"""Tests for Logitech HID++ collector — new features (SmartShift, ChangeHost, etc.)."""

from __future__ import annotations

from unittest.mock import MagicMock

from desk2ha_agent.collector.vendor.logitech_hidpp import (
    _FEAT_CHANGE_HOST,
    _FEAT_HIRES_WHEEL,
    _FEAT_SMART_SHIFT,
    _FEAT_THUMB_WHEEL,
    _FEAT_WIRELESS_STATUS,
    _KNOWN_FEATURES,
    _REPORT_LONG,
    _build_hidpp_long,
    _HidPPDevice,
)


def _mock_hid_device(responses: list[list[int]]) -> MagicMock:
    """Create a mock HID device that returns canned responses."""
    h = MagicMock()
    h.write = MagicMock()
    call_count = 0

    def _read(size: int) -> list[int] | None:
        nonlocal call_count
        if call_count < len(responses):
            resp = responses[call_count]
            call_count += 1
            return resp
        return None

    h.read = _read
    return h


def test_known_features_complete() -> None:
    """All new feature IDs should be in _KNOWN_FEATURES."""
    assert _FEAT_SMART_SHIFT in _KNOWN_FEATURES
    assert _FEAT_CHANGE_HOST in _KNOWN_FEATURES
    assert _FEAT_HIRES_WHEEL in _KNOWN_FEATURES
    assert _FEAT_THUMB_WHEEL in _KNOWN_FEATURES
    assert _FEAT_WIRELESS_STATUS in _KNOWN_FEATURES


def test_read_smart_shift() -> None:
    """SmartShift read should parse mode and threshold."""
    dev = _HidPPDevice(b"/test", 1, "MX Master 3")
    dev.features["smart_shift"] = 0x05  # fake feature index

    # Response: report_long, device_idx=1, feat_idx=5, func<<4|sw, mode=2(freespin), threshold=15
    response = [0] * 20
    response[0] = _REPORT_LONG
    response[1] = 1
    response[2] = 0x05
    response[4] = 2  # freespin
    response[5] = 15  # threshold

    h = _mock_hid_device([response])
    result = dev.read_smart_shift(h)
    assert result is not None
    assert result["mode"] == "freespin"
    assert result["threshold"] == 15


def test_read_smart_shift_ratchet() -> None:
    """SmartShift ratchet mode."""
    dev = _HidPPDevice(b"/test", 1, "MX Master 3")
    dev.features["smart_shift"] = 0x05

    response = [0] * 20
    response[0] = _REPORT_LONG
    response[2] = 0x05
    response[4] = 1  # ratchet
    response[5] = 30

    h = _mock_hid_device([response])
    result = dev.read_smart_shift(h)
    assert result is not None
    assert result["mode"] == "ratchet"
    assert result["threshold"] == 30


def test_read_change_host() -> None:
    """Change Host read should return host count and current."""
    dev = _HidPPDevice(b"/test", 1, "MX Keys")
    dev.features["change_host"] = 0x06

    response = [0] * 20
    response[0] = _REPORT_LONG
    response[2] = 0x06
    response[4] = 3  # num_hosts
    response[5] = 1  # current_host

    h = _mock_hid_device([response])
    result = dev.read_change_host(h)
    assert result is not None
    assert result["num_hosts"] == 3
    assert result["current_host"] == 1


def test_read_hires_wheel() -> None:
    """Hi-Res Wheel read should parse hires and invert flags."""
    dev = _HidPPDevice(b"/test", 1, "MX Master 3")
    dev.features["hires_wheel"] = 0x07

    response = [0] * 20
    response[0] = _REPORT_LONG
    response[2] = 0x07
    response[4] = 0x03  # hires=True, invert=True

    h = _mock_hid_device([response])
    result = dev.read_hires_wheel(h)
    assert result is not None
    assert result["hires"] is True
    assert result["invert"] is True


def test_read_wireless_status() -> None:
    """Wireless status should return link quality."""
    dev = _HidPPDevice(b"/test", 1, "MX Anywhere")
    dev.features["wireless_status"] = 0x08

    response = [0] * 20
    response[0] = _REPORT_LONG
    response[2] = 0x08
    response[5] = 80  # link quality

    h = _mock_hid_device([response])
    result = dev.read_wireless_status(h)
    assert result is not None
    assert result["link_quality"] == 80


def test_read_feature_not_available() -> None:
    """Reading a feature that isn't discovered should return None."""
    dev = _HidPPDevice(b"/test", 1, "Test Device")
    # No features discovered
    h = _mock_hid_device([])
    assert dev.read_smart_shift(h) is None
    assert dev.read_change_host(h) is None
    assert dev.read_wireless_status(h) is None


def test_discover_features() -> None:
    """discover_features should populate the features dict."""
    dev = _HidPPDevice(b"/test", 1, "Test Device")

    # Mock IRoot responses for each feature query
    # When the device queries IRoot for a feature, it gets back the index
    responses: list[list[int]] = []
    for i, _feat_id in enumerate(_KNOWN_FEATURES):
        resp = [0] * 20
        resp[0] = _REPORT_LONG
        resp[1] = 1
        resp[2] = 0x00  # IRoot response
        resp[4] = i + 1  # non-zero = supported
        responses.append(resp)

    h = _mock_hid_device(responses)
    dev.discover_features(h)
    assert len(dev.features) == len(_KNOWN_FEATURES)


def test_build_hidpp_long_message() -> None:
    """Verify HID++ long message construction."""
    msg = _build_hidpp_long(1, 5, 0, 100)
    assert len(msg) == 20
    assert msg[0] == _REPORT_LONG
    assert msg[1] == 1  # device_idx
    assert msg[2] == 5  # feat_idx
    assert msg[3] == 0x01  # func_id=0 << 4 | sw_id=1
    assert msg[4] == 100
