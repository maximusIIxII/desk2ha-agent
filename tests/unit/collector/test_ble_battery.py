"""Tests for BLE battery collector."""

from __future__ import annotations

from unittest.mock import patch

from desk2ha_agent.collector.generic.ble_battery import (
    BLEBatteryCollector,
    _is_macos_uuid,
    _make_device_key,
    _make_global_id,
)


def test_ble_battery_meta():
    assert BLEBatteryCollector.meta.name == "ble_battery"
    assert BLEBatteryCollector.meta.tier == "generic"
    assert "peripheral" in BLEBatteryCollector.meta.capabilities
    assert "bleak" in BLEBatteryCollector.meta.optional_dependencies


# ---------- macOS CoreBluetooth helpers (FK-21) ----------


def test_is_macos_uuid():
    """macOS UUIDs should be detected correctly."""
    assert _is_macos_uuid("12345678-1234-1234-1234-123456789ABC")
    assert not _is_macos_uuid("AA:BB:CC:DD:EE:FF")
    assert not _is_macos_uuid("AABBCCDDEEFF")


def test_make_device_key_mac():
    """MAC address should produce BLE-<MAC> key."""
    assert _make_device_key("AA:BB:CC:DD:EE:FF") == "BLE-AABBCCDDEEFF"


def test_make_device_key_uuid():
    """macOS UUID should produce BLE-<last12> key."""
    key = _make_device_key("12345678-1234-1234-1234-56789ABCDEF0")
    assert key == "BLE-56789ABCDEF0"


def test_make_global_id_linux():
    """Linux/Windows should use bt:<MAC> format."""
    with patch("desk2ha_agent.collector.generic.ble_battery.sys") as mock_sys:
        mock_sys.platform = "linux"
        gid = _make_global_id("AA:BB:CC:DD:EE:FF", "Test Device")
    assert gid == "bt:AABBCCDDEEFF"


def test_make_global_id_macos():
    """macOS should use bt-uuid:<UUID> format."""
    with patch("desk2ha_agent.collector.generic.ble_battery.sys") as mock_sys:
        mock_sys.platform = "darwin"
        gid = _make_global_id("12345678-1234-1234-1234-56789abcdef0", "Test Device")
    assert gid == "bt-uuid:12345678-1234-1234-1234-56789ABCDEF0"
