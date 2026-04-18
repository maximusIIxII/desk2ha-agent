"""Tests for the HeadsetControl collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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


async def test_parse_devices_vid_pid() -> None:
    """Should use VID:PID for device key when available."""
    c = HeadsetControlCollector()
    devices = [
        {
            "product": "Corsair VOID",
            "vendor": "Corsair",
            "id_vendor": "1B1C",
            "id_product": "0A14",
            "battery": {"level": 50, "status": "charging"},
            "capabilities": {},
        }
    ]
    metrics = c._parse_devices(devices)
    prefix = "peripheral.headset_1b1c_0a14"
    assert metrics[f"{prefix}.global_id"]["value"] == "usb:1B1C:0A14"
    assert metrics[f"{prefix}.charging"]["value"] is True


async def test_parse_devices_extended_features() -> None:
    """Should parse equalizer_preset, inactive_time, voice_prompts."""
    c = HeadsetControlCollector()
    devices = [
        {
            "product": "Test Headset",
            "vendor": "Test",
            "id_vendor": "AAAA",
            "id_product": "BBBB",
            "capabilities": {
                "equalizer_preset": 2,
                "inactive_time": 30,
                "voice_prompts": True,
            },
        }
    ]
    metrics = c._parse_devices(devices)
    prefix = "peripheral.headset_aaaa_bbbb"
    assert metrics[f"{prefix}.equalizer_preset"]["value"] == "2"
    assert metrics[f"{prefix}.inactive_timeout"]["value"] == 30
    assert metrics[f"{prefix}.voice_prompts"]["value"] is True


async def test_execute_sidetone() -> None:
    """set_sidetone should call CLI with -s flag."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with patch.object(c, "_run_cli", new_callable=AsyncMock) as mock_cli:
        result = await c.execute_command("headset.set_sidetone", "", {"value": 50})
    assert result["status"] == "completed"
    mock_cli.assert_called_once_with("-s", "50")


async def test_execute_led() -> None:
    """set_led should call CLI with -l flag."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with patch.object(c, "_run_cli", new_callable=AsyncMock) as mock_cli:
        result = await c.execute_command("headset.set_led", "", {"enabled": False})
    assert result["status"] == "completed"
    mock_cli.assert_called_once_with("-l", "0")


async def test_execute_inactive_timeout() -> None:
    """set_inactive_timeout should call CLI with -i flag."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with patch.object(c, "_run_cli", new_callable=AsyncMock) as mock_cli:
        result = await c.execute_command("headset.set_inactive_timeout", "", {"value": 30})
    assert result["status"] == "completed"
    mock_cli.assert_called_once_with("-i", "30")


async def test_execute_equalizer_preset() -> None:
    """set_equalizer_preset should call CLI with -p flag."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with patch.object(c, "_run_cli", new_callable=AsyncMock) as mock_cli:
        result = await c.execute_command("headset.set_equalizer_preset", "", {"preset": "2"})
    assert result["status"] == "completed"
    mock_cli.assert_called_once_with("-p", "2")


async def test_execute_voice_prompts() -> None:
    """set_voice_prompts should call CLI with --voice-prompt flag."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with patch.object(c, "_run_cli", new_callable=AsyncMock) as mock_cli:
        result = await c.execute_command("headset.set_voice_prompts", "", {"enabled": True})
    assert result["status"] == "completed"
    mock_cli.assert_called_once_with("--voice-prompt", "1")


async def test_execute_unknown_raises() -> None:
    """Unknown commands should raise NotImplementedError."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with pytest.raises(NotImplementedError):
        await c.execute_command("headset.unknown", "", {})


async def test_execute_sidetone_out_of_range() -> None:
    """Sidetone out of range should raise ValueError."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with pytest.raises(ValueError, match="0-128"):
        await c.execute_command("headset.set_sidetone", "", {"value": 200})


async def test_execute_inactive_timeout_out_of_range() -> None:
    """Inactive timeout > 90 should raise ValueError."""
    c = HeadsetControlCollector()
    c._exe = "/usr/bin/headsetcontrol"
    with pytest.raises(ValueError, match="0-90"):
        await c.execute_command("headset.set_inactive_timeout", "", {"value": 120})
