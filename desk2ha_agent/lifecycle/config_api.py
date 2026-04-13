"""Runtime config modification."""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keys that must never be modified via the config API
_FORBIDDEN_KEYS = frozenset({"auth_token", "auth_token_env", "password"})


def get_config_summary(config_path: Path) -> dict[str, Any]:
    """Return redacted config summary (no secrets)."""
    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception:
        return {}

    # Redact secrets
    summary: dict[str, Any] = {}
    for section, values in raw.items():
        if isinstance(values, dict):
            clean = {}
            for k, v in values.items():
                if any(secret in k.lower() for secret in ("token", "password", "secret", "key")):
                    clean[k] = "***REDACTED***"
                else:
                    clean[k] = v
            summary[section] = clean
        else:
            summary[section] = values
    return summary


def set_config_value(config_path: Path, section: str, key: str, value: Any) -> dict[str, Any]:
    """Update a config value in the TOML file.

    Returns dict with status and whether restart is required.
    """
    if key in _FORBIDDEN_KEYS:
        return {"status": "forbidden", "message": f"Key '{key}' cannot be modified via API"}

    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}

    # Navigate to section (supports dotted paths like "collectors.intervals")
    parts = section.split(".")
    target = raw
    for part in parts:
        if part not in target:
            target[part] = {}
        target = target[part]

    old_value = target.get(key)
    target[key] = value

    # Write back
    try:
        _write_toml(config_path, raw)
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}

    # Determine if restart is needed
    hot_reload_keys = {"level", "token"}
    hot_reload_sections = {"logging"}
    restart_required = not (key in hot_reload_keys or section in hot_reload_sections)

    logger.info("Config updated: [%s] %s = %s (was %s)", section, key, value, old_value)
    return {
        "status": "applied",
        "restart_required": restart_required,
        "old_value": old_value,
    }


def bulk_set_config(
    config_path: Path,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply multiple config changes atomically (single read/write cycle).

    Each change is a dict with ``section``, ``key``, and ``value``.
    Returns summary with per-change results.
    """
    if not changes:
        return {"status": "applied", "applied": 0, "restart_required": False, "results": []}

    # Fail-fast: reject entire batch if any key is forbidden
    for change in changes:
        key = change.get("key", "")
        if key in _FORBIDDEN_KEYS:
            return {
                "status": "forbidden",
                "message": f"Key '{key}' cannot be modified via API",
                "applied": 0,
                "restart_required": False,
                "results": [],
            }

    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "applied": 0,
            "restart_required": False,
            "results": [],
        }

    hot_reload_keys = {"level", "token"}
    hot_reload_sections = {"logging"}
    any_restart = False
    results: list[dict[str, Any]] = []

    for change in changes:
        section = change.get("section", "")
        key = change.get("key", "")
        value = change.get("value")

        # Navigate to section
        parts = section.split(".")
        target = raw
        for part in parts:
            if part not in target:
                target[part] = {}
            target = target[part]

        old_value = target.get(key)
        target[key] = value

        restart_required = not (key in hot_reload_keys or section in hot_reload_sections)
        if restart_required:
            any_restart = True

        results.append(
            {
                "section": section,
                "key": key,
                "old_value": old_value,
                "restart_required": restart_required,
            }
        )

    try:
        _write_toml(config_path, raw)
    except Exception as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "applied": 0,
            "restart_required": False,
            "results": [],
        }

    applied = len(results)
    logger.info("Bulk config: %d keys updated (restart_required=%s)", applied, any_restart)
    return {
        "status": "applied",
        "applied": applied,
        "restart_required": any_restart,
        "results": results,
    }


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Write dict as TOML. Simple implementation for flat/nested dicts."""
    lines: list[str] = []

    # Write top-level scalars first
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_value(value)}")

    if lines:
        lines.append("")

    # Write sections
    for section, values in data.items():
        if isinstance(values, dict):
            _write_section(lines, section, values)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_section(lines: list[str], prefix: str, data: dict[str, Any]) -> None:
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    subsections = {k: v for k, v in data.items() if isinstance(v, dict)}

    if scalars:
        lines.append(f"[{prefix}]")
        for k, v in scalars.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")

    for sub_name, sub_data in subsections.items():
        _write_section(lines, f"{prefix}.{sub_name}", sub_data)


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        items = ", ".join(_toml_value(i) for i in v)
        return f"[{items}]"
    return f'"{v}"'
