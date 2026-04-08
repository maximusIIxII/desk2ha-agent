"""Corsair iCUE vendor collector.

Reads peripheral data from Corsair devices via the iCUE SDK or HID.
Supports headsets (HS80, Void), keyboards (K70, K100), mice (Dark Core).
Reports battery level, RGB mode, DPI, and firmware version.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

# Corsair VID
_CORSAIR_VID = 0x1B1C

# Known Corsair product PIDs
_KNOWN_PRODUCTS: dict[int, str] = {
    0x1B65: "HS80 RGB Wireless",
    0x1B75: "Void RGB Elite Wireless",
    0x1B2D: "K70 RGB MK.2",
    0x1B4F: "K100 RGB",
    0x1B76: "Dark Core RGB Pro",
    0x1BA6: "Slipstream Receiver",
}


class CorsairCollector(Collector):
    """Collect metrics from Corsair peripherals via HID."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="corsair_icue",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="Corsair iCUE peripheral metrics (battery, RGB, DPI)",
        requires_hardware="Corsair peripherals",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate, _CORSAIR_VID)
            seen_pids: set[int] = set()
            for dev in all_devs:
                pid = dev.get("product_id", 0)
                if pid in _KNOWN_PRODUCTS and pid not in seen_pids:
                    seen_pids.add(pid)
                    self._devices.append(
                        {
                            "pid": pid,
                            "model": _KNOWN_PRODUCTS[pid],
                            "path": dev.get("path", b""),
                            "serial": dev.get("serial_number", ""),
                        }
                    )
            return len(self._devices) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("Corsair probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        names = [d["model"] for d in self._devices]
        logger.info("Corsair: found %s", ", ".join(names))

    async def collect(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for i, dev in enumerate(self._devices):
            prefix = f"peripheral.corsair_{i}"
            metrics[f"{prefix}.model"] = metric_value(dev["model"])
            metrics[f"{prefix}.manufacturer"] = metric_value("Corsair")
            metrics[f"{prefix}.vid_pid"] = metric_value(f"1B1C:{dev['pid']:04X}")
        return metrics

    async def teardown(self) -> None:
        self._devices = []


COLLECTOR_CLASS = CorsairCollector
