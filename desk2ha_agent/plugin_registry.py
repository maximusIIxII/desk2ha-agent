"""Plugin discovery and registration."""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desk2ha_agent.collector.base import Collector

from desk2ha_agent.collector.base import Platform

logger = logging.getLogger(__name__)

# All known collector modules, in load order
COLLECTOR_MODULES: list[str] = [
    # Platform (one per OS, mutually exclusive)
    "desk2ha_agent.collector.platform.windows",
    "desk2ha_agent.collector.platform.linux",
    "desk2ha_agent.collector.platform.macos",
    # Generic (cross-platform)
    "desk2ha_agent.collector.generic.ddcci",
    "desk2ha_agent.collector.generic.uvc",
    "desk2ha_agent.collector.generic.ble_battery",
    "desk2ha_agent.collector.generic.hid_battery",
    "desk2ha_agent.collector.generic.headsetcontrol",
    "desk2ha_agent.collector.generic.usb_pd",
    "desk2ha_agent.collector.generic.network",
    "desk2ha_agent.collector.generic.usb_devices",
    "desk2ha_agent.collector.generic.wireless_receiver",
    # Vendor plugins
    "desk2ha_agent.collector.vendor.dell_dcm",
    "desk2ha_agent.collector.vendor.hp_wmi",
    "desk2ha_agent.collector.vendor.lenovo_wmi",
    "desk2ha_agent.collector.vendor.logitech_litra",
    "desk2ha_agent.collector.vendor.corsair_icue",
    "desk2ha_agent.collector.vendor.steelseries",
    "desk2ha_agent.collector.vendor.steelseries_sonar",
    "desk2ha_agent.collector.vendor.razer",
]


def get_current_platform() -> Platform:
    """Detect the current platform."""
    if sys.platform == "win32":
        return Platform.WINDOWS
    if sys.platform == "linux":
        return Platform.LINUX
    if sys.platform == "darwin":
        return Platform.MACOS
    return Platform.ANY


async def discover_collectors(
    current_platform: Platform | None = None,
    disabled: set[str] | None = None,
) -> list[Collector]:
    """Discover, probe, and activate all available collectors."""
    if current_platform is None:
        current_platform = get_current_platform()
    disabled = disabled or set()
    active: list[Collector] = []

    for module_path in COLLECTOR_MODULES:
        collector_name = module_path.rsplit(".", 1)[-1]
        if collector_name in disabled:
            logger.info("Collector %s disabled by config", collector_name)
            continue

        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            logger.debug("Skipping %s: %s", module_path, exc)
            continue

        collector_cls = getattr(mod, "COLLECTOR_CLASS", None)
        if collector_cls is None:
            logger.warning("Module %s has no COLLECTOR_CLASS", module_path)
            continue

        meta = collector_cls.meta
        if current_platform not in meta.platforms and Platform.ANY not in meta.platforms:
            logger.debug("Skipping %s: wrong platform (%s)", meta.name, current_platform)
            continue

        instance = collector_cls()
        try:
            if await instance.probe():
                await instance.setup()
                active.append(instance)
                logger.info("Activated collector: %s (%s tier)", meta.name, meta.tier)
            else:
                logger.debug("Collector %s probed negative", meta.name)
        except Exception:
            logger.exception("Error probing/setting up %s", meta.name)

    return active
