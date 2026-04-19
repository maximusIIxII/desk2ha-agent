"""Tests for Dell Peripheral HID Feature Reports vendor collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from desk2ha_agent.collector.vendor.dell_peripheral import (
    _BACKLIGHT_LEVELS,
    _BACKLIGHT_REVERSE,
    _DPI_PRESETS,
    _HID_USAGE_KEYBOARD,
    _HID_USAGE_MOUSE,
    _HID_USAGE_PAGE_GENERIC_DESKTOP,
    _PERIPHERAL_TYPES,
    _RECEIVER_PIDS,
    DellPeripheralCollector,
    _detect_paired_classes,
)


def test_dell_peripheral_meta():
    assert DellPeripheralCollector.meta.name == "dell_peripheral"
    assert DellPeripheralCollector.meta.tier == "vendor"
    assert "peripheral" in DellPeripheralCollector.meta.capabilities
    assert "control" in DellPeripheralCollector.meta.capabilities


def test_backlight_levels_bidirectional():
    """Backlight levels and reverse map should be consistent."""
    for byte_val, level_str in _BACKLIGHT_LEVELS.items():
        assert _BACKLIGHT_REVERSE[level_str] == byte_val


def test_receiver_pids():
    """Should recognize known Dell Secure Link receiver PIDs."""
    assert 0x2119 in _RECEIVER_PIDS
    assert 0x2141 in _RECEIVER_PIDS
    assert 0xB091 in _RECEIVER_PIDS


def test_peripheral_types():
    """Should map peripheral type bytes to names."""
    assert _PERIPHERAL_TYPES[0x01] == "keyboard"
    assert _PERIPHERAL_TYPES[0x02] == "mouse"
    assert _PERIPHERAL_TYPES[0x03] == "combo"


def test_dpi_presets():
    """DPI presets should have expected values."""
    assert _DPI_PRESETS[0] == 1000
    assert _DPI_PRESETS[1] == 1600
    assert _DPI_PRESETS[2] == 2400
    assert _DPI_PRESETS[3] == 4000


@pytest.mark.asyncio
async def test_probe_no_hidapi():
    """Probe should return False when hidapi is not installed."""
    c = DellPeripheralCollector()
    with patch.dict("sys.modules", {"hid": None}):
        result = await c.probe()
    assert result is False


@pytest.mark.asyncio
async def test_collect_empty_when_no_receivers():
    """Collect should return empty dict when no receivers probed."""
    c = DellPeripheralCollector()
    result = await c.collect()
    assert result == {}


@pytest.mark.asyncio
async def test_execute_command_unknown_raises():
    """Unknown commands should raise NotImplementedError."""
    c = DellPeripheralCollector()
    with pytest.raises(NotImplementedError):
        await c.execute_command("peripheral.unknown", "x", {})


def test_collect_sync_keyboard():
    """_collect_sync should parse a keyboard from receiver report."""
    c = DellPeripheralCollector()
    c._receivers = [
        {
            "vendor_id": 0x413C,
            "product_id": 0x2119,
            "path": b"/fake/receiver",
            "usage_page": 0xFF02,
        }
    ]

    # Build a fake report: byte[3]=0x01 (keyboard), byte[4]=2 (medium backlight), byte[5]=1 (slot)
    fake_report = [0] * 64
    fake_report[3] = 0x01  # keyboard type
    fake_report[4] = 2  # backlight = medium
    fake_report[5] = 1  # active slot

    mock_device = MagicMock()
    mock_device.get_feature_report.return_value = bytes(fake_report)

    mock_hid = MagicMock()
    mock_hid.device.return_value = mock_device

    with patch.dict("sys.modules", {"hid": mock_hid}):
        metrics = c._collect_sync()

    assert metrics["peripheral.dell_kb_0.manufacturer"]["value"] == "Dell"
    assert metrics["peripheral.dell_kb_0.device_type"]["value"] == "keyboard"
    assert metrics["peripheral.dell_kb_0.backlight_level"]["value"] == "medium"
    assert metrics["peripheral.dell_kb_0.active_slot"]["value"] == 1.0


def test_collect_sync_mouse():
    """_collect_sync should parse a mouse from receiver report."""
    c = DellPeripheralCollector()
    c._receivers = [
        {
            "vendor_id": 0x413C,
            "product_id": 0x2141,
            "path": b"/fake/receiver",
            "usage_page": 0xFF83,
        }
    ]

    # byte[3]=0x02 (mouse), byte[4]=1 (DPI preset 1 = 1600)
    fake_report = [0] * 64
    fake_report[3] = 0x02
    fake_report[4] = 1  # DPI preset index → 1600

    mock_device = MagicMock()
    mock_device.get_feature_report.return_value = bytes(fake_report)

    mock_hid = MagicMock()
    mock_hid.device.return_value = mock_device

    with patch.dict("sys.modules", {"hid": mock_hid}):
        metrics = c._collect_sync()

    assert metrics["peripheral.dell_ms_0.dpi"]["value"] == 1600.0
    assert metrics["peripheral.dell_ms_0.device_type"]["value"] == "mouse"


def test_collect_sync_combo_keyboard_and_mouse():
    """_collect_sync should create both kb and ms sub-devices for combo type."""
    c = DellPeripheralCollector()
    c._receivers = [
        {
            "vendor_id": 0x413C,
            "product_id": 0x2119,
            "path": b"/fake/receiver",
            "usage_page": 0xFF02,
        }
    ]

    fake_report = [0] * 64
    fake_report[3] = 0x03  # combo
    fake_report[4] = 3  # backlight = high (keyboard) / DPI preset 3 = 4000 (mouse)
    fake_report[5] = 0  # slot (keyboard)
    fake_report[6] = 2  # mouse active_slot

    mock_device = MagicMock()
    mock_device.get_feature_report.return_value = bytes(fake_report)

    mock_hid = MagicMock()
    mock_hid.device.return_value = mock_device

    with patch.dict("sys.modules", {"hid": mock_hid}):
        metrics = c._collect_sync()

    # Both keyboard and mouse should be present
    assert "peripheral.dell_kb_0.manufacturer" in metrics
    assert "peripheral.dell_ms_0.manufacturer" in metrics


# ---------------------------------------------------------------------------
# Paired-class detection from HID enumeration (FK-15 presence fallback)
# ---------------------------------------------------------------------------


def _make_iface(path: bytes, pid: int, usage_page: int, usage: int) -> dict:
    return {"path": path, "product_id": pid, "usage_page": usage_page, "usage": usage}


def test_detect_paired_classes_keyboard_and_mouse():
    """Secure Link exposes KB and mouse as distinct HID usages."""
    recv_path = b"/fake/recv"
    devs = [
        _make_iface(recv_path, 0x2119, 0xFF02, 0x01),
        _make_iface(b"/fake/kb", 0x2119, _HID_USAGE_PAGE_GENERIC_DESKTOP, _HID_USAGE_KEYBOARD),
        _make_iface(b"/fake/ms", 0x2119, _HID_USAGE_PAGE_GENERIC_DESKTOP, _HID_USAGE_MOUSE),
    ]
    assert _detect_paired_classes(recv_path, devs) == {"keyboard", "mouse"}


def test_detect_paired_classes_only_keyboard():
    recv_path = b"/fake/recv"
    devs = [
        _make_iface(recv_path, 0x2119, 0xFF02, 0x01),
        _make_iface(b"/fake/kb", 0x2119, _HID_USAGE_PAGE_GENERIC_DESKTOP, _HID_USAGE_KEYBOARD),
    ]
    assert _detect_paired_classes(recv_path, devs) == {"keyboard"}


def test_detect_paired_classes_other_pid_ignored():
    """Interfaces from a different receiver PID must not leak in."""
    recv_path = b"/fake/recv"
    devs = [
        _make_iface(recv_path, 0x2119, 0xFF02, 0x01),
        # KB iface belongs to a *different* receiver PID → must not count
        _make_iface(b"/other/kb", 0xB091, _HID_USAGE_PAGE_GENERIC_DESKTOP, _HID_USAGE_KEYBOARD),
    ]
    assert _detect_paired_classes(recv_path, devs) == set()


def test_detect_paired_classes_receiver_unknown_path():
    """If we can't find the receiver itself in the enumeration, bail out."""
    devs = [_make_iface(b"/other/kb", 0x2119, 0x01, _HID_USAGE_KEYBOARD)]
    assert _detect_paired_classes(b"/missing", devs) == set()


