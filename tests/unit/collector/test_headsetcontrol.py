"""Tests for the HeadsetControl collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from desk2ha_agent.collector.generic.headsetcontrol import HeadsetControlCollector


async def test_probe_no_binary() -> None:
    """Should return False if headsetcontrol is not installed."""
    with patch("shutil.which", return_value=None):
        c = HeadsetControlCollector()
        assert await c.probe() is False


async def test_parse_devices() -> None:
    """Should parse HeadsetControl JSON output into flat metrics."""
    c = HeadsetControlCollector()
    devices = [
        {
            "product": "Arctis Nova 7",
            "vendor": "SteelSeries",
            "battery": {"level": 85, "status": "discharging"},
            "capabilities": {"sidetone": 64, "lights": True},
            "firmware_version": "1.2.3",
        }
    ]
    metrics = c._parse_devices(devices)

    assert "peripheral.headset_arctis_nova_7.battery_level" in metrics
    assert metrics["peripheral.headset_arctis_nova_7.battery_level"]["value"] == 85.0
    assert metrics["peripheral.headset_arctis_nova_7.manufacturer"]["value"] == "SteelSeries"
    assert metrics["peripheral.headset_arctis_nova_7.charging"]["value"] is False
    assert metrics["peripheral.headset_arctis_nova_7.sidetone"]["value"] == 64
    assert metrics["peripheral.headset_arctis_nova_7.led"]["value"] is True
    assert metrics["peripheral.headset_arctis_nova_7.firmware"]["value"] == "1.2.3"
