"""Lenovo WMI/sysfs vendor collector.

Windows: reads from Lenovo WMI namespace ``root\\WMI`` (Lenovo-specific classes)
and ``root\\Lenovo\\Lenovo_BiosSettingInterface``.

Linux: reads from ``/sys/devices/platform/thinkpad_acpi/`` for ThinkPad-specific
metrics (fan speed, thermal mode, battery thresholds).
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

_THINKPAD_ACPI = Path("/sys/devices/platform/thinkpad_acpi")
_IDEAPAD_ACPI = Path("/sys/devices/platform/ideapad_acpi")


class LenovoWmiCollector(Collector):
    """Collect thermals, fan, and battery data from Lenovo WMI/sysfs."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="lenovo_wmi",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX},
        capabilities={"thermals"},
        description="Lenovo WMI/sysfs telemetry (thermals, fans, battery thresholds)",
        requires_hardware="Lenovo ThinkPad/IdeaPad/Legion",
    )

    def __init__(self) -> None:
        self._available: bool = False
        self._is_linux_thinkpad: bool = False

    async def probe(self) -> bool:
        if sys.platform == "win32":
            return await asyncio.to_thread(self._probe_windows)
        if sys.platform == "linux":
            return self._probe_linux()
        return False

    def _probe_windows(self) -> bool:
        try:
            import pythoncom
            import wmi

            pythoncom.CoInitialize()
            try:
                # Try Lenovo BIOS WMI namespace
                conn = wmi.WMI(namespace=r"root\WMI")
                # Lenovo_BiosSetting is available on ThinkPads
                items = conn.query("SELECT * FROM Lenovo_BiosSetting")
                count = len(list(items))
                if count > 0:
                    logger.info("Lenovo WMI: found %d BIOS settings", count)
                    return True
                return False
            finally:
                pythoncom.CoUninitialize()
        except ImportError:
            return False
        except Exception:
            logger.debug("Lenovo WMI probe failed", exc_info=True)
            return False

    def _probe_linux(self) -> bool:
        if _THINKPAD_ACPI.exists():
            self._is_linux_thinkpad = True
            logger.info("Lenovo: detected thinkpad_acpi")
            return True
        if _IDEAPAD_ACPI.exists():
            logger.info("Lenovo: detected ideapad_acpi")
            return True
        return False

    async def setup(self) -> None:
        self._available = True
        logger.info("Lenovo collector activated")

    async def collect(self) -> dict[str, Any]:
        if not self._available:
            return {}
        if sys.platform == "win32":
            return await asyncio.to_thread(self._collect_windows)
        if sys.platform == "linux":
            return self._collect_linux()
        return {}

    def _collect_windows(self) -> dict[str, Any]:
        import pythoncom
        import wmi

        pythoncom.CoInitialize()
        try:
            metrics: dict[str, Any] = {}
            conn = wmi.WMI(namespace=r"root\WMI")

            # Fan speed
            try:
                fans = conn.query("SELECT * FROM Lenovo_FanSpeedSensor")
                for i, fan in enumerate(fans):
                    speed = getattr(fan, "CurrentFanSpeed", None)
                    if speed is not None:
                        key = "fan.cpu" if i == 0 else f"fan.{i}"
                        metrics[key] = metric_value(float(speed), unit="/min")
            except Exception:
                logger.debug("Lenovo fan query failed", exc_info=True)

            # Thermal profile / performance mode
            try:
                settings = conn.query(
                    "SELECT * FROM Lenovo_BiosSetting WHERE CurrentSetting LIKE 'ThermalMode%'"
                )
                for s in settings:
                    val = getattr(s, "CurrentSetting", "")
                    if val:
                        # Format: "ThermalMode,Balanced"
                        parts = val.split(",")
                        if len(parts) >= 2:
                            metrics["thermal_profile"] = metric_value(parts[1])
            except Exception:
                logger.debug("Lenovo thermal profile query failed", exc_info=True)

            return metrics
        except Exception:
            logger.exception("Lenovo WMI collection failed")
            return {}
        finally:
            pythoncom.CoUninitialize()

    def _collect_linux(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        # ThinkPad fan speed
        fan_path = _THINKPAD_ACPI / "fan1_input"
        if fan_path.exists():
            try:
                rpm = int(fan_path.read_text().strip())
                metrics["fan.cpu"] = metric_value(float(rpm), unit="/min")
            except Exception:
                pass

        # ThinkPad fan level
        fan_level = _THINKPAD_ACPI / "fan_watchdog"
        if fan_level.exists():
            try:
                val = fan_level.read_text().strip()
                metrics["fan.watchdog"] = metric_value(val)
            except Exception:
                pass

        # Battery charge thresholds (ThinkPad specific)
        for bat_idx in range(2):
            start = Path(f"/sys/class/power_supply/BAT{bat_idx}/charge_control_start_threshold")
            end = Path(f"/sys/class/power_supply/BAT{bat_idx}/charge_control_end_threshold")
            if start.exists():
                try:
                    val = int(start.read_text().strip())
                    metrics[f"battery.charge_start_threshold_{bat_idx}"] = metric_value(
                        float(val), unit="%"
                    )
                except Exception:
                    pass
            if end.exists():
                try:
                    val = int(end.read_text().strip())
                    metrics[f"battery.charge_end_threshold_{bat_idx}"] = metric_value(
                        float(val), unit="%"
                    )
                except Exception:
                    pass

        # Performance mode (ideapad)
        perf_path = _IDEAPAD_ACPI / "performance_mode" if not self._is_linux_thinkpad else None
        if perf_path and perf_path.exists():
            try:
                mode = int(perf_path.read_text().strip())
                mode_map = {
                    0: "intelligent_cooling",
                    1: "extreme_performance",
                    2: "battery_saving",
                }
                metrics["thermal_profile"] = metric_value(mode_map.get(mode, f"mode_{mode}"))
            except Exception:
                pass

        return metrics

    async def teardown(self) -> None:
        self._available = False


COLLECTOR_CLASS = LenovoWmiCollector
