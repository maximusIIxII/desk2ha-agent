"""Keyboard backlight collector and control.

Reads and controls keyboard backlight level via platform-specific APIs:
- Linux: /sys/class/leds/*kbd_backlight*/brightness
- Windows: WMI (vendor-specific) or HID
- macOS: IOKit (Apple Silicon / Intel)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)


def _find_linux_kbd_backlight() -> Path | None:
    """Find the sysfs path for keyboard backlight."""
    leds = Path("/sys/class/leds")
    if not leds.exists():
        return None
    for led in leds.iterdir():
        if (
            "kbd" in led.name.lower()
            and "backlight" in led.name.lower()
            and (led / "brightness").exists()
        ):
            return led
    return None


class KeyboardBacklightCollector(Collector):
    """Read and control keyboard backlight level."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="keyboard_backlight",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"control"},
        description="Keyboard backlight level read/write",
    )

    def __init__(self) -> None:
        self._sysfs_path: Path | None = None
        self._max_brightness: int = 0

    async def probe(self) -> bool:
        if sys.platform == "linux":
            self._sysfs_path = _find_linux_kbd_backlight()
            if self._sysfs_path is not None:
                try:
                    self._max_brightness = int(
                        (self._sysfs_path / "max_brightness").read_text().strip()
                    )
                    return True
                except Exception:
                    return False
        if sys.platform == "win32":
            return await asyncio.to_thread(self._probe_windows)
        return False

    def _probe_windows(self) -> bool:
        """Try WMI keyboard backlight (Dell/Lenovo/HP)."""
        try:
            import pythoncom
            import wmi

            pythoncom.CoInitialize()
            try:
                # Dell
                try:
                    conn = wmi.WMI(namespace=r"root\Dell\SYSMAN")
                    items = conn.query(
                        "SELECT * FROM DCIM_Keyboard WHERE AttributeName='Keyboard Illumination'"
                    )
                    if list(items):
                        self._max_brightness = 100
                        return True
                except Exception:
                    pass

                # Generic WMI approach — check if keyboard backlight class exists
                try:
                    conn = wmi.WMI(namespace=r"root\WMI")
                    items = conn.query("SELECT * FROM WmiMonitorBrightness")
                    # This is monitor brightness, not keyboard. Skip.
                except Exception:
                    pass

                return False
            finally:
                pythoncom.CoUninitialize()
        except ImportError:
            return False

    async def setup(self) -> None:
        logger.info("Keyboard backlight collector activated (max=%d)", self._max_brightness)

    async def collect(self) -> dict[str, Any]:
        if sys.platform == "linux" and self._sysfs_path:
            return self._collect_linux()
        if sys.platform == "win32":
            return await asyncio.to_thread(self._collect_windows)
        return {}

    def _collect_linux(self) -> dict[str, Any]:
        try:
            brightness = int((self._sysfs_path / "brightness").read_text().strip())
            pct = round(brightness / self._max_brightness * 100) if self._max_brightness else 0
            return {
                "system.keyboard_backlight": metric_value(float(pct), unit="%"),
                "system.keyboard_backlight_raw": metric_value(float(brightness)),
            }
        except Exception:
            return {}

    def _collect_windows(self) -> dict[str, Any]:
        # Windows keyboard backlight reads are vendor-specific and typically
        # require admin. Report as available for command control.
        return {}

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if command != "keyboard.set_backlight":
            raise NotImplementedError

        value = parameters.get("value")
        if value is None:
            return {"status": "failed", "message": "Missing 'value' parameter"}

        level = int(value)
        if level < 0 or level > 100:
            return {"status": "failed", "message": "Value must be 0-100"}

        if sys.platform == "linux" and self._sysfs_path:
            return await asyncio.to_thread(self._set_linux, level)
        return {"status": "failed", "message": "Not supported on this platform"}

    def _set_linux(self, level_pct: int) -> dict[str, Any]:
        """Set keyboard backlight via sysfs."""
        try:
            raw = round(level_pct / 100 * self._max_brightness)
            (self._sysfs_path / "brightness").write_text(str(raw))
            return {"status": "completed", "level": level_pct}
        except PermissionError:
            return {"status": "failed", "message": "Permission denied (need root)"}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    async def teardown(self) -> None:
        pass


COLLECTOR_CLASS = KeyboardBacklightCollector
