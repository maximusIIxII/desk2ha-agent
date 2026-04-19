"""Tests for `python -m desk2ha_agent.helper` argument + config parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from desk2ha_agent.helper.__main__ import _parse_args, _read_secret_from_config


def test_parse_args_config_flag(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[helper]\nsecret = "abc"\n', encoding="utf-8")
    args = _parse_args(["-c", str(cfg)])
    assert args.config == cfg


def test_parse_args_config_long_form(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[helper]\nsecret = "abc"\n', encoding="utf-8")
    args = _parse_args(["--config", str(cfg)])
    assert args.config == cfg


def test_parse_args_defaults():
    args = _parse_args([])
    assert args.config is None
    assert args.secret is None
    assert args.port == 9694


def test_read_secret_from_config(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[helper]\nsecret = "top-secret-value"\n', encoding="utf-8")
    assert _read_secret_from_config(cfg) == "top-secret-value"


def test_read_secret_from_config_missing_section(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[other]\nkey = "val"\n', encoding="utf-8")
    assert _read_secret_from_config(cfg) is None


def test_read_secret_from_config_missing_file(tmp_path: Path):
    assert _read_secret_from_config(tmp_path / "does-not-exist.toml") is None


def test_read_secret_from_config_malformed(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("not valid toml = = =\n[", encoding="utf-8")
    assert _read_secret_from_config(cfg) is None


def test_read_secret_from_config_no_secret_key(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[helper]\nport = 9694\n", encoding="utf-8")
    assert _read_secret_from_config(cfg) is None


@pytest.mark.parametrize(
    "content,expected",
    [
        ('[helper]\nsecret = "x"\n', "x"),
        ('[helper]\nsecret = "with-dashes_and_99"\n', "with-dashes_and_99"),
    ],
)
def test_read_secret_round_trip(tmp_path: Path, content: str, expected: str):
    cfg = tmp_path / "config.toml"
    cfg.write_text(content, encoding="utf-8")
    assert _read_secret_from_config(cfg) == expected
