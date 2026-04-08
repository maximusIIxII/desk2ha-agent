"""Tests for config loading."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from desk2ha_agent.config import AgentConfig, load_config


def test_default_config():
    """Default config should have HTTP and MQTT disabled."""
    config = AgentConfig()
    assert config.http.enabled is False
    assert config.mqtt.enabled is False
    assert config.http.port == 9693
    assert config.mqtt.base_topic == "desk2ha"


def test_load_minimal_config(tmp_path: Path):
    """Load a minimal TOML config."""
    toml = tmp_path / "test.toml"
    toml.write_text(
        '[http]\nenabled = true\nauth_token = "test-token-123"\n'
    )
    config = load_config(toml)
    assert config.http.enabled is True
    assert config.http.auth_token == "test-token-123"


def test_http_token_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """HTTP token resolved from env var."""
    monkeypatch.setenv("DESK2HA_HTTP_TOKEN", "env-token-456")
    toml = tmp_path / "test.toml"
    toml.write_text("[http]\nenabled = true\n")
    config = load_config(toml)
    assert config.http.auth_token == "env-token-456"


def test_http_enabled_without_token_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """HTTP enabled without token should raise."""
    monkeypatch.delenv("DESK2HA_HTTP_TOKEN", raising=False)
    toml = tmp_path / "test.toml"
    toml.write_text("[http]\nenabled = true\n")
    with pytest.raises(ValueError, match="auth_token"):
        load_config(toml)


def test_collector_intervals(tmp_path: Path):
    """Per-collector intervals parsed correctly."""
    toml = tmp_path / "test.toml"
    toml.write_text(
        '[collectors.intervals]\nddcci = 60\nhid_battery = 120\n'
    )
    config = load_config(toml)
    assert config.collectors.intervals == {"ddcci": 60, "hid_battery": 120}
