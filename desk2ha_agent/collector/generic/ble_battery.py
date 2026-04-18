"""BLE GATT Battery Service collector.

macOS note: bleak returns CoreBluetooth UUIDs instead of MAC addresses.
On macOS, global_id uses "bt-uuid:<UUID>" format and devices are matched
by name + manufacturer for cross-host tracking.
"""

from __future__ import annotations

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
        capabilities={"peripheral", "control"},
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
        # Always report scanning state so HA can show the switch
        metrics: dict[str, Any] = {
            "system.ble_scanning": metric_value(self._enabled),
        }
        if not self._enabled:
            return metrics

        try:
            from bleak import BleakClient, BleakScanner

            # Scan for BLE devices advertising Battery Service
            devices = await BleakScanner.discover(
                timeout=self._scan_duration,
                service_uuids=[BATTERY_SERVICE_UUID],
            )

            for device in devices:
                device_key = _make_device_key(device.address)
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

                            # Multi-host tracking
                            global_id = _make_global_id(device.address, name)
                            metrics[f"{prefix}.global_id"] = metric_value(global_id)
                            if self.host_device_key:
                                metrics[f"{prefix}.connected_host"] = metric_value(
                                    self.host_device_key
                                )

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

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if command == "ble.set_scanning":
            enabled = bool(parameters.get("enabled", True))
            self._enabled = enabled
            logger.info("BLE scanning %s", "enabled" if enabled else "disabled")
            return {"status": "completed", "scanning": enabled}
        raise NotImplementedError

    async def teardown(self) -> None:
        self._known_devices.clear()


def _is_macos_uuid(address: str) -> bool:
    """Check if address is a macOS CoreBluetooth UUID (not a MAC)."""
    # macOS UUIDs are 36 chars like "12345678-1234-1234-1234-123456789ABC"
    # MACs are like "AA:BB:CC:DD:EE:FF" or "AA-BB-CC-DD-EE-FF"
    return len(address) == 36 and address.count("-") == 4


def _make_device_key(address: str) -> str:
    """Create a stable device key from BLE address or UUID."""
    if _is_macos_uuid(address):
        # Use last 12 chars of UUID for shorter key
        return f"BLE-{address.replace('-', '')[-12:].upper()}"
    return f"BLE-{address.replace(':', '').replace('-', '').upper()}"


def _make_global_id(address: str, name: str) -> str:
    """Create a global_id for multi-host tracking.

    On Linux/Windows: ``bt:<MAC>`` (globally unique)
    On macOS: ``bt-uuid:<UUID>`` (device-local, but stable per Mac)
    """
    if sys.platform == "darwin" and _is_macos_uuid(address):
        return f"bt-uuid:{address.upper()}"
    clean = address.replace(":", "").replace("-", "").upper()
    return f"bt:{clean}"


COLLECTOR_CLASS = BLEBatteryCollector
