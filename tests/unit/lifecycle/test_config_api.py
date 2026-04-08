"""Tests for config API."""

from __future__ import annotations

from pathlib import Path

from desk2ha_agent.lifecycle.config_api import get_config_summary, set_config_value


def test_get_config_summary_redacts_secrets(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('[http]\nport = 9693\nauth_token = "secret123"\n')
    summary = get_config_summary(config)
    assert summary["http"]["port"] == 9693
    assert summary["http"]["auth_token"] == "***REDACTED***"


def test_set_config_value(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("[collectors]\ndisabled = []\n")
    result = set_config_value(config, "collectors", "disabled", ["uvc"])
    assert result["status"] == "applied"
    # Verify file was updated
    content = config.read_text()
    assert "uvc" in content


def test_set_config_hot_reload(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('[logging]\nlevel = "INFO"\n')
    result = set_config_value(config, "logging", "level", "DEBUG")
    assert result["restart_required"] is False
