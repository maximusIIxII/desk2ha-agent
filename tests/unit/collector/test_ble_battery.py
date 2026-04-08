"""Tests for BLE battery collector."""

from __future__ import annotations

from desk2ha_agent.collector.generic.ble_battery import BLEBatteryCollector


def test_ble_battery_meta():
    assert BLEBatteryCollector.meta.name == "ble_battery"
    assert BLEBatteryCollector.meta.tier == "generic"
    assert "peripheral" in BLEBatteryCollector.meta.capabilities
    assert "bleak" in BLEBatteryCollector.meta.optional_dependencies
