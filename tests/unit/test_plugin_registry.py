"""Tests for the plugin registry."""

from __future__ import annotations

from desk2ha_agent.collector.base import Platform
from desk2ha_agent.plugin_registry import get_current_platform


def test_get_current_platform():
    p = get_current_platform()
    assert p in {Platform.WINDOWS, Platform.LINUX, Platform.MACOS, Platform.ANY}
