"""HeadsetControl collector for gaming/USB headset telemetry.

Uses the HeadsetControl CLI (https://github.com/Sapd/HeadsetControl) to read
battery level, charging status, and features from supported headsets (SteelSeries,
Corsair, Logitech, HyperX, etc.).

Requires ``headsetcontrol`` to be installed and on PATH.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)


class HeadsetControlCollector(Collector):
    """Collect headset metrics via HeadsetControl CLI."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="headsetcontrol",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="Headset battery, sidetone, and LED status via HeadsetControl CLI",
        requires_software="headsetcontrol",
    )

    def __init__(self) -> None:
        self._exe: str | None = None
        self._device_count: int = 0

    async def probe(self) -> bool:
        """Check if headsetcontrol CLI is installed and detects a headset."""
        exe = shutil.which("headsetcontrol")
        if exe is None:
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "--output", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            data = json.loads(stdout)

            devices = data.get("devices", [])
            if not devices:
                return False

            self._exe = exe
            self._device_count = len(devices)
            return True
        except (json.JSONDecodeError, asyncio.TimeoutError):
            return False
        except Exception:
            logger.debug("headsetcontrol probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        logger.info(
            "HeadsetControl: found %d device(s)", self._device_count
        )

    async def collect(self) -> dict[str, Any]:
        if self._exe is None:
            return {}

        try:
            proc = await asyncio.create_subprocess_exec(
                self._exe, "--output", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                logger.debug("headsetcontrol returned %d", proc.returncode)
                return {}

            data = json.loads(stdout)
            return self._parse_devices(data.get("devices", []))
        except asyncio.TimeoutError:
            logger.warning("headsetcontrol timed out")
            return {}
        except Exception:
            logger.debug("headsetcontrol collection failed", exc_info=True)
            return {}

    def _parse_devices(self, devices: list[dict[str, Any]]) -> dict[str, Any]:
        """Parse HeadsetControl JSON output into flat metrics."""
        metrics: dict[str, Any] = {}

        for i, dev in enumerate(devices):
            product = dev.get("product", dev.get("device", f"headset_{i}"))
            # Build a stable device key from product name
            slug = product.lower().replace(" ", "_").replace("-", "_")[:30]
            prefix = f"peripheral.headset_{slug}"

            metrics[f"{prefix}.model"] = metric_value(product)

            vendor = dev.get("vendor")
            if vendor:
                metrics[f"{prefix}.manufacturer"] = metric_value(vendor)

            # Battery
            battery = dev.get("battery")
            if battery is not None:
                status = battery.get("status", "")
                level = battery.get("level", -1)

                if isinstance(level, (int, float)) and 0 <= level <= 100:
                    metrics[f"{prefix}.battery_level"] = metric_value(
                        float(level), unit="%"
                    )

                if status:
                    metrics[f"{prefix}.charging"] = metric_value(
                        status.lower() == "charging"
                    )

            # Capabilities / features
            caps = dev.get("capabilities", {})

            sidetone = caps.get("sidetone")
            if sidetone is not None and isinstance(sidetone, (int, float)):
                metrics[f"{prefix}.sidetone"] = metric_value(
                    int(sidetone), unit="level"
                )

            led = caps.get("lights")
            if led is not None:
                metrics[f"{prefix}.led"] = metric_value(bool(led))

            chatmix = caps.get("chatmix")
            if chatmix is not None and isinstance(chatmix, (int, float)):
                metrics[f"{prefix}.chatmix"] = metric_value(int(chatmix))

            # Firmware if available
            firmware = dev.get("firmware_version")
            if firmware:
                metrics[f"{prefix}.firmware"] = metric_value(str(firmware))

        return metrics

    async def teardown(self) -> None:
        self._exe = None


COLLECTOR_CLASS = HeadsetControlCollector