def test_collect_sync_kb_mouse_visible_when_feature_report_empty():
    """The key fix: kb/ms sub-peripherals appear even if the Feature Report
    channel returns an empty/short response. Before this change, the /v1/info
    peripherals list only showed `dell_receiver_0` — the HA card had no Dell
    mouse or keyboard entries."""
    c = DellPeripheralCollector()
    recv_path = b"/fake/recv"
    c._receivers = [
        {
            "vendor_id": 0x413C,
            "product_id": 0x2119,
            "path": recv_path,
            "usage_page": 0xFF02,
        }
    ]

    enum_result = [
        _make_iface(recv_path, 0x2119, 0xFF02, 0x01),
        _make_iface(b"/fake/kb", 0x2119, _HID_USAGE_PAGE_GENERIC_DESKTOP, _HID_USAGE_KEYBOARD),
        _make_iface(b"/fake/ms", 0x2119, _HID_USAGE_PAGE_GENERIC_DESKTOP, _HID_USAGE_MOUSE),
    ]

    mock_device = MagicMock()
    # Feature Report returns empty / nothing usable
    mock_device.get_feature_report.return_value = b""

    mock_hid = MagicMock()
    mock_hid.device.return_value = mock_device
    mock_hid.enumerate.return_value = enum_result

    with patch.dict("sys.modules", {"hid": mock_hid}):
        metrics = c._collect_sync()

    # Receiver still present
    assert metrics["peripheral.dell_receiver_0.device_type"]["value"] == "receiver"
    # Keyboard and mouse now visible purely from HID enumeration
    assert metrics["peripheral.dell_kb_0.device_type"]["value"] == "keyboard"
    assert metrics["peripheral.dell_kb_0.manufacturer"]["value"] == "Dell"
    assert metrics["peripheral.dell_ms_0.device_type"]["value"] == "mouse"
    assert metrics["peripheral.dell_ms_0.manufacturer"]["value"] == "Dell"
    # No DPI / backlight expected — Feature Report was empty
    assert "peripheral.dell_kb_0.backlight_level" not in metrics
    assert "peripheral.dell_ms_0.dpi" not in metrics
