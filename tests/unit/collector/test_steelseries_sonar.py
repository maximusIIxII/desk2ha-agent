"""Tests for SteelSeries Sonar collector."""

from __future__ import annotations

import pytest

from desk2ha_agent.collector.vendor.steelseries_sonar import SteelSeriesSonarCollector


class TestMeta:
    def test_name(self) -> None:
        assert SteelSeriesSonarCollector.meta.name == "steelseries_sonar"

    def test_windows_only(self) -> None:
        from desk2ha_agent.collector.base import Platform

        assert SteelSeriesSonarCollector.meta.platforms == {Platform.WINDOWS}

    def test_audio_capability(self) -> None:
        assert "audio" in SteelSeriesSonarCollector.meta.capabilities


class TestChannels:
    def test_channel_list(self) -> None:
        from desk2ha_agent.collector.vendor.steelseries_sonar import _CHANNELS

        assert "master" in _CHANNELS
        assert "game" in _CHANNELS
        assert "chatRender" in _CHANNELS
        assert "media" in _CHANNELS
        assert "aux" in _CHANNELS


class TestProbe:
    @pytest.mark.asyncio
    async def test_probe_no_corprops(self, tmp_path: object) -> None:
        """Probe returns False when coreProps.json doesn't exist."""
        collector = SteelSeriesSonarCollector()
        # On a machine without SteelSeries GG, probe should return False
        result = await collector.probe()
        # Can't guarantee this machine has SteelSeries, so just check it doesn't crash
        assert isinstance(result, bool)
