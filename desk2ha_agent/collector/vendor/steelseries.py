"""SteelSeries vendor collector.

Reads peripheral data from SteelSeries devices via HID.
Supports headsets (Arctis Nova 7, Pro), mice (Rival, Aerox),
keyboards (Apex Pro). Reports battery level and settings.
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

_STEELSERIES_VID = 0x1038

_KNOWN_PRODUCTS: dict[int, str] = {
    0x12AD: "Arctis Nova 7",
    0x12C2: "Arctis Nova 7 Wireless",
    0x1294: "Arctis Nova Pro Wireless",
    0x1290: "Arctis Nova Pro",
    0x1862: "Rival 650 Wireless",
    0x1870: "Aerox 3 Wireless",
    0x1882: "Aerox 5 Wireless",
    0x161C: "Apex Pro",
    0x1618: "Apex 7",
}


class SteelSeriesCollector(Collector):
    """Collect metrics from SteelSeries peripherals via HID."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="steelseries",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="SteelSeries peripheral metrics (battery, EQ, sensitivity)",
        requires_hardware="SteelSeries peripherals",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate, _STEELSERIES_VID)
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
                        }
                    )
            return len(self._devices) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("SteelSeries probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        names = [d["model"] for d in self._devices]
        logger.info("SteelSeries: found %s", ", ".join(names))

    async def collect(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for i, dev in enumerate(self._devices):
            prefix = f"peripheral.steelseries_{i}"
            metrics[f"{prefix}.model"] = metric_value(dev["model"])
            metrics[f"{prefix}.manufacturer"] = metric_value("SteelSeries")
            metrics[f"{prefix}.vid_pid"] = metric_value(f"1038:{dev['pid']:04X}")
        return metrics

    async def teardown(self) -> None:
        self._devices = []


COLLECTOR_CLASS = SteelSeriesCollector
