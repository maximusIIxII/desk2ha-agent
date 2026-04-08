"""Tests for USB PD collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from desk2ha_agent.collector.generic.usb_pd import USBPDCollector


def test_usb_pd_meta():
    assert USBPDCollector.meta.name == "usb_pd"
    assert USBPDCollector.meta.tier == "generic"
    assert "power" in USBPDCollector.meta.capabilities


@pytest.mark.asyncio
async def test_probe_windows_with_battery():
    c = USBPDCollector()
    mock_battery = MagicMock()
    mock_battery.power_plugged = True

    with (
        patch("desk2ha_agent.collector.generic.usb_pd.sys") as mock_sys,
        patch(
            "desk2ha_agent.collector.generic.usb_pd.psutil",
            create=True,
        ) as mock_psutil,
    ):
        mock_sys.platform = "win32"
        mock_psutil.sensors_battery.return_value = mock_battery
        # Patch the import inside _probe_windows
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            result = await c.probe()

    assert result is True
    assert c._has_pd_info is True


@pytest.mark.asyncio
async def test_probe_windows_no_battery():
    c = USBPDCollector()

    with patch("desk2ha_agent.collector.generic.usb_pd.sys") as mock_sys:
        mock_sys.platform = "win32"
        mock_psutil = MagicMock()
        mock_psutil.sensors_battery.return_value = None
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            result = await c.probe()

    assert result is False


def test_collect_windows_with_battery():
    c = USBPDCollector()
    mock_battery = MagicMock()
    mock_battery.power_plugged = True

    mock_psutil = MagicMock()
    mock_psutil.sensors_battery.return_value = mock_battery

    with (
        patch.dict("sys.modules", {"psutil": mock_psutil}),
        patch.object(c, "_collect_wmi_power"),
    ):
        metrics = c._collect_windows()

    assert "power.usb_pd_connected" in metrics
    assert metrics["power.usb_pd_connected"]["value"] is True


@pytest.mark.asyncio
async def test_teardown_resets_state():
    c = USBPDCollector()
    c._has_pd_info = True
    await c.teardown()
    assert c._has_pd_info is False
