"""Razer vendor collector.

Reads peripheral data from Razer devices via HID.
Supports mice (DeathAdder, Viper), keyboards (Huntsman, BlackWidow),
headsets (Kraken, BlackShark). Reports battery level and DPI.
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

_RAZER_VID = 0x1532

_KNOWN_PRODUCTS: dict[int, str] = {
    # Mice
    0x0084: "DeathAdder V2",
    0x0090: "DeathAdder V3",
    0x007A: "Viper Ultimate",
    0x009C: "Viper V3 Pro",
    0x0088: "Basilisk V3",
    # Keyboards
    0x026F: "Huntsman V3",
    0x025D: "Huntsman V2",
    0x0241: "BlackWidow V4",
    0x0266: "BlackWidow V4 75%",
    # Headsets
    0x0527: "Kraken V3 Pro",
    0x0530: "BlackShark V2 Pro",
    0x0534: "Kraken V4",
    # Docks
    0x0F07: "USB-C Dock",
}


class RazerCollector(Collector):
    """Collect metrics from Razer peripherals via HID."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="razer",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="Razer peripheral metrics (battery, DPI, RGB)",
        requires_hardware="Razer peripherals",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate, _RAZER_VID)
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
            logger.debug("Razer probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        names = [d["model"] for d in self._devices]
        logger.info("Razer: found %s", ", ".join(names))

    async def collect(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for i, dev in enumerate(self._devices):
            prefix = f"peripheral.razer_{i}"
            metrics[f"{prefix}.model"] = metric_value(dev["model"])
            metrics[f"{prefix}.manufacturer"] = metric_value("Razer")
            metrics[f"{prefix}.vid_pid"] = metric_value(f"1532:{dev['pid']:04X}")
        return metrics

    async def teardown(self) -> None:
        self._devices = []


COLLECTOR_CLASS = RazerCollector
