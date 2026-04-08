"""Tests for Network collector."""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest

from desk2ha_agent.collector.generic.network import NetworkCollector


def test_network_meta():
    assert NetworkCollector.meta.name == "network"
    assert NetworkCollector.meta.tier == "generic"
    assert "network" in NetworkCollector.meta.capabilities


@pytest.mark.asyncio
async def test_probe_with_interfaces():
    with patch("desk2ha_agent.collector.generic.network.psutil") as mock_psutil:
        mock_psutil.net_if_addrs.return_value = {"eth0": []}
        c = NetworkCollector()
        assert await c.probe() is True


@pytest.mark.asyncio
async def test_probe_no_interfaces():
    with patch("desk2ha_agent.collector.generic.network.psutil") as mock_psutil:
        mock_psutil.net_if_addrs.return_value = {}
        c = NetworkCollector()
        assert await c.probe() is False


@pytest.mark.asyncio
async def test_collect_ethernet_speed():
    Snic = namedtuple("Snic", ["isup", "speed", "duplex", "mtu"])
    stats = {"Ethernet": Snic(isup=True, speed=1000, duplex=2, mtu=1500)}

    c = NetworkCollector()
    with (
        patch("desk2ha_agent.collector.generic.network.psutil") as mock_psutil,
        patch.object(c, "_get_wifi_rssi", return_value={}),
    ):
        mock_psutil.net_if_stats.return_value = stats
        metrics = await c.collect()

    assert "network.ethernet.speed_mbps" in metrics
    assert metrics["network.ethernet.speed_mbps"]["value"] == 1000.0


@pytest.mark.asyncio
async def test_collect_skips_down_interfaces():
    Snic = namedtuple("Snic", ["isup", "speed", "duplex", "mtu"])
    stats = {"lo": Snic(isup=False, speed=0, duplex=0, mtu=65536)}

    c = NetworkCollector()
    with (
        patch("desk2ha_agent.collector.generic.network.psutil") as mock_psutil,
        patch.object(c, "_get_wifi_rssi", return_value={}),
    ):
        mock_psutil.net_if_stats.return_value = stats
        metrics = await c.collect()

    assert metrics == {}


def test_wifi_rssi_windows_parsing():
    c = NetworkCollector()
    netsh_output = (
        "    SSID                   : MyNetwork\n"
        "    BSSID                  : aa:bb:cc:dd:ee:ff\n"
        "    Signal                 : 85%\n"
    )
    mock_result = MagicMock()
    mock_result.stdout = netsh_output

    with (
        patch(
            "desk2ha_agent.collector.generic.network.subprocess.run",
            return_value=mock_result,
        ),
        patch("desk2ha_agent.collector.generic.network.sys") as mock_sys,
    ):
        mock_sys.platform = "win32"
        result = c._get_wifi_rssi()

    assert result["network.wifi_signal_percent"]["value"] == 85.0
    assert result["network.wifi_ssid"]["value"] == "MyNetwork"


def test_wifi_rssi_linux_parsing():
    c = NetworkCollector()
    iwconfig_output = (
        'wlan0     IEEE 802.11  ESSID:"HomeWifi"\n'
        "          Link Quality=70/70  Signal level=-30 dBm\n"
    )
    mock_result = MagicMock()
    mock_result.stdout = iwconfig_output

    with (
        patch(
            "desk2ha_agent.collector.generic.network.subprocess.run",
            return_value=mock_result,
        ),
        patch("desk2ha_agent.collector.generic.network.sys") as mock_sys,
    ):
        mock_sys.platform = "linux"
        result = c._get_wifi_rssi()

    assert result["network.wifi_rssi_dbm"]["value"] == -30.0
    assert result["network.wifi_ssid"]["value"] == "HomeWifi"
