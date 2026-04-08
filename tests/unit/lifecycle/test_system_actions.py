"""Tests for system actions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from desk2ha_agent.lifecycle.system_actions import (
    hibernate_system,
    lock_screen,
    shutdown_system,
    sleep_system,
)


@pytest.mark.asyncio
async def test_lock_screen_linux():
    with (
        patch("desk2ha_agent.lifecycle.system_actions.sys") as mock_sys,
        patch("desk2ha_agent.lifecycle.system_actions.subprocess") as mock_sub,
    ):
        mock_sys.platform = "linux"
        result = await lock_screen()

    assert result["status"] == "completed"
    assert result["action"] == "lock"
    mock_sub.run.assert_called_once_with(["loginctl", "lock-session"], timeout=5)


@pytest.mark.asyncio
async def test_sleep_linux():
    with (
        patch("desk2ha_agent.lifecycle.system_actions.sys") as mock_sys,
        patch("desk2ha_agent.lifecycle.system_actions.subprocess") as mock_sub,
    ):
        mock_sys.platform = "linux"
        result = await sleep_system()

    assert result["status"] == "completed"
    assert result["action"] == "sleep"
    mock_sub.run.assert_called_once_with(["systemctl", "suspend"], timeout=5)


@pytest.mark.asyncio
async def test_shutdown_linux():
    with (
        patch("desk2ha_agent.lifecycle.system_actions.sys") as mock_sys,
        patch("desk2ha_agent.lifecycle.system_actions.subprocess") as mock_sub,
    ):
        mock_sys.platform = "linux"
        result = await shutdown_system(delay=60)

    assert result["status"] == "completed"
    assert result["action"] == "shutdown"
    mock_sub.Popen.assert_called_once_with(["sudo", "shutdown", "-h", "+1"])


@pytest.mark.asyncio
async def test_hibernate_linux():
    with (
        patch("desk2ha_agent.lifecycle.system_actions.sys") as mock_sys,
        patch("desk2ha_agent.lifecycle.system_actions.subprocess") as mock_sub,
    ):
        mock_sys.platform = "linux"
        result = await hibernate_system()

    assert result["status"] == "completed"
    assert result["action"] == "hibernate"
    mock_sub.run.assert_called_once_with(["systemctl", "hibernate"], timeout=5)


@pytest.mark.asyncio
async def test_lock_screen_failure():
    with (
        patch("desk2ha_agent.lifecycle.system_actions.sys") as mock_sys,
        patch("desk2ha_agent.lifecycle.system_actions.subprocess") as mock_sub,
    ):
        mock_sys.platform = "linux"
        mock_sub.run.side_effect = OSError("no loginctl")
        result = await lock_screen()

    assert result["status"] == "failed"
    assert "no loginctl" in result["message"]


@pytest.mark.asyncio
async def test_hibernate_unsupported_macos():
    with patch("desk2ha_agent.lifecycle.system_actions.sys") as mock_sys:
        mock_sys.platform = "darwin"
        result = await hibernate_system()

    assert result["status"] == "failed"
    assert "not supported" in result["message"]
