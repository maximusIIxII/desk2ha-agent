"""Tests for Corsair iCUE collector."""

from __future__ import annotations

from desk2ha_agent.collector.vendor.corsair_icue import (
    _KNOWN_PRODUCTS,
    _WIRELESS_PIDS,
    CorsairCollector,
)


class TestMeta:
    def test_name(self) -> None:
        assert CorsairCollector.meta.name == "corsair_icue"

    def test_capabilities(self) -> None:
        assert "peripheral" in CorsairCollector.meta.capabilities

    def test_optional_deps(self) -> None:
        assert "cuesdk" in CorsairCollector.meta.optional_dependencies


class TestKnownProducts:
    def test_has_wireless_headset(self) -> None:
        assert 0x1B65 in _KNOWN_PRODUCTS  # HS80

    def test_has_wireless_mouse(self) -> None:
        assert 0x1B76 in _KNOWN_PRODUCTS  # Dark Core

    def test_wireless_pids_subset(self) -> None:
        assert _WIRELESS_PIDS.issubset(_KNOWN_PRODUCTS.keys())


class TestMatchDevice:
    def test_exact_match(self) -> None:
        collector = CorsairCollector()
        collector._devices = [
            {"pid": 0x1B65, "model": "HS80 RGB Wireless", "wireless": True},
        ]
        assert collector._match_device("HS80 RGB Wireless") == 0

    def test_partial_match(self) -> None:
        collector = CorsairCollector()
        collector._devices = [
            {"pid": 0x1B65, "model": "HS80 RGB Wireless", "wireless": True},
        ]
        assert collector._match_device("HS80 RGB Wireless Headset") == 0

    def test_no_match(self) -> None:
        collector = CorsairCollector()
        collector._devices = [
            {"pid": 0x1B65, "model": "HS80 RGB Wireless", "wireless": True},
        ]
        assert collector._match_device("Razer DeathAdder") is None

    def test_case_insensitive(self) -> None:
        collector = CorsairCollector()
        collector._devices = [
            {"pid": 0x1B65, "model": "HS80 RGB Wireless", "wireless": True},
        ]
        assert collector._match_device("hs80 rgb wireless") == 0
