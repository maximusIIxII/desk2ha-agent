"""Tests for USB device enumeration collector."""

from __future__ import annotations

from desk2ha_agent.collector.generic.usb_devices import (
    _KNOWN_DEVICES,
    _SKIP_VID_PIDS,
    _SKIP_VIDS,
    USBDeviceCollector,
    _is_generic_name,
)


def test_usb_devices_meta():
    assert USBDeviceCollector.meta.name == "usb_devices"
    assert USBDeviceCollector.meta.tier == "generic"
    assert "peripheral" in USBDeviceCollector.meta.capabilities
    assert "inventory" in USBDeviceCollector.meta.capabilities


def test_known_devices_mapping():
    # Jabra Speak2 75
    model, mfg = _KNOWN_DEVICES["0B0E:24F1"]
    assert model == "Speak2 75"
    assert mfg == "Jabra"

    # Dell webcam
    model, mfg = _KNOWN_DEVICES["413C:C015"]
    assert model == "Webcam WB7022"
    assert mfg == "Dell"


def test_skip_vids():
    assert "8087" in _SKIP_VIDS  # Intel internal
    assert "27C6" in _SKIP_VIDS  # Goodix fingerprint


def test_skip_vid_pids():
    assert "046D:C900" in _SKIP_VID_PIDS  # Litra Glow
    assert "046D:C901" in _SKIP_VID_PIDS  # Litra Beam


def test_is_generic_name():
    assert _is_generic_name("USB-Eingabegerät") is True
    assert _is_generic_name("USB Composite Device") is True
    assert _is_generic_name("Jabra Speak2 75") is False
    assert _is_generic_name("usb-verbundgerät") is True
