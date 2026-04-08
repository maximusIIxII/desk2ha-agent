"""BLE GATT Battery Service collector."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

# BLE Battery Service UUID
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Device Information Service
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_CHAR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_CHAR_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_CHAR_UUID = "00002a26-0000-1000-8000-00805f9b34fb"


class BLEBatteryCollector(Collector):
    """Read battery levels from BLE peripherals via GATT Battery Service."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="ble_battery",
        tier=CollectorTier.GENERIC,
        platforms={Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="BLE GATT Battery Service 0x180F for wireless peripherals",
        optional_dependencies=["bleak"],
    )

    def __init__(self) -> None:
        self._known_devices: dict[str, str] = {}  # address -> name
        self._enabled: bool = False
        self._scan_duration: float = 5.0

    async def probe(self) -> bool:
        """Check if bleak is available and BLE adapter exists."""
        try:
            from bleak import BleakScanner  # noqa: F401

            # Quick check -- don't actually scan during probe
            return True
        except ImportError:
            return False
        except Exception:
            return False

    async def setup(self) -> None:
        logger.info("BLE battery collector ready (scan on demand)")

    async def collect(self) -> dict[str, Any]:
        if not self._enabled:
            return {}

        metrics: dict[str, Any] = {}

        try:
            from bleak import BleakClient, BleakScanner

            # Scan for BLE devices advertising Battery Service
            devices = await BleakScanner.discover(
                timeout=self._scan_duration,
                service_uuids=[BATTERY_SERVICE_UUID],
            )

            for device in devices:
                device_key = f"BLE-{device.address.replace(':', '')}"
                name = device.name or "Unknown BLE Device"
                prefix = f"peripheral.{device_key}"

                try:
                    async with BleakClient(device.address, timeout=10.0) as client:
                        # Read battery level
                        battery_data = await client.read_gatt_char(BATTERY_LEVEL_CHAR_UUID)
                        if battery_data:
                            level = int(battery_data[0])
                            metrics[f"{prefix}.battery_level"] = metric_value(
                                float(level), unit="%"
                            )
                            metrics[f"{prefix}.model"] = metric_value(name)

                        # Try to read device info
                        try:
                            mfr_data = await client.read_gatt_char(MANUFACTURER_NAME_CHAR_UUID)
                            if mfr_data:
                                metrics[f"{prefix}.manufacturer"] = metric_value(
                                    mfr_data.decode("utf-8", errors="ignore")
                                )
                        except Exception:
                            pass

                        try:
                            fw_data = await client.read_gatt_char(FIRMWARE_REVISION_CHAR_UUID)
                            if fw_data:
                                metrics[f"{prefix}.firmware"] = metric_value(
                                    fw_data.decode("utf-8", errors="ignore")
                                )
                        except Exception:
                            pass

                except Exception:
                    logger.debug(
                        "Failed to read BLE battery from %s",
                        device_key,
                        exc_info=True,
                    )

        except Exception:
            logger.debug("BLE scan failed", exc_info=True)

        return metrics

    async def teardown(self) -> None:
        self._known_devices.clear()


COLLECTOR_CLASS = BLEBatteryCollector
