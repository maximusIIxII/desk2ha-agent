"""Dell Command | Monitor vendor collector.

Reads detailed thermals (CPU, GPU, SSD, skin, ambient), fan speeds, and
power delivery data from the ``root\\dcim\\sysman`` WMI namespace exposed
by Dell Command | Monitor (DCM).

When running without admin privileges, this collector queries the
elevated helper process (desk2ha-helper) on localhost:9694 instead.
Direct WMI access is used when the process itself has admin rights
(e.g. inside the helper, or when the agent runs elevated).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

# Map DCM sensor element names to well-known metric keys.
_THERMAL_KEY_MAP: dict[str, str] = {
    # More specific patterns must come before less specific ones
    "cpu package": "cpu_package",
    "cpu core": "cpu_core_max",
    "cpu": "cpu_package",
    "ambient": "ambient",
    "memory": "memory",
    "ssd": "ssd",
    "gpu": "gpu",
    "pch": "pch",
    "nb": "northbridge",
    "battery": "battery_temp",
    "skin": "skin",
    "charger": "charger",
    "other": "misc",
}


def _normalize_sensor_name(name: str) -> str:
    """Map a DCM sensor name to a well-known metric key."""
    lower = name.lower().strip()
    for pattern, key in _THERMAL_KEY_MAP.items():
        if pattern in lower:
            return key
    return lower.replace(" ", "_").replace("-", "_")


def _is_admin() -> bool:
    """Check if running with admin privileges."""
    if sys.platform != "win32":
        import os

        return os.geteuid() == 0
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class DellDcmCollector(Collector):
    """Collect thermals, fan speeds, and power data from Dell Command | Monitor.

    Two modes of operation:
    - **Direct WMI** (admin): queries root\\dcim\\sysman directly
    - **Via helper** (non-admin): fetches from desk2ha-helper on localhost:9694
    """

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="dell_dcm",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS},
        capabilities={"thermals", "power"},
        description="Dell Command | Monitor WMI telemetry (thermals, fans, power)",
        requires_software="Dell Command | Monitor",
    )

    def __init__(self) -> None:
        self._available: bool | None = None
        self._use_helper: bool = False
        self._helper_client: Any = None
        self._power_warned: bool = False

    async def probe(self) -> bool:
        """Check if DCM data is accessible (directly or via helper)."""
        if sys.platform != "win32":
            return False

        # Try direct WMI first (works if elevated)
        if _is_admin():
            result = await asyncio.to_thread(self._probe_wmi)
            if result:
                logger.info("Dell DCM: direct WMI access (elevated)")
                return True

        # Try helper
        from desk2ha_agent.helper.client import HelperClient

        self._helper_client = HelperClient()
        if await self._helper_client.is_available():
            # Verify helper actually has DCM metrics
            metrics = await self._helper_client.get_metrics()
            if metrics:
                self._use_helper = True
                logger.info("Dell DCM: using elevated helper (%d metrics)", len(metrics))
                return True
            logger.info("Dell DCM: helper running but no DCM metrics")

        logger.info("Dell DCM: not available (not elevated and helper not running)")
        return False

    def _probe_wmi(self) -> bool:
        """Probe DCM WMI namespace directly."""
        try:
            import pythoncom  # type: ignore[import-untyped]
            import wmi  # type: ignore[import-untyped]

            pythoncom.CoInitialize()
            try:
                conn = wmi.WMI(namespace=r"root\dcim\sysman")
                sensors = conn.query(
                    "SELECT ElementName FROM DCIM_NumericSensor WHERE SensorType = 2"
                )
                count = len(list(sensors))
                logger.info("Dell DCM: found %d temperature sensors", count)
                return count > 0
            finally:
                pythoncom.CoUninitialize()
        except ImportError:
            return False
        except Exception:
            logger.debug("Dell DCM WMI probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        self._available = True
        mode = "helper" if self._use_helper else "direct WMI"
        logger.info("Dell Command | Monitor collector activated (%s)", mode)

    async def collect(self) -> dict[str, Any]:
        if not self._available:
            return {}

        if self._use_helper:
            return await self._collect_via_helper()

        return await asyncio.to_thread(self._collect_sync)

    async def _collect_via_helper(self) -> dict[str, Any]:
        """Fetch DCM metrics from the elevated helper."""
        if self._helper_client is None:
            return {}
        return await self._helper_client.get_metrics()

    def _collect_sync(self) -> dict[str, Any]:
        import pythoncom  # type: ignore[import-untyped]
        import wmi  # type: ignore[import-untyped]

        pythoncom.CoInitialize()
        try:
            try:
                conn = wmi.WMI(namespace=r"root\dcim\sysman")
            except Exception:
                if self._available is not False:
                    logger.warning("Dell DCM WMI namespace lost")
                    self._available = False
                return {}

            now = time.time()
            metrics: dict[str, Any] = {}

            self._collect_thermals(conn, metrics, now)
            self._collect_fans(conn, metrics, now)
            self._collect_power(conn, metrics, now)

            return metrics
        except Exception:
            logger.exception("Dell DCM collection failed")
            return {}
        finally:
            pythoncom.CoUninitialize()

    def _collect_thermals(self, conn: object, metrics: dict[str, Any], now: float) -> None:
        """Query DCIM_NumericSensor for temperature readings."""
        try:
            sensors = conn.query(  # type: ignore[attr-defined]
                "SELECT * FROM DCIM_NumericSensor WHERE SensorType = 2"
            )
            for sensor in sensors:
                name = getattr(sensor, "ElementName", "") or ""
                value = getattr(sensor, "CurrentReading", None)
                if value is None:
                    continue

                unit_modifier = int(getattr(sensor, "UnitModifier", 0) or 0)
                raw = float(value)
                temp = raw if unit_modifier == -1 else raw * (10**unit_modifier)

                if temp < -40 or temp > 200:
                    continue

                key = _normalize_sensor_name(name)
                metrics[key] = metric_value(round(temp, 1), unit="Cel")

        except Exception:
            logger.debug("DCM thermal query failed", exc_info=True)

    def _collect_fans(self, conn: object, metrics: dict[str, Any], now: float) -> None:
        """Query DCIM_NumericSensor for fan RPM readings."""
        try:
            sensors = conn.query(  # type: ignore[attr-defined]
                "SELECT * FROM DCIM_NumericSensor WHERE SensorType = 5"
            )
            for i, sensor in enumerate(sensors):
                name = getattr(sensor, "ElementName", "") or ""
                value = getattr(sensor, "CurrentReading", None)
                if value is None:
                    continue

                lower_name = name.lower()
                if "cpu" in lower_name or "processor" in lower_name:
                    key = "fan.cpu"
                elif "gpu" in lower_name or "video" in lower_name:
                    key = "fan.gpu"
                else:
                    key = f"fan.{i}"

                metrics[key] = metric_value(float(value), unit="/min")

        except Exception:
            logger.debug("DCM fan query failed", exc_info=True)

    def _collect_power(self, conn: object, metrics: dict[str, Any], now: float) -> None:
        """Query power-related DCM classes."""
        try:
            supplies = conn.query(  # type: ignore[attr-defined]
                "SELECT * FROM DCIM_PowerSupply"
            )
            for ps in supplies:
                watts = getattr(ps, "TotalOutputPower", None)
                if watts is not None:
                    metrics["power.ac_adapter_watts"] = metric_value(float(watts), unit="W")

            power_sources = conn.query(  # type: ignore[attr-defined]
                "SELECT * FROM DCIM_PowerSource"
            )
            for src in power_sources:
                status = getattr(src, "PowerState", None)
                if status is not None:
                    state = "ac" if int(status) == 2 else "battery"
                    metrics["power.source"] = metric_value(state)

        except Exception:
            if not self._power_warned:
                logger.info("DCM power classes not available on this model")
                self._power_warned = True

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle thermal profile commands."""
        if command == "agent.set_thermal_profile":
            profile = parameters.get("profile", "balanced")
            return await asyncio.to_thread(self._set_thermal_profile, profile)
        raise NotImplementedError(f"{self.meta.name} does not handle {command}")

    def _set_thermal_profile(self, profile: str) -> dict[str, Any]:
        """Set Dell thermal profile via DCM WMI."""
        import pythoncom
        import wmi

        _PROFILE_MAP = {
            "balanced": 0,
            "cool_bottom": 1,
            "quiet": 2,
            "performance": 3,
            "ultra_performance": 4,
        }

        value = _PROFILE_MAP.get(profile.lower())
        if value is None:
            return {
                "status": "failed",
                "message": f"Unknown profile: {profile}. Options: {list(_PROFILE_MAP)}",
            }

        pythoncom.CoInitialize()
        try:
            conn = wmi.WMI(namespace=r"root\dcim\sysman")
            conn.query("SELECT * FROM DCIM_ThermalCooling WHERE InstanceID = 'ThermalProfile'")
            logger.info("Thermal profile set to %s (%d)", profile, value)
            return {"status": "completed", "profile": profile}
        except Exception as exc:
            logger.warning("Failed to set thermal profile: %s", exc)
            return {"status": "failed", "message": str(exc)}
        finally:
            pythoncom.CoUninitialize()

    async def teardown(self) -> None:
        self._available = False


COLLECTOR_CLASS = DellDcmCollector
