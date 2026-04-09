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
        capabilities={"thermals", "control"},
        description="Lenovo WMI/sysfs telemetry (thermals, fans, battery mode)",
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

            # Battery conservation mode
            try:
                settings = conn.query(
                    "SELECT * FROM Lenovo_BiosSetting "
                    "WHERE CurrentSetting LIKE 'ChargeMode%' "
                    "OR CurrentSetting LIKE 'Conservation%'"
                )
                for s in settings:
                    val = getattr(s, "CurrentSetting", "")
                    if val:
                        parts = val.split(",")
                        if len(parts) >= 2:
                            metrics["battery.charge_mode"] = metric_value(parts[1])
                            break
            except Exception:
                logger.debug("Lenovo battery mode query failed", exc_info=True)

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

        # Battery conservation mode (ThinkPad via sysfs, IdeaPad via ideapad_acpi)
        conservation_path = _IDEAPAD_ACPI / "conservation_mode"
        if conservation_path.exists():
            try:
                val = int(conservation_path.read_text().strip())
                mode = "conservation" if val == 1 else "normal"
                metrics["battery.charge_mode"] = metric_value(mode)
            except Exception:
                pass
        elif self._is_linux_thinkpad:
            # ThinkPad: infer mode from charge thresholds
            start_path = Path("/sys/class/power_supply/BAT0/charge_control_start_threshold")
            end_path = Path("/sys/class/power_supply/BAT0/charge_control_end_threshold")
            if start_path.exists() and end_path.exists():
                try:
                    start = int(start_path.read_text().strip())
                    end = int(end_path.read_text().strip())
                    if end <= 60:
                        mode = "conservation"
                    elif end >= 95 and start <= 5:
                        mode = "express"
                    else:
                        mode = "normal"
                    metrics["battery.charge_mode"] = metric_value(mode)
                except Exception:
                    pass

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if command == "battery.set_charge_mode":
            return await asyncio.to_thread(self._set_charge_mode, parameters)
        if command == "lenovo.set_thermal_profile":
            return await asyncio.to_thread(self._set_thermal_profile, parameters)
        raise NotImplementedError

    def _set_charge_mode(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Set battery charge mode: conservation, normal, or express."""
        mode = parameters.get("mode", "normal")
        if mode not in ("conservation", "normal", "express"):
            return {"status": "failed", "message": f"Unknown mode: {mode}"}

        if sys.platform == "linux":
            conservation_path = _IDEAPAD_ACPI / "conservation_mode"
            if conservation_path.exists():
                try:
                    val = "1" if mode == "conservation" else "0"
                    conservation_path.write_text(val)
                    return {"status": "completed", "mode": mode}
                except PermissionError:
                    return {"status": "failed", "message": "Permission denied (need root)"}
            elif self._is_linux_thinkpad:
                thresholds = {
                    "conservation": (0, 60),
                    "normal": (0, 100),
                    "express": (0, 100),
                }
                start, end = thresholds[mode]
                try:
                    start_path = Path(
                        "/sys/class/power_supply/BAT0/charge_control_start_threshold"
                    )
                    end_path = Path("/sys/class/power_supply/BAT0/charge_control_end_threshold")
                    end_path.write_text(str(end))
                    start_path.write_text(str(start))
                    return {"status": "completed", "mode": mode}
                except PermissionError:
                    return {"status": "failed", "message": "Permission denied (need root)"}

        if sys.platform == "win32":
            try:
                import pythoncom
                import wmi

                pythoncom.CoInitialize()
                try:
                    conn = wmi.WMI(namespace=r"root\Lenovo\Lenovo_BiosSettingInterface")
                    # WMI set method varies by model; this is a best-effort approach
                    wmi_mode_map = {
                        "conservation": "Conservation",
                        "normal": "Normal",
                        "express": "Express",
                    }
                    conn.Lenovo_SetBiosSetting(f"ChargeMode,{wmi_mode_map[mode]}")
                    conn.Lenovo_SaveBiosSettings()
                    return {"status": "completed", "mode": mode}
                finally:
                    pythoncom.CoUninitialize()
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}

        return {"status": "failed", "message": "Unsupported platform"}

    def _set_thermal_profile(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Set thermal profile via WMI or sysfs."""
        profile = parameters.get("profile", "balanced")

        if sys.platform == "linux":
            perf_path = _IDEAPAD_ACPI / "performance_mode"
            if perf_path.exists():
                mode_map = {
                    "intelligent_cooling": "0",
                    "balanced": "0",
                    "extreme_performance": "1",
                    "performance": "1",
                    "battery_saving": "2",
                    "quiet": "2",
                }
                val = mode_map.get(profile)
                if val is None:
                    return {"status": "failed", "message": f"Unknown profile: {profile}"}
                try:
                    perf_path.write_text(val)
                    return {"status": "completed", "profile": profile}
                except PermissionError:
                    return {"status": "failed", "message": "Permission denied (need root)"}

        if sys.platform == "win32":
            try:
                import pythoncom
                import wmi

                pythoncom.CoInitialize()
                try:
                    conn = wmi.WMI(namespace=r"root\Lenovo\Lenovo_BiosSettingInterface")
                    conn.Lenovo_SetBiosSetting(f"ThermalMode,{profile}")
                    conn.Lenovo_SaveBiosSettings()
                    return {"status": "completed", "profile": profile}
                finally:
                    pythoncom.CoUninitialize()
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}

        return {"status": "failed", "message": "Unsupported platform"}

    async def teardown(self) -> None:
        self._available = False


COLLECTOR_CLASS = LenovoWmiCollector
