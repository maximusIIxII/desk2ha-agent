"""Wireless receiver detection collector.

Detects peripherals connected via proprietary wireless receivers
(Dell Universal Receiver, Logitech Bolt/Unifying, Jabra Link).
Uses HID enumeration to find receivers and their paired devices.
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

# Known wireless receiver VID:PID pairs
_RECEIVERS: dict[tuple[int, int], dict[str, str]] = {
    # Dell
    (0x413C, 0x2119): {"name": "Universal Receiver", "manufacturer": "Dell", "protocol": "rf"},
    (0x413C, 0x2141): {"name": "Universal Receiver v2", "manufacturer": "Dell", "protocol": "rf"},
    # Logitech
    (0x046D, 0xC548): {"name": "Bolt Receiver", "manufacturer": "Logitech", "protocol": "bolt"},
    (0x046D, 0xC52B): {
        "name": "Unifying Receiver",
        "manufacturer": "Logitech",
        "protocol": "unifying",
    },
    (0x046D, 0xC534): {
        "name": "Nano Receiver",
        "manufacturer": "Logitech",
        "protocol": "nano",
    },
    (0x046D, 0xC545): {
        "name": "Lightspeed Receiver",
        "manufacturer": "Logitech",
        "protocol": "lightspeed",
    },
    # Jabra
    (0x0B0E, 0x245D): {"name": "Link 380", "manufacturer": "Jabra", "protocol": "bt"},
    (0x0B0E, 0x2481): {"name": "Link 390", "manufacturer": "Jabra", "protocol": "bt"},
    # SteelSeries
    (0x1038, 0x1702): {
        "name": "Wireless Receiver",
        "manufacturer": "SteelSeries",
        "protocol": "rf",
    },
    # Corsair
    (0x1B1C, 0x1BA6): {
        "name": "Slipstream Receiver",
        "manufacturer": "Corsair",
        "protocol": "slipstream",
    },
    # Razer
    (0x1532, 0x0A56): {
        "name": "HyperSpeed Receiver",
        "manufacturer": "Razer",
        "protocol": "hyperspeed",
    },
}

# Logitech HID++ constants for device enumeration
_HIDPP_SHORT_MSG = 0x10
_HIDPP_LONG_MSG = 0x11
_HIDPP_RECEIVER_IDX = 0xFF
_HIDPP_GET_PAIRING_INFO = 0x00B5


class WirelessReceiverCollector(Collector):
    """Detect wireless receivers and their paired peripherals."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="wireless_receiver",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "inventory"},
        description="Wireless receiver detection (Dell, Logitech, Jabra, etc.)",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._receivers: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate)
            self._receivers = []

            for dev in all_devs:
                vid = dev.get("vendor_id", 0)
                pid = dev.get("product_id", 0)
                key = (vid, pid)
                if key in _RECEIVERS:
                    self._receivers.append(
                        {
                            **_RECEIVERS[key],
                            "vid": vid,
                            "pid": pid,
                            "path": dev.get("path", b""),
                            "serial": dev.get("serial_number", ""),
                        }
                    )

            # Deduplicate by VID:PID (HID can report multiple interfaces)
            seen: set[tuple[int, int]] = set()
            unique: list[dict[str, Any]] = []
            for r in self._receivers:
                key = (r["vid"], r["pid"])
                if key not in seen:
                    seen.add(key)
                    unique.append(r)
            self._receivers = unique

            return len(self._receivers) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("Wireless receiver probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        names = [r["name"] for r in self._receivers]
        logger.info("Wireless receivers: %s", ", ".join(names))

    async def collect(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        from desk2ha_agent.peripheral_db import lookup_peripheral

        metrics: dict[str, Any] = {}
        idx = 0

        for receiver in self._receivers:
            vid_pid = f"{receiver['vid']:04X}:{receiver['pid']:04X}"

            # Skip receivers marked as suppressed in peripheral_db
            spec = lookup_peripheral(vid_pid)
            if spec and spec.suppress:
                logger.debug("Suppressing receiver %s (%s)", receiver["name"], vid_pid)
                continue

            prefix = f"peripheral.receiver_{idx}"
            metrics[f"{prefix}.model"] = metric_value(receiver["name"])
            metrics[f"{prefix}.manufacturer"] = metric_value(receiver["manufacturer"])
            metrics[f"{prefix}.vid_pid"] = metric_value(vid_pid)
            metrics[f"{prefix}.protocol"] = metric_value(receiver["protocol"])
            metrics[f"{prefix}.connected"] = metric_value(True)

            if receiver["serial"]:
                metrics[f"{prefix}.serial"] = metric_value(receiver["serial"])

            # Try to enumerate paired devices for Logitech receivers
            if receiver["manufacturer"] == "Logitech":
                paired = self._enumerate_logitech_devices(receiver)
                if paired is not None:
                    metrics[f"{prefix}.paired_devices"] = metric_value(paired)

            idx += 1

        return metrics

    def _enumerate_logitech_devices(self, receiver: dict[str, Any]) -> int | None:
        """Count paired devices on a Logitech receiver via HID++."""
        try:
            import hid

            h = hid.device()
            h.open_path(receiver["path"])
            h.set_nonblocking(True)

            # HID++ short message: get receiver info
            # [report_id, device_idx, sub_id, ...]
            msg = [_HIDPP_SHORT_MSG, _HIDPP_RECEIVER_IDX, _HIDPP_GET_PAIRING_INFO, 0x00] + [
                0x00
            ] * 3
            h.write(msg)

            import time

            time.sleep(0.1)
            data = h.read(20)
            h.close()

            if data and len(data) >= 5:
                # Byte 4 typically contains paired device count
                return data[4] & 0x0F

        except Exception:
            logger.debug("HID++ enumeration failed for %s", receiver["name"])

        return None

    async def teardown(self) -> None:
        self._receivers = []


COLLECTOR_CLASS = WirelessReceiverCollector
