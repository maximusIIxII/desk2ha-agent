"""Desk2HA Agent — Multi-vendor desktop telemetry for Home Assistant."""

from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("desk2ha-agent")
except Exception:
    __version__ = "0.0.0-dev"
