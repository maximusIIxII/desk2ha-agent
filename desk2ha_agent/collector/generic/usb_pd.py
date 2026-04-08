"""USB Power Delivery collector.

Reads USB PD charging information on Windows (via WMI UcmCx/battery) and
Linux (via sysfs power_supply). Reports power delivery wattage, voltage,
and connected USB-C port information — useful for monitoring docks and
chargers.
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


class USBPDCollector(Collector):
    """Collect USB Power Delivery metrics."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="usb_pd",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX},
        capabilities={"power"},
        description="USB Power Delivery wattage and charger information",
    )

    def __init__(self) -> None:
        self._has_pd_info: bool = False

    async def probe(self) -> bool:
        """Check if USB PD information is available."""
        if sys.platform == "win32":
            return await self._probe_windows()
        if sys.platform == "linux":
            return await self._probe_linux()
        return False

    async def _probe_windows(self) -> bool:
        """Check for USB PD info via psutil/WMI battery power info."""
        try:
            import psutil

            battery = psutil.sensors_battery()
            if battery is None:
                return False
            # If we have a battery with power_plugged info, we can report PD
            self._has_pd_info = battery.power_plugged is not None
            return self._has_pd_info
        except Exception:
            return False

    async def _probe_linux(self) -> bool:
        """Check for USB PD info in sysfs power_supply."""
        try:
            ps_path = Path("/sys/class/power_supply")
            if not ps_path.exists():
                return False

            for supply in ps_path.iterdir():
                supply_type = (supply / "type").read_text().strip().lower()
                if supply_type in ("usb", "usb_pd", "mains"):
                    self._has_pd_info = True
                    return True
            return False
        except Exception:
            return False

    async def setup(self) -> None:
        logger.info("USB PD collector activated")

    async def collect(self) -> dict[str, Any]:
        if sys.platform == "win32":
            return await asyncio.to_thread(self._collect_windows)
        if sys.platform == "linux":
            return self._collect_linux()
        return {}

    def _collect_windows(self) -> dict[str, Any]:
        """Collect USB PD metrics on Windows."""
        metrics: dict[str, Any] = {}

        try:
            import psutil

            battery = psutil.sensors_battery()
            if battery is None:
                return {}

            # Power plugged status
            if battery.power_plugged is not None:
                metrics["power.usb_pd_connected"] = metric_value(battery.power_plugged)

            # Try to get power rate from WMI (watts being drawn/charged)
            try:
                self._collect_wmi_power(metrics)
            except Exception:
                logger.debug("WMI power query failed", exc_info=True)

        except Exception:
            logger.debug("USB PD Windows collection failed", exc_info=True)

        return metrics

    def _collect_wmi_power(self, metrics: dict[str, Any]) -> None:
        """Read charging rate from WMI BatteryStatus."""
        import pythoncom  # type: ignore[import-untyped]
        import wmi  # type: ignore[import-untyped]

        pythoncom.CoInitialize()
        try:
            conn = wmi.WMI()
            # Win32_Battery has EstimatedChargeRemaining and BatteryStatus
            batteries = conn.Win32_Battery()
            if not batteries:
                return

            bat = batteries[0]

            # Check for charging rate via BatteryStatus
            # Status 6-9 = various charging states
            status_code = getattr(bat, "BatteryStatus", None)
            if status_code is not None:
                is_charging = int(status_code) in (6, 7, 8, 9)
                metrics["power.charging"] = metric_value(is_charging)

            # DesignVoltage in millivolts
            voltage = getattr(bat, "DesignVoltage", None)
            if voltage is not None and int(voltage) > 0:
                metrics["power.design_voltage"] = metric_value(
                    round(int(voltage) / 1000, 2), unit="V"
                )
        finally:
            pythoncom.CoUninitialize()

    def _collect_linux(self) -> dict[str, Any]:
        """Collect USB PD metrics from sysfs."""
        metrics: dict[str, Any] = {}
        ps_path = Path("/sys/class/power_supply")

        if not ps_path.exists():
            return {}

        for supply in ps_path.iterdir():
            try:
                supply_type = (supply / "type").read_text().strip().lower()
                if supply_type not in ("usb", "usb_pd", "mains"):
                    continue

                name = supply.name
                prefix = f"power.pd_{name}"

                # Online status
                online_path = supply / "online"
                if online_path.exists():
                    online = online_path.read_text().strip()
                    metrics[f"{prefix}.connected"] = metric_value(online == "1")

                # Voltage
                voltage_path = supply / "voltage_now"
                if voltage_path.exists():
                    voltage_uv = int(voltage_path.read_text().strip())
                    metrics[f"{prefix}.voltage"] = metric_value(
                        round(voltage_uv / 1_000_000, 2), unit="V"
                    )

                # Current
                current_path = supply / "current_now"
                if current_path.exists():
                    current_ua = int(current_path.read_text().strip())
                    metrics[f"{prefix}.current"] = metric_value(
                        round(current_ua / 1_000_000, 3), unit="A"
                    )

                # Power (voltage * current)
                if (supply / "voltage_now").exists() and (supply / "current_now").exists():
                    v = int((supply / "voltage_now").read_text().strip()) / 1_000_000
                    a = int((supply / "current_now").read_text().strip()) / 1_000_000
                    watts = round(v * a, 1)
                    metrics[f"{prefix}.power_watts"] = metric_value(watts, unit="W")

                # Manufacturer/model
                for attr in ("manufacturer", "model_name"):
                    attr_path = supply / attr
                    if attr_path.exists():
                        val = attr_path.read_text().strip()
                        if val:
                            metrics[f"{prefix}.{attr}"] = metric_value(val)

            except Exception:
                logger.debug("Failed to read %s", supply.name, exc_info=True)

        return metrics

    async def teardown(self) -> None:
        self._has_pd_info = False


COLLECTOR_CLASS = USBPDCollector
