"""Tests for UVC webcam collector."""

from __future__ import annotations

from desk2ha_agent.collector.generic.uvc import UVCCollector


def test_uvc_meta():
    assert UVCCollector.meta.name == "uvc"
    assert UVCCollector.meta.tier == "generic"
    assert "peripheral" in UVCCollector.meta.capabilities
