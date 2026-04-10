"""Tests for DDC/CI collector."""

from __future__ import annotations

from desk2ha_agent.collector.generic.ddcci import DDCCICollector


def test_ddcci_meta():
    assert DDCCICollector.meta.name == "ddcci"
    assert DDCCICollector.meta.tier == "generic"
    assert "display" in DDCCICollector.meta.capabilities


def test_input_source_mapping():
    from desk2ha_agent.collector.generic.ddcci import _INPUT_SOURCE_MAP

    assert _INPUT_SOURCE_MAP[15] == "DP1"
    assert _INPUT_SOURCE_MAP[17] == "HDMI1"


def test_color_preset_mapping():
    from desk2ha_agent.collector.generic.ddcci import (
        _COLOR_PRESET_MAP,
        _COLOR_PRESET_TO_VCP,
    )

    assert _COLOR_PRESET_MAP[1] == "sRGB"
    assert _COLOR_PRESET_MAP[5] == "6500K"
    assert _COLOR_PRESET_MAP[12] == "user2"
    # Reverse mapping
    assert _COLOR_PRESET_TO_VCP["sRGB"] == 1
    assert _COLOR_PRESET_TO_VCP["6500K"] == 5
    assert _COLOR_PRESET_TO_VCP["native"] == 2


def test_vcp_constants():
    from desk2ha_agent.collector.generic.ddcci import (
        _VCP_AUDIO_MUTE,
        _VCP_COLOR_PRESET,
        _VCP_FACTORY_COLOR_RESET,
        _VCP_FACTORY_RESET,
        _VCP_FIRMWARE_LEVEL,
        _VCP_SHARPNESS,
        _VCP_USAGE_HOURS,
    )

    assert _VCP_COLOR_PRESET == 0x14
    assert _VCP_SHARPNESS == 0x87
    assert _VCP_AUDIO_MUTE == 0x8D
    assert _VCP_USAGE_HOURS == 0xC0
    assert _VCP_FIRMWARE_LEVEL == 0xC9
    assert _VCP_FACTORY_RESET == 0x04
    assert _VCP_FACTORY_COLOR_RESET == 0x08
