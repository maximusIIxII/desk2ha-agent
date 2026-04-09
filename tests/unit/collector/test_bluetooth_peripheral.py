"""Tests for Bluetooth peripheral collector."""

from __future__ import annotations

import pytest

from desk2ha_agent.collector.generic.bluetooth_peripheral import (
    BluetoothPeripheralCollector,
    _classify_device,
    _make_device_key,
)


def test_meta():
    assert BluetoothPeripheralCollector.meta.name == "bluetooth_peripheral"
    assert BluetoothPeripheralCollector.meta.tier == "generic"
    assert "peripheral" in BluetoothPeripheralCollector.meta.capabilities
    assert "battery" in BluetoothPeripheralCollector.meta.capabilities
    assert "bleak" in BluetoothPeripheralCollector.meta.optional_dependencies


class TestClassifyDevice:
    def test_keyboard(self):
        assert _classify_device("Dell Keyboard KB900") == "keyboard"

    def test_kb_short(self):
        assert _classify_device("Logitech KB780") == "keyboard"

    def test_mouse(self):
        assert _classify_device("Dell Mouse MS900") == "mouse"

    def test_ms_short(self):
        assert _classify_device("Microsoft MS650") == "mouse"

    def test_headset(self):
        assert _classify_device("Dell Headset WL5022") == "headset"

    def test_earbuds(self):
        assert _classify_device("Dell EB525 Earbuds") == "earbuds"

    def test_headphones(self):
        assert _classify_device("Sony WH-1000XM5 Headphone") == "headphones"

    def test_speaker(self):
        assert _classify_device("JBL Speaker Flip 6") == "speaker"

    def test_gamepad(self):
        assert _classify_device("Xbox Wireless Controller") == "gamepad"

    def test_stylus(self):
        assert _classify_device("Dell Active Pen") == "stylus"

    def test_unknown(self):
        assert _classify_device("Some Random Device") == "peripheral"

    def test_case_insensitive(self):
        assert _classify_device("DELL KEYBOARD KB900") == "keyboard"
        assert _classify_device("dell mouse ms900") == "mouse"


class TestMakeDeviceKey:
    def test_colon_format(self):
        assert _make_device_key("CF:B5:EB:B8:5D:D0") == "bt_CFB5EBB85DD0"

    def test_hyphen_format(self):
        assert _make_device_key("CF-B5-EB-B8-5D-D0") == "bt_CFB5EBB85DD0"

    def test_lowercase(self):
        assert _make_device_key("cf:b5:eb:b8:5d:d0") == "bt_CFB5EBB85DD0"


class TestExtractAddress:
    def test_ble_address(self):
        dev_id = "BluetoothLE#BluetoothLE2c:0d:a7:d5:d7:ba-cf:b5:eb:b8:5d:d0"
        addr = BluetoothPeripheralCollector._extract_address(dev_id)
        assert addr == "CF:B5:EB:B8:5D:D0"

    def test_classic_address(self):
        dev_id = "Bluetooth#Bluetooth2c:0d:a7:d5:d7:ba-38:5c:76:15:00:ea"
        addr = BluetoothPeripheralCollector._extract_address(dev_id)
        assert addr == "38:5C:76:15:00:EA"

    def test_short_id_returns_none(self):
        assert BluetoothPeripheralCollector._extract_address("short") is None

    def test_invalid_format_returns_none(self):
        assert BluetoothPeripheralCollector._extract_address("x" * 20) is None


class TestProbe:
    @pytest.mark.asyncio
    async def test_probe_no_bleak_no_winrt(self, monkeypatch):
        """Probe returns False when no BLE library is available."""
        monkeypatch.setattr(
            "desk2ha_agent.collector.generic.bluetooth_peripheral.sys",
            type("FakeSys", (), {"platform": "linux"})(),
        )
        c = BluetoothPeripheralCollector()
        # Monkey-patch _probe_bleak to simulate missing bleak
        c._probe_bleak = lambda: False
        result = await c.probe()
        assert result is False
