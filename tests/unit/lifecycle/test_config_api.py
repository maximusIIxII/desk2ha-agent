"""Tests for config API."""

from __future__ import annotations

from pathlib import Path

from desk2ha_agent.lifecycle.config_api import (
    bulk_set_config,
    get_config_summary,
    set_config_value,
)


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


def test_bulk_set_config_multiple_keys(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('[collectors]\ndisabled = []\n\n[logging]\nlevel = "INFO"\n')
    result = bulk_set_config(
        config,
        [
            {"section": "collectors", "key": "disabled", "value": ["uvc"]},
            {"section": "logging", "key": "level", "value": "DEBUG"},
        ],
    )
    assert result["status"] == "applied"
    assert result["applied"] == 2
    content = config.read_text()
    assert "uvc" in content
    assert "DEBUG" in content


def test_bulk_set_config_forbidden_key(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("[http]\nport = 9693\n")
    result = bulk_set_config(
        config,
        [
            {"section": "http", "key": "port", "value": 9999},
            {"section": "http", "key": "auth_token", "value": "hacked"},
        ],
    )
    assert result["status"] == "forbidden"
    assert result["applied"] == 0
    # Verify file was NOT modified
    assert "9693" in config.read_text()


def test_bulk_set_config_empty(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("[http]\nport = 9693\n")
    result = bulk_set_config(config, [])
    assert result["status"] == "applied"
    assert result["applied"] == 0


def test_bulk_set_config_restart_detection(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('[logging]\nlevel = "INFO"\n\n[collectors]\ndisabled = []\n')
    result = bulk_set_config(
        config,
        [
            {"section": "logging", "key": "level", "value": "DEBUG"},  # hot-reload
            {"section": "collectors", "key": "disabled", "value": ["uvc"]},  # needs restart
        ],
    )
    assert result["status"] == "applied"
    assert result["restart_required"] is True
    assert result["results"][0]["restart_required"] is False
    assert result["results"][1]["restart_required"] is True
