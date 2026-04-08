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
