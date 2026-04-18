"""Tests for Dell Webcam Extension Units vendor collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from desk2ha_agent.collector.vendor.dell_webcam import (
    _DELL_WEBCAM_PIDS,
    _FOV_MAP,
    _FOV_REVERSE,
    _REPORT_MAP,
    DellWebcamCollector,
)


def test_dell_webcam_meta():
    assert DellWebcamCollector.meta.name == "dell_webcam"
    assert DellWebcamCollector.meta.tier == "vendor"
    assert "peripheral" in DellWebcamCollector.meta.capabilities
    assert "control" in DellWebcamCollector.meta.capabilities


def test_fov_map_bidirectional():
    """FOV map and reverse should be consistent."""
    for byte_val, fov_str in _FOV_MAP.items():
        assert _FOV_REVERSE[fov_str] == byte_val


def test_report_map_contains_expected_fields():
    """WB7022 report map should include all expected feature offsets."""
    wb7022 = _REPORT_MAP.get("wb7022", {})
    assert "hdr" in wb7022
    assert "auto_framing" in wb7022
    assert "fov" in wb7022
    assert "noise_reduction" in wb7022
    assert "digital_zoom" in wb7022


def test_known_webcam_pids():
    """Should recognize Dell WB7022 variants."""
    models = set(_DELL_WEBCAM_PIDS.values())
    assert any("WB7022" in m for m in models)
    assert len(models) >= 1


@pytest.mark.asyncio
async def test_probe_no_hidapi():
    """Probe should return False when hidapi is not installed."""
    c = DellWebcamCollector()
    with patch.dict("sys.modules", {"hid": None}):
        result = await c.probe()
    assert result is False


@pytest.mark.asyncio
async def test_probe_no_devices():
    """Probe should return False when no Dell webcams found."""
    mock_hid = MagicMock()
    mock_hid.enumerate.return_value = []

    c = DellWebcamCollector()
    with patch.dict("sys.modules", {"hid": mock_hid}):
        result = await c.probe()
    assert result is False


@pytest.mark.asyncio
async def test_collect_empty_when_no_devices():
    """Collect should return empty dict when no devices probed."""
    c = DellWebcamCollector()
    result = await c.collect()
    assert result == {}


@pytest.mark.asyncio
async def test_execute_command_unknown_raises():
    """Unknown commands should raise NotImplementedError."""
    c = DellWebcamCollector()
    with pytest.raises(NotImplementedError):
        await c.execute_command("webcam.unknown", "webcam.0", {})


def test_collect_sync_parses_report():
    """_collect_sync should parse a fake HID feature report correctly."""
    c = DellWebcamCollector()

    # Simulate a probed WB7022 device
    c._devices = [
        {
            "vendor_id": 0x413C,
            "product_id": 0xC015,
            "path": b"/fake/path",
            "serial_number": "ABC123",
        }
    ]

    # Build a fake HID report: index 4=HDR(1), 5=AF(0), 6=FOV(2=90°), 7=NR(1), 8=zoom(20=2.0x)
    fake_report = [0] * 64
    fake_report[4] = 1  # HDR on
    fake_report[5] = 0  # Auto-framing off
    fake_report[6] = 2  # FOV 90°
    fake_report[7] = 1  # Noise reduction on
    fake_report[8] = 20  # Digital zoom 2.0x

    mock_device = MagicMock()
    mock_device.get_feature_report.return_value = bytes(fake_report)

    mock_hid = MagicMock()
    mock_hid.device.return_value = mock_device

    with patch.dict("sys.modules", {"hid": mock_hid}):
        metrics = c._collect_sync()

    assert metrics["webcam.0.model"]["value"] == "Dell WB7022 4K"
    assert metrics["webcam.0.manufacturer"]["value"] == "Dell"
    assert metrics["webcam.0.hdr"]["value"] is True
    assert metrics["webcam.0.auto_framing"]["value"] is False
    assert metrics["webcam.0.fov"]["value"] == "90"
    assert metrics["webcam.0.noise_reduction"]["value"] is True
    assert metrics["webcam.0.digital_zoom"]["value"] == 2.0
    assert metrics["webcam.0.global_id"]["value"] == "usb:413C:C015:ABC123"
