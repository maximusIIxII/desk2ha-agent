"""Tests for elevated helper registry."""

from __future__ import annotations

from desk2ha_agent.helper.registry import ELEVATED_MODULES


def test_registry_has_dell_dcm():
    assert "desk2ha_agent.collector.vendor.dell_dcm" in ELEVATED_MODULES


def test_registry_modules_are_strings():
    for mod in ELEVATED_MODULES:
        assert isinstance(mod, str)
        assert "." in mod
