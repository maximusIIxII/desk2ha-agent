"""Tests for USB device enumeration collector."""

from __future__ import annotations

from desk2ha_agent.collector.generic.usb_devices import (
    _KNOWN_DEVICES,
    _SKIP_VID_PIDS,
    _SKIP_VIDS,
    USBDeviceCollector,
    _extract_serial_from_instance_id,
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


def test_extract_serial_from_instance_id():
    # Real serial number (alphanumeric, no & separator)
    assert _extract_serial_from_instance_id("USB\\VID_0B0E&PID_24F1\\ABC1234567") == "ABC1234567"

    # Port-path index (contains & separator) — not a serial
    assert _extract_serial_from_instance_id("USB\\VID_046D&PID_C548\\5&12345678&0&1") == ""

    # Short numeric index — not a serial (< 4 chars)
    assert _extract_serial_from_instance_id("USB\\VID_046D&PID_C548\\1") == ""

    # Real webcam serial
    assert _extract_serial_from_instance_id("USB\\VID_413C&PID_C015\\CNXYZ12345") == "CNXYZ12345"

    # Empty / malformed
    assert _extract_serial_from_instance_id("") == ""
    assert _extract_serial_from_instance_id("USB\\VID_046D") == ""


def test_host_device_key_attribute():
    """Collector base class should have host_device_key attribute."""
    collector = USBDeviceCollector()
    assert collector.host_device_key is None
    collector.host_device_key = "ST-TEST123"
    assert collector.host_device_key == "ST-TEST123"
