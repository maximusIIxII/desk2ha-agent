"""Bluetooth peripheral collector.

Enumerates paired Bluetooth LE and Classic devices, reads battery levels
via GATT Battery Service (0x180F), and collects device information.

On Windows: uses WinRT APIs directly for paired device enumeration.
On Linux/macOS: uses bleak for BLE scanning/connection.
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

# GATT UUIDs
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_CHAR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_CHAR_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_CHAR_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

# Device type classification based on name patterns
_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("keyboard", "keyboard"),
    ("kb", "keyboard"),
    ("mouse", "mouse"),
    ("ms", "mouse"),
    ("headset", "headset"),
    ("earbuds", "earbuds"),
    ("earbud", "earbuds"),
    ("headphone", "headphones"),
    ("speaker", "speaker"),
    ("speakerphone", "speakerphone"),
    ("speak", "speakerphone"),
    ("gamepad", "gamepad"),
    ("controller", "gamepad"),
    ("pen", "stylus"),
    ("stylus", "stylus"),
]

# Name-pattern → manufacturer mapping for BT devices without GATT manufacturer info
_MANUFACTURER_PATTERNS: list[tuple[str, str]] = [
    ("dell", "Dell"),
    ("km7321w", "Dell"),
    ("km5221w", "Dell"),
    ("ms5320w", "Dell"),
    ("ms3320w", "Dell"),
    ("ms5120w", "Dell"),
    ("kb900", "Dell"),
    ("ms900", "Dell"),
    ("kb700", "Dell"),
    ("eb525", "Dell"),
    ("wl5022", "Dell"),
    ("wl7024", "Dell"),
    ("wl3024", "Dell"),
    ("jabra", "Jabra"),
    ("speak2", "Jabra"),
    ("speak 75", "Jabra"),
    ("evolve2", "Jabra"),
    ("engage", "Jabra"),
    ("elite", "Jabra"),
    ("logitech", "Logitech"),
    ("mx master", "Logitech"),
    ("mx keys", "Logitech"),
    ("mx anywhere", "Logitech"),
    ("bose", "Bose"),
    ("sony wh-", "Sony"),
    ("sony wf-", "Sony"),
    ("airpods", "Apple"),
    ("surface", "Microsoft"),
    ("arctis", "SteelSeries"),
    ("razer", "Razer"),
    ("corsair", "Corsair"),
    ("plantronics", "Plantronics"),
    ("poly", "Poly"),
    ("sennheiser", "Sennheiser"),
    ("jbl", "JBL"),
    ("samsung", "Samsung"),
    ("galaxy buds", "Samsung"),
]


def _infer_manufacturer(name: str) -> str:
    """Infer manufacturer from device name patterns."""
    lower = name.lower()
    for pattern, manufacturer in _MANUFACTURER_PATTERNS:
        if pattern in lower:
            return manufacturer
    return ""


def _classify_device(name: str) -> str:
    """Classify a Bluetooth device by name into a device type."""
    lower = name.lower()
    for pattern, device_type in _TYPE_PATTERNS:
        if pattern in lower:
            return device_type
    return "peripheral"


def _make_device_key(address: str) -> str:
    """Create a stable device key from a Bluetooth address."""
    # Remove colons/hyphens, uppercase
    clean = address.replace(":", "").replace("-", "").upper()
    return f"bt_{clean}"


class BluetoothPeripheralCollector(Collector):
    """Enumerate paired Bluetooth devices and read battery levels."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="bluetooth_peripheral",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "battery"},
        description="Bluetooth peripheral battery and device info (BLE + Classic)",
        optional_dependencies=["bleak"],
    )

    def __init__(self) -> None:
        self._available: bool = False

    async def probe(self) -> bool:
        if sys.platform == "win32":
            return self._probe_windows()
        return self._probe_bleak()

    def _probe_windows(self) -> bool:
        try:
            from winrt.windows.devices.bluetooth import (  # noqa: F401
                BluetoothLEDevice,
            )
            from winrt.windows.devices.enumeration import (  # noqa: F401
                DeviceInformation,
            )

            self._available = True
            return True
        except ImportError:
            return False

    def _probe_bleak(self) -> bool:
        try:
            from bleak import BleakClient, BleakScanner  # noqa: F401

            self._available = True
            return True
        except ImportError:
            return False

    async def setup(self) -> None:
        logger.info("Bluetooth peripheral collector ready (platform=%s)", sys.platform)

    async def collect(self) -> dict[str, Any]:
        if sys.platform == "win32":
            # WinRT async APIs need their own event loop in a separate thread
            return await asyncio.to_thread(self._collect_windows_sync)
        return await self._collect_bleak()

    def _collect_windows_sync(self) -> dict[str, Any]:
        """Run Windows collection in a thread with its own event loop."""
        return asyncio.run(self._collect_windows())

    # ── Windows: WinRT Bluetooth API ──────────────────────────────

    async def _collect_windows(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        try:
            ble_metrics = await self._collect_windows_ble()
            metrics.update(ble_metrics)
        except Exception:
            logger.debug("BLE enumeration failed", exc_info=True)

        try:
            classic_metrics = await self._collect_windows_classic(
                set(metrics.keys()),
            )
            metrics.update(classic_metrics)
        except Exception:
            logger.debug("BT Classic enumeration failed", exc_info=True)

        return metrics

    async def _collect_windows_ble(self) -> dict[str, Any]:
        import uuid as _uuid

        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattCommunicationStatus,
        )
        from winrt.windows.devices.enumeration import DeviceInformation
        from winrt.windows.storage.streams import DataReader

        metrics: dict[str, Any] = {}

        selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
        devices = await DeviceInformation.find_all_async_aqs_filter(selector)

        for i in range(devices.size):
            dev_info = devices.get_at(i)
            name = dev_info.name.strip() if dev_info.name else ""
            if not name:
                continue

            # Extract BT address from device ID
            # Format: BluetoothLE#BluetoothLE<adapter>-<device_addr>
            dev_id = dev_info.id
            address = self._extract_address(dev_id)
            device_key = _make_device_key(address) if address else f"bt_ble_{i}"
            prefix = f"peripheral.{device_key}"

            try:
                ble_device = await BluetoothLEDevice.from_id_async(dev_id)
                if not ble_device:
                    continue

                # Check if device has GATT services at all
                all_svcs = await ble_device.get_gatt_services_async()
                if (
                    all_svcs.status != GattCommunicationStatus.SUCCESS
                    or all_svcs.services.size == 0
                ):
                    # No GATT services — skip, will appear via BT Classic
                    ble_device.close()
                    continue

                # Device has GATT services — report it
                metrics[f"{prefix}.model"] = metric_value(name)
                metrics[f"{prefix}.type"] = metric_value(_classify_device(name))
                metrics[f"{prefix}.transport"] = metric_value("ble")
                metrics[f"{prefix}.connected"] = metric_value(True)

                # Infer manufacturer from name pattern (may be overridden by GATT below)
                inferred_mfg = _infer_manufacturer(name)
                if inferred_mfg:
                    metrics[f"{prefix}.manufacturer"] = metric_value(inferred_mfg)

                # Read battery level
                result = await ble_device.get_gatt_services_for_uuid_async(
                    _uuid.UUID(BATTERY_SERVICE_UUID)
                )
                if result.status == GattCommunicationStatus.SUCCESS and result.services.size > 0:
                    svc = result.services.get_at(0)
                    chars = await svc.get_characteristics_for_uuid_async(
                        _uuid.UUID(BATTERY_LEVEL_CHAR_UUID)
                    )
                    if (
                        chars.status == GattCommunicationStatus.SUCCESS
                        and chars.characteristics.size > 0
                    ):
                        val = await chars.characteristics.get_at(0).read_value_async()
                        if val.status == GattCommunicationStatus.SUCCESS and val.value:
                            reader = DataReader.from_buffer(val.value)
                            battery = reader.read_byte()
                            metrics[f"{prefix}.battery_level"] = metric_value(
                                float(battery), unit="%"
                            )

                # Read device info (manufacturer, firmware)
                result = await ble_device.get_gatt_services_for_uuid_async(
                    _uuid.UUID(DEVICE_INFO_SERVICE_UUID)
                )
                if result.status == GattCommunicationStatus.SUCCESS and result.services.size > 0:
                    svc = result.services.get_at(0)
                    for char_uuid, metric_name in [
                        (MANUFACTURER_NAME_CHAR_UUID, "manufacturer"),
                        (FIRMWARE_REVISION_CHAR_UUID, "firmware"),
                    ]:
                        try:
                            chars = await svc.get_characteristics_for_uuid_async(
                                _uuid.UUID(char_uuid)
                            )
                            if (
                                chars.status == GattCommunicationStatus.SUCCESS
                                and chars.characteristics.size > 0
                            ):
                                val = await chars.characteristics.get_at(0).read_value_async()
                                if val.status == GattCommunicationStatus.SUCCESS and val.value:
                                    reader = DataReader.from_buffer(val.value)
                                    length = val.value.length
                                    raw = bytes([reader.read_byte() for _ in range(length)])
                                    text = raw.decode("utf-8", errors="ignore").strip()
                                    if text:
                                        metrics[f"{prefix}.{metric_name}"] = metric_value(text)
                        except Exception:
                            pass

                ble_device.close()

            except Exception:
                logger.debug("Failed to read GATT from %s", name, exc_info=True)

        return metrics

    async def _collect_windows_classic(
        self,
        existing_keys: set[str],
    ) -> dict[str, Any]:
        """Enumerate paired BT Classic devices not already found via BLE."""
        from winrt.windows.devices.bluetooth import (
            BluetoothConnectionStatus,
            BluetoothDevice,
        )
        from winrt.windows.devices.enumeration import DeviceInformation

        metrics: dict[str, Any] = {}

        selector = BluetoothDevice.get_device_selector_from_pairing_state(True)
        devices = await DeviceInformation.find_all_async_aqs_filter(selector)

        for i in range(devices.size):
            dev_info = devices.get_at(i)
            name = dev_info.name.strip() if dev_info.name else ""
            if not name:
                continue

            # Extract address from ID
            # Format: Bluetooth#Bluetooth<adapter>-<device_addr>
            address = self._extract_address(dev_info.id)
            device_key = _make_device_key(address) if address else f"bt_classic_{i}"
            prefix = f"peripheral.{device_key}"

            # Skip if we already have this device from BLE enumeration
            if any(k.startswith(prefix) for k in existing_keys):
                continue

            # Check actual connection status via WinRT
            connected = False
            try:
                bt_device = await BluetoothDevice.from_id_async(dev_info.id)
                if bt_device:
                    connected = bt_device.connection_status == BluetoothConnectionStatus.CONNECTED
                    bt_device.close()
            except Exception:
                logger.debug("Could not check connection for %s", name)

            # Skip disconnected (paired-only) devices — they clutter HA
            if not connected:
                continue

            metrics[f"{prefix}.model"] = metric_value(name)
            metrics[f"{prefix}.type"] = metric_value(_classify_device(name))
            metrics[f"{prefix}.transport"] = metric_value("classic")
            metrics[f"{prefix}.connected"] = metric_value(connected)

            # Infer manufacturer from name pattern
            inferred_mfg = _infer_manufacturer(name)
            if inferred_mfg:
                metrics[f"{prefix}.manufacturer"] = metric_value(inferred_mfg)

        return metrics

    @staticmethod
    def _extract_address(device_id: str) -> str | None:
        """Extract BT address from WinRT device ID.

        BLE:     BluetoothLE#BluetoothLE<adapter>-<device_addr>
        Classic: Bluetooth#Bluetooth<adapter>-<device_addr>
        Device address is always the last 17 chars (XX:XX:XX:XX:XX:XX).
        """
        try:
            if len(device_id) >= 17:
                addr = device_id[-17:]
                # Validate MAC format
                if len(addr.split(":")) == 6:
                    return addr.upper()
        except Exception:
            pass
        return None

    # ── Linux/macOS: bleak ────────────────────────────────────────

    async def _collect_bleak(self) -> dict[str, Any]:
        from bleak import BleakClient, BleakScanner

        metrics: dict[str, Any] = {}

        # Scan for advertising BLE devices
        devices = await BleakScanner.discover(timeout=5.0, return_adv=True)

        for addr, (device, adv_data) in devices.items():
            name = device.name or ""
            if not name:
                continue

            device_key = _make_device_key(addr)
            prefix = f"peripheral.{device_key}"

            metrics[f"{prefix}.model"] = metric_value(name)
            metrics[f"{prefix}.type"] = metric_value(_classify_device(name))
            metrics[f"{prefix}.transport"] = metric_value("ble")
            metrics[f"{prefix}.connected"] = metric_value(True)

            # Infer manufacturer from name pattern
            inferred_mfg = _infer_manufacturer(name)
            if inferred_mfg:
                metrics[f"{prefix}.manufacturer"] = metric_value(inferred_mfg)

            # Check if device advertises Battery Service
            service_uuids = [str(u).lower() for u in (adv_data.service_uuids or [])]
            has_battery = BATTERY_SERVICE_UUID in service_uuids

            if has_battery:
                try:
                    async with BleakClient(addr, timeout=10.0) as client:
                        battery_data = await client.read_gatt_char(BATTERY_LEVEL_CHAR_UUID)
                        if battery_data:
                            metrics[f"{prefix}.battery_level"] = metric_value(
                                float(battery_data[0]), unit="%"
                            )

                        # Device info
                        for char_uuid, metric_name in [
                            (MANUFACTURER_NAME_CHAR_UUID, "manufacturer"),
                            (FIRMWARE_REVISION_CHAR_UUID, "firmware"),
                        ]:
                            try:
                                data = await client.read_gatt_char(char_uuid)
                                if data:
                                    text = data.decode("utf-8", errors="ignore").strip()
                                    if text:
                                        metrics[f"{prefix}.{metric_name}"] = metric_value(text)
                            except Exception:
                                pass

                except Exception:
                    logger.debug("Failed to read BLE battery from %s", addr, exc_info=True)

        return metrics

    async def teardown(self) -> None:
        self._available = False


COLLECTOR_CLASS = BluetoothPeripheralCollector
