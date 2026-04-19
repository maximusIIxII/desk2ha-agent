"""Tests for USB PD collector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from desk2ha_agent.collector.generic.usb_pd import (
    USBPDCollector,
    _classify_charge_mode,
)


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


# ---------------------------------------------------------------------------
# _classify_charge_mode — Dell Adaptive Charging pause detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,level,expected",
    [
        # Active charging states (Win32 BatteryStatus 6-9)
        (6, 50.0, "charging"),
        (7, 50.0, "charging"),
        (8, 50.0, "charging"),
        (9, 50.0, "charging"),
        # Discharging on battery
        (1, 50.0, "discharging"),
        # Explicit Windows "full" status
        (3, 100.0, "full"),
        # Low / critical
        (4, 10.0, "low"),
        (5, 3.0, "critical"),
        # Status 2 ("AC connected, not charging"):
        #   - below threshold → adaptive-pause style "ac_idle"
        #   - at/above threshold → treat as "full"
        #   - unknown level → fall back to "ac_idle"
        (2, 80.0, "ac_idle"),
        (2, 94.9, "ac_idle"),
        (2, 95.0, "full"),
        (2, 100.0, "full"),
        (2, None, "ac_idle"),
        # Missing status → unknown
        (None, 50.0, "unknown"),
        (None, None, "unknown"),
        # Out-of-spec status codes fall through to unknown
        (99, 50.0, "unknown"),
    ],
)
def test_classify_charge_mode(status, level, expected):
    assert _classify_charge_mode(status, level) == expected
