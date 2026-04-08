"""Tests for Logitech Litra vendor collector."""

from __future__ import annotations

import pytest

from desk2ha_agent.collector.vendor.logitech_litra import (
    LogitechLitraCollector,
    _build_report,
    _uint16_be,
)


def test_litra_meta():
    assert LogitechLitraCollector.meta.name == "logitech_litra"
    assert LogitechLitraCollector.meta.tier == "vendor"
    assert "peripheral" in LogitechLitraCollector.meta.capabilities
    assert "control" in LogitechLitraCollector.meta.capabilities
    assert LogitechLitraCollector.meta.requires_hardware == "Logitech Litra Glow/Beam"


def test_build_report_length():
    report = _build_report(0x01)
    assert len(report) == 20


def test_build_report_header():
    report = _build_report(0x01, 0xAB, 0xCD)
    assert report[:3] == [0x11, 0xFF, 0x04]
    assert report[3] == 0x01
    assert report[4] == 0xAB
    assert report[5] == 0xCD
    assert all(b == 0 for b in report[6:])


def test_uint16_be():
    hi, lo = _uint16_be(2700)
    assert (hi << 8) | lo == 2700

    hi, lo = _uint16_be(6500)
    assert (hi << 8) | lo == 6500

    hi, lo = _uint16_be(0)
    assert hi == 0 and lo == 0

    hi, lo = _uint16_be(255)
    assert hi == 0 and lo == 255


def test_init_empty_devices():
    c = LogitechLitraCollector()
    assert c._devices == []


@pytest.mark.asyncio
async def test_teardown_clears_devices():
    c = LogitechLitraCollector()
    c._devices = [{"path": b"/dev/foo"}]
    await c.teardown()
    assert c._devices == []


@pytest.mark.asyncio
async def test_execute_command_rejects_non_litra():
    c = LogitechLitraCollector()
    with pytest.raises(NotImplementedError):
        await c.execute_command("display.set_brightness", "", {})


@pytest.mark.asyncio
async def test_execute_command_device_not_found():
    c = LogitechLitraCollector()
    c._devices = []
    result = await c.execute_command("litra.set_power", "peripheral.litra_0", {"value": True})
    assert result["status"] == "failed"
    assert "not found" in result["message"]
