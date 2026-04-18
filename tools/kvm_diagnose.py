#!/usr/bin/env python3
"""KVM USB-Switch Diagnose Tool.

Captures Thunderbolt + USB device state before and after a KVM switch
to help diagnose the "Thunderbolt gives USB not free" issue (WD22TB4 etc.).

Usage:
    python tools/kvm_diagnose.py              # Capture current state
    python tools/kvm_diagnose.py --before     # Save 'before' snapshot
    python tools/kvm_diagnose.py --after      # Save 'after' snapshot and diff
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_SNAPSHOT_DIR = Path(tempfile.gettempdir()) / "desk2ha_kvm_diag"


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


def _collect_windows() -> dict:
    """Collect Thunderbolt + USB state on Windows."""
    data: dict = {"platform": "windows", "timestamp": _now()}

    # Thunderbolt devices
    data["thunderbolt_devices"] = _run(
        [
            "powershell",
            "-Command",
            "Get-PnpDevice -Class Thunderbolt -ErrorAction SilentlyContinue "
            "| Select-Object Status,InstanceId,FriendlyName "
            "| ConvertTo-Json -Depth 3",
        ]
    )

    # USB controllers and devices
    data["usb_controllers"] = _run(
        [
            "powershell",
            "-Command",
            "Get-PnpDevice -Class USB "
            "| Select-Object Status,InstanceId,FriendlyName "
            "| ConvertTo-Json -Depth 3",
        ]
    )

    # USB devices with problems
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

    # USB Selective Suspend setting
    data["usb_selective_suspend"] = _run(
        [
            "powershell",
            "-Command",
            "powercfg /query SCHEME_CURRENT "
            "2a737441-1930-4402-8d77-b2bebba308a3 "
            "48e6b7a6-50f5-4782-a5d4-53bb8f07e226",
        ]
    )

    # USB device count
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
    data["thunderbolt_names"] = _run(
        ["bash", "-c", "cat /sys/bus/thunderbolt/devices/*/device_name 2>/dev/null"]
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def collect() -> dict:
    """Collect platform-specific Thunderbolt + USB snapshot."""
    if sys.platform == "win32":
        return _collect_windows()
    elif sys.platform == "darwin":
        return _collect_macos()
    else:
        return _collect_linux()


def save_snapshot(name: str) -> Path:
    """Collect and save a snapshot to temp directory."""
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    data = collect()
    path = _SNAPSHOT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def diff_snapshots() -> str | None:
    """Compare before/after snapshots and return a human-readable diff."""
    before_path = _SNAPSHOT_DIR / "before.json"
    after_path = _SNAPSHOT_DIR / "after.json"

    if not before_path.exists() or not after_path.exists():
        return None

    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("KVM USB-Switch Diagnose — Diff")
    lines.append("=" * 60)
    lines.append(f"Before: {before.get('timestamp', '?')}")
    lines.append(f"After:  {after.get('timestamp', '?')}")
    lines.append("")

    # Compare USB device counts
    count_before = before.get("usb_device_count", "?")
    count_after = after.get("usb_device_count", "?")
    lines.append(f"USB Device Count: {count_before} -> {count_after}")

    # Compare USB problems
    prob_before = before.get("usb_problems", "")
    prob_after = after.get("usb_problems", "")
    if prob_before != prob_after:
        lines.append("")
        lines.append("USB Problems CHANGED:")
        lines.append(f"  Before: {prob_before[:200]}")
        lines.append(f"  After:  {prob_after[:200]}")

    # Compare Thunderbolt devices
    tb_before = before.get("thunderbolt_devices", "")
    tb_after = after.get("thunderbolt_devices", "")
    if tb_before != tb_after:
        lines.append("")
        lines.append("Thunderbolt Devices CHANGED:")
        lines.append(f"  Before: {tb_before[:200]}")
        lines.append(f"  After:  {tb_after[:200]}")

    lines.append("")
    lines.append(f"Full snapshots: {_SNAPSHOT_DIR}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="KVM USB-Switch Diagnose Tool")
    parser.add_argument(
        "--before",
        action="store_true",
        help="Save 'before KVM switch' snapshot",
    )
    parser.add_argument(
        "--after",
        action="store_true",
        help="Save 'after KVM switch' snapshot and show diff",
    )
    args = parser.parse_args()

    if args.before:
        path = save_snapshot("before")
        print(f"Before snapshot saved: {path}")
        print("Now switch KVM and run: python tools/kvm_diagnose.py --after")
    elif args.after:
        path = save_snapshot("after")
        print(f"After snapshot saved: {path}")
        diff = diff_snapshots()
        if diff:
            print()
            print(diff)
        else:
            print("No 'before' snapshot found. Run --before first.")
    else:
        # Just show current state
        data = collect()
        print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    main()
