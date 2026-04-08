"""HP WMI vendor collector.

Reads thermals, fan speeds, and battery health from HP's WMI namespace
``root\\HP\\InstrumentedBIOS`` and ``root\\WMI`` (HP-specific classes).

Requires an HP system with HP System Event Utility or HP Notifications installed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)


class HpWmiCollector(Collector):
    """Collect thermals, fan, and battery data from HP WMI."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="hp_wmi",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS},
        capabilities={"thermals"},
        description="HP WMI telemetry (thermals, fans, battery health)",
        requires_software="HP System Event Utility",
    )

    def __init__(self) -> None:
        self._available: bool = False

    async def probe(self) -> bool:
        if sys.platform != "win32":
            return False
        return await asyncio.to_thread(self._probe_sync)

    def _probe_sync(self) -> bool:
        try:
            import pythoncom
            import wmi

            pythoncom.CoInitialize()
            try:
                conn = wmi.WMI(namespace=r"root\HP\InstrumentedBIOS")
                # Quick check — try to list BIOS settings
                items = conn.query("SELECT * FROM HP_BIOSSetting")
                logger.info("HP WMI: found %d BIOS settings", len(list(items)))
                return True
            finally:
                pythoncom.CoUninitialize()
        except ImportError:
            return False
        except Exception:
            logger.debug("HP WMI probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        self._available = True
        logger.info("HP WMI collector activated")

    async def collect(self) -> dict[str, Any]:
        if not self._available:
            return {}
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        import pythoncom
        import wmi

        pythoncom.CoInitialize()
        try:
            metrics: dict[str, Any] = {}

            # Thermals via root\WMI (HP thermal zone)
            try:
                wmi_conn = wmi.WMI(namespace=r"root\WMI")
                sensors = wmi_conn.query(
                    "SELECT * FROM MSAcpi_ThermalZoneTemperature"
                )
                for i, sensor in enumerate(sensors):
                    raw = getattr(sensor, "CurrentTemperature", None)
                    if raw is None:
                        continue
                    celsius = round((float(raw) / 10.0) - 273.15, 1)
                    if celsius < 0 or celsius > 150:
                        continue
                    key = "cpu_package" if i == 0 else f"thermal_zone_{i}"
                    metrics[key] = metric_value(celsius, unit="Cel")
            except Exception:
                logger.debug("HP thermal query failed", exc_info=True)

            # Fan speed via HP WMI
            try:
                hp_conn = wmi.WMI(namespace=r"root\HP\InstrumentedBIOS")
                fans = hp_conn.query(
                    "SELECT * FROM HP_BIOSSetting WHERE Name LIKE '%Fan%'"
                )
                for fan in fans:
                    name = getattr(fan, "Name", "")
                    value = getattr(fan, "CurrentValue", None)
                    if value is not None and name:
                        slug = name.lower().replace(" ", "_")[:20]
                        metrics[f"fan.{slug}"] = metric_value(str(value))
            except Exception:
                logger.debug("HP fan query failed", exc_info=True)

            # Thermal profile
            try:
                hp_conn = wmi.WMI(namespace=r"root\HP\InstrumentedBIOS")
                profiles = hp_conn.query(
                    "SELECT * FROM HP_BIOSSetting "
                    "WHERE Name = 'Thermal Profile'"
                )
                for p in profiles:
                    val = getattr(p, "CurrentValue", None)
                    if val:
                        metrics["thermal_profile"] = metric_value(str(val))
            except Exception:
                logger.debug("HP thermal profile query failed", exc_info=True)

            return metrics
        except Exception:
            logger.exception("HP WMI collection failed")
            return {}
        finally:
            pythoncom.CoUninitialize()

    async def teardown(self) -> None:
        self._available = False


COLLECTOR_CLASS = HpWmiCollector
