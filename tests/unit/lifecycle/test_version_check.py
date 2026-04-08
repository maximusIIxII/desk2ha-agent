"""Tests for version check logic."""

from __future__ import annotations

from desk2ha_agent.lifecycle.version_check import _is_newer


def test_newer_version() -> None:
    assert _is_newer("0.2.0", "0.1.0") is True


def test_same_version() -> None:
    assert _is_newer("0.1.0", "0.1.0") is False


def test_older_version() -> None:
    assert _is_newer("0.1.0", "0.2.0") is False


def test_patch_newer() -> None:
    assert _is_newer("0.1.1", "0.1.0") is True


def test_major_newer() -> None:
    assert _is_newer("1.0.0", "0.9.9") is True


def test_invalid_version() -> None:
    assert _is_newer("invalid", "0.1.0") is False
