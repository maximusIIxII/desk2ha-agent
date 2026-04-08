"""Tests for HID battery collector."""

from __future__ import annotations

from desk2ha_agent.collector.generic.hid_battery import HIDBatteryCollector


def test_hid_battery_meta():
    assert HIDBatteryCollector.meta.name == "hid_battery"
    assert HIDBatteryCollector.meta.tier == "generic"
    assert "peripheral" in HIDBatteryCollector.meta.capabilities
