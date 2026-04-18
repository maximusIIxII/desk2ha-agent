"""KVM USB-Switch diagnostics for system.kvm_diagnose command.

Captures Thunderbolt + USB device state to help diagnose KVM switching issues
(e.g. WD22TB4 "Thunderbolt gives USB not free" problem).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime


def _run(cmd: list[str], *, timeout: int = 10) -> str:
    """Run a command and return stdout, or error string."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except FileNotFoundError:
        return f"[command not found: {cmd[0]}]"
    except subprocess.TimeoutExpired:
        return "[timeout]"
    except Exception as exc:
        return f"[error: {exc}]"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _collect_windows() -> dict:
    """Collect Thunderbolt + USB state on Windows."""
    data: dict = {"platform": "windows", "timestamp": _now()}

    data["thunderbolt_devices"] = _run(
        [
            "powershell",
            "-Command",
            "Get-PnpDevice -Class Thunderbolt -ErrorAction SilentlyContinue "
            "| Select-Object Status,InstanceId,FriendlyName "
            "| ConvertTo-Json -Depth 3",
        ]
    )

    data["usb_controllers"] = _run(
        [
            "powershell",
            "-Command",
            "Get-PnpDevice -Class USB "
            "| Select-Object Status,InstanceId,FriendlyName "
            "| ConvertTo-Json -Depth 3",
        ]
    )

    data["usb_problems"] = _run(
        [
            "powershell",
            "-Command",
            "Get-PnpDevice -Class USB "
            "| Where-Object { $_.Status -ne 'OK' } "
            "| Select-Object Status,InstanceId,FriendlyName "
            "| ConvertTo-Json -Depth 3",
        ]
    )

    data["usb_device_count"] = _run(
        [
            "powershell",
            "-Command",
            "(Get-PnpDevice -Class USB | Where-Object { $_.Status -eq 'OK' }).Count",
        ]
    )

    return data


def _collect_linux() -> dict:
    """Collect Thunderbolt + USB state on Linux."""
    data: dict = {"platform": "linux", "timestamp": _now()}

    data["thunderbolt_devices"] = _run(
        ["bash", "-c", "ls -la /sys/bus/thunderbolt/devices/ 2>/dev/null"]
    )
    data["usb_tree"] = _run(["lsusb", "-t"])
    data["usb_devices"] = _run(["lsusb"])
    data["usb_device_count"] = _run(["bash", "-c", "lsusb | wc -l"])

    return data


def _collect_macos() -> dict:
    """Collect Thunderbolt + USB state on macOS."""
    data: dict = {"platform": "macos", "timestamp": _now()}

    data["thunderbolt_info"] = _run(["system_profiler", "SPThunderboltDataType", "-json"])
    data["usb_info"] = _run(["system_profiler", "SPUSBDataType", "-json"])

    return data


def _collect_sync() -> dict:
    """Collect platform-specific Thunderbolt + USB snapshot."""
    if sys.platform == "win32":
        return _collect_windows()
    elif sys.platform == "darwin":
        return _collect_macos()
    else:
        return _collect_linux()


async def kvm_diagnose() -> dict:
    """Async wrapper for KVM diagnostics collection."""
    return await asyncio.to_thread(_collect_sync)
