"""USB Watchdog — detects stale USB state after KVM switch and optionally resets.

Periodically checks USB device count. If devices drop to zero while the
Thunderbolt link is still active, the USB subsystem is likely in a stale
state caused by a KVM switch not releasing USB properly.

Emits metrics:
    system.usb_device_count  — current number of healthy USB devices
    system.usb_reset_count   — cumulative resets performed
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desk2ha_agent.state import StateCache

logger = logging.getLogger(__name__)


class UsbWatchdog:
    """Monitor USB subsystem health and reset on stale state."""

    def __init__(
        self,
        state: StateCache,
        *,
        interval: int = 30,
        auto_reset: bool = False,
    ) -> None:
        self._state = state
        self._interval = interval
        self._auto_reset = auto_reset
        self._reset_count = 0
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the watchdog loop."""
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "USB watchdog started (interval=%ds, auto_reset=%s)",
            self._interval,
            self._auto_reset,
        )

    async def stop(self) -> None:
        """Stop the watchdog loop."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("USB watchdog stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._check()
            except Exception:
                logger.debug("USB watchdog check failed", exc_info=True)
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        device_count = await asyncio.to_thread(_get_usb_device_count)
        tb_active = await asyncio.to_thread(_is_thunderbolt_active)

        metrics: dict[str, Any] = {
            "system.usb_device_count": {
                "value": device_count,
                "unit": None,
                "timestamp": None,
            },
            "system.usb_reset_count": {
                "value": self._reset_count,
                "unit": None,
                "timestamp": None,
            },
        }
        await self._state.update(metrics)

        if device_count == 0 and tb_active:
            logger.warning("USB stale state detected: 0 USB devices but Thunderbolt is active")
            if self._auto_reset:
                result = await usb_reset()
                if result.get("status") == "completed":
                    self._reset_count += 1
                    await self._state.update(
                        {
                            "system.usb_reset_count": {
                                "value": self._reset_count,
                                "unit": None,
                                "timestamp": None,
                            }
                        }
                    )


async def usb_reset() -> dict[str, str]:
    """Reset USB host controllers to recover from stale KVM state."""
    return await asyncio.to_thread(_usb_reset_sync)


def _usb_reset_sync() -> dict[str, str]:
    """Platform-specific USB host controller reset."""
    try:
        if sys.platform == "win32":
            # Restart all USB host controllers via pnputil (available on Win10+)
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Get-PnpDevice -Class USB "
                    "| Where-Object { $_.FriendlyName -like '*Host Controller*' } "
                    "| ForEach-Object { "
                    "  Disable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false; "
                    "  Start-Sleep -Milliseconds 500; "
                    "  Enable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false "
                    "}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("USB host controllers reset successfully")
                return {"status": "completed", "action": "usb_reset"}
            else:
                msg = result.stderr.strip() or "Unknown error"
                logger.error("USB reset failed: %s", msg)
                return {"status": "failed", "message": msg}

        elif sys.platform == "linux":
            # Toggle authorized flag on all USB root hubs
            import glob

            root_hubs = glob.glob("/sys/bus/usb/devices/usb*/authorized")
            if not root_hubs:
                return {"status": "failed", "message": "No USB root hubs found"}
            for hub in root_hubs:
                try:
                    with open(hub, "w") as f:
                        f.write("0")
                    with open(hub, "w") as f:
                        f.write("1")
                except PermissionError:
                    return {
                        "status": "failed",
                        "message": "Permission denied — run as root",
                    }
            logger.info("USB root hubs reset: %d hubs", len(root_hubs))
            return {"status": "completed", "action": "usb_reset"}

        else:
            return {
                "status": "failed",
                "message": f"USB reset not supported on {sys.platform}",
            }

    except Exception as exc:
        logger.exception("USB reset failed")
        return {"status": "failed", "message": str(exc)}


def _get_usb_device_count() -> int:
    """Count active USB devices on the system."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "(Get-PnpDevice -Class USB | Where-Object { $_.Status -eq 'OK' }).Count",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            count_str = result.stdout.strip()
            return int(count_str) if count_str.isdigit() else 0

        elif sys.platform == "linux":
            result = subprocess.run(
                ["lsusb"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return len(result.stdout.strip().splitlines()) if result.stdout else 0

        elif sys.platform == "darwin":
            result = subprocess.run(
                ["system_profiler", "SPUSBDataType"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Count lines with "Product ID:" as rough device count
            return result.stdout.count("Product ID:") if result.stdout else 0

    except Exception:
        logger.debug("Failed to count USB devices", exc_info=True)
    return 0


def _is_thunderbolt_active() -> bool:
    """Check if a Thunderbolt connection is active."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "(Get-PnpDevice -Class Thunderbolt -ErrorAction SilentlyContinue "
                    "| Where-Object { $_.Status -eq 'OK' }).Count",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            count_str = result.stdout.strip()
            return int(count_str) > 0 if count_str.isdigit() else False

        elif sys.platform == "linux":
            import glob

            return len(glob.glob("/sys/bus/thunderbolt/devices/*/device_name")) > 0

    except Exception:
        logger.debug("Failed to check Thunderbolt status", exc_info=True)
    return False
