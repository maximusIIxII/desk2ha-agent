"""Tests for DDC/CI collector."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


def test_smoke_test_passes_when_one_monitor_responds():
    """At least one monitor must accept a VCP read for smoke-test to pass."""
    good_monitor = MagicMock()
    good_monitor.__enter__ = MagicMock(return_value=good_monitor)
    good_monitor.__exit__ = MagicMock(return_value=False)
    good_monitor.get_luminance = MagicMock(return_value=75)

    assert DDCCICollector._ddcci_smoke_test_sync([good_monitor]) is True


def test_smoke_test_fails_when_all_monitors_throw():
    """get_monitors() returning handles is not enough — VCP reads must succeed."""
    bad_monitor = MagicMock()
    bad_monitor.__enter__ = MagicMock(return_value=bad_monitor)
    bad_monitor.__exit__ = MagicMock(return_value=False)
    bad_monitor.get_luminance = MagicMock(side_effect=OSError("DDC/CI not available"))

    assert DDCCICollector._ddcci_smoke_test_sync([bad_monitor, bad_monitor]) is False


def test_smoke_test_passes_when_first_monitor_fails_but_second_works():
    """One bad monitor in the list must not poison the probe."""
    bad = MagicMock()
    bad.__enter__ = MagicMock(return_value=bad)
    bad.__exit__ = MagicMock(return_value=False)
    bad.get_luminance = MagicMock(side_effect=OSError("nope"))

    good = MagicMock()
    good.__enter__ = MagicMock(return_value=good)
    good.__exit__ = MagicMock(return_value=False)
    good.get_luminance = MagicMock(return_value=50)

    assert DDCCICollector._ddcci_smoke_test_sync([bad, good]) is True


def test_smoke_test_empty_list():
    """No monitors → no smoke."""
    assert DDCCICollector._ddcci_smoke_test_sync([]) is False


def test_has_live_vcp_data_true_with_brightness():
    metrics = {
        "display.0.model": "U5226KW",
        "display.0.brightness_percent": 75.0,
    }
    assert DDCCICollector._has_live_vcp_data(metrics) is True


def test_has_live_vcp_data_true_with_input_source():
    assert DDCCICollector._has_live_vcp_data({"display.0.input_source": "HDMI1"}) is True


def test_has_live_vcp_data_false_with_only_static_fields():
    """model + manufacturer come from registry-cached EDID, not from live VCP reads.

    This is exactly the half-init state we observed on 2026-04-26: agent
    serving displays with only model+manufacturer (and sometimes power_state)
    but missing brightness/contrast/volume/input_source/KVM. self-heal must
    detect this.
    """
    metrics = {
        "display.0.model": "U5226KW",
        "display.0.manufacturer": "Dell",
    }
    assert DDCCICollector._has_live_vcp_data(metrics) is False


def test_has_live_vcp_data_false_with_empty_dict():
    assert DDCCICollector._has_live_vcp_data({}) is False


@pytest.mark.asyncio
async def test_collect_resets_streak_on_live_data(monkeypatch):
    """A successful collect with live VCP data must reset the empty-streak counter."""
    collector = DDCCICollector()
    collector._empty_collect_streak = 2

    def fake_sync(self):
        return {"display.0.model": "U5226KW", "display.0.brightness_percent": 75.0}

    monkeypatch.setattr(DDCCICollector, "_collect_sync", fake_sync)

    result = await collector.collect()
    assert result["display.0.brightness_percent"] == 75.0
    assert collector._empty_collect_streak == 0


@pytest.mark.asyncio
async def test_collect_increments_streak_on_static_only(monkeypatch):
    """Collects with only model/manufacturer must accumulate the streak counter."""
    collector = DDCCICollector()

    def fake_sync(self):
        return {"display.0.model": "U5226KW", "display.0.manufacturer": "Dell"}

    monkeypatch.setattr(DDCCICollector, "_collect_sync", fake_sync)

    # Below threshold: no helper-fallback attempt yet
    for expected in (1, 2):
        await collector.collect()
        assert collector._empty_collect_streak == expected
        assert collector._use_helper is False


@pytest.mark.asyncio
async def test_collect_triggers_helper_fallback_at_threshold(monkeypatch):
    """At SELF_HEAL_THRESHOLD consecutive empty collects, helper fallback fires."""
    collector = DDCCICollector()
    collector._empty_collect_streak = collector.SELF_HEAL_THRESHOLD - 1

    def fake_sync(self):
        return {"display.0.model": "U5226KW"}

    fallback_called = {"count": 0}

    async def fake_fallback(self):
        fallback_called["count"] += 1
        return False  # simulate helper not (yet) available

    monkeypatch.setattr(DDCCICollector, "_collect_sync", fake_sync)
    monkeypatch.setattr(DDCCICollector, "_try_helper_fallback", fake_fallback)

    await collector.collect()
    assert fallback_called["count"] == 1
    # Streak resets after a fallback attempt to avoid log spam
    assert collector._empty_collect_streak == 0


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
