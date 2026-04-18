"""Tests for USB watchdog and usb_reset command."""

from __future__ import annotations

from unittest.mock import patch

from desk2ha_agent.lifecycle.usb_watchdog import (
    UsbWatchdog,
    _get_usb_device_count,
    _is_thunderbolt_active,
    usb_reset,
)
from desk2ha_agent.state import StateCache


async def test_usb_watchdog_emits_metrics() -> None:
    """Watchdog check should emit usb_device_count and usb_reset_count."""
    state = StateCache()
    watchdog = UsbWatchdog(state, interval=60, auto_reset=False)

    with (
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._get_usb_device_count",
            return_value=5,
        ),
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._is_thunderbolt_active",
            return_value=True,
        ),
    ):
        await watchdog._check()

    snapshot = await state.snapshot()
    assert snapshot["system.usb_device_count"]["value"] == 5
    assert snapshot["system.usb_reset_count"]["value"] == 0


async def test_usb_watchdog_detects_stale_no_auto_reset() -> None:
    """Watchdog should detect stale state but not reset if auto_reset=False."""
    state = StateCache()
    watchdog = UsbWatchdog(state, interval=60, auto_reset=False)

    with (
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._get_usb_device_count",
            return_value=0,
        ),
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._is_thunderbolt_active",
            return_value=True,
        ),
    ):
        await watchdog._check()

    snapshot = await state.snapshot()
    assert snapshot["system.usb_device_count"]["value"] == 0
    assert snapshot["system.usb_reset_count"]["value"] == 0


async def test_usb_watchdog_auto_reset() -> None:
    """Watchdog should trigger reset when stale and auto_reset=True."""
    state = StateCache()
    watchdog = UsbWatchdog(state, interval=60, auto_reset=True)

    with (
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._get_usb_device_count",
            return_value=0,
        ),
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._is_thunderbolt_active",
            return_value=True,
        ),
        patch(
            "desk2ha_agent.lifecycle.usb_watchdog._usb_reset_sync",
            return_value={"status": "completed", "action": "usb_reset"},
        ),
    ):
        await watchdog._check()

    snapshot = await state.snapshot()
    assert snapshot["system.usb_reset_count"]["value"] == 1


async def test_usb_reset_returns_dict() -> None:
    """usb_reset should return a status dict."""
    with patch(
        "desk2ha_agent.lifecycle.usb_watchdog._usb_reset_sync",
        return_value={"status": "completed", "action": "usb_reset"},
    ):
        result = await usb_reset()
    assert result["status"] == "completed"
    assert result["action"] == "usb_reset"


def test_get_usb_device_count_handles_failure() -> None:
    """Should return 0 on failure."""
    with patch("subprocess.run", side_effect=Exception("boom")):
        count = _get_usb_device_count()
    assert count == 0


def test_is_thunderbolt_active_handles_failure() -> None:
    """Should return False on failure."""
    with patch("subprocess.run", side_effect=Exception("boom")):
        active = _is_thunderbolt_active()
    assert active is False
