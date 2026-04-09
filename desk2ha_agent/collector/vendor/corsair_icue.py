"""Corsair iCUE vendor collector.

Reads peripheral data from Corsair devices. Uses the official iCUE SDK
(cuesdk) when available to read battery levels and device details.
Falls back to HID enumeration for basic device detection.

Requires iCUE 4.31+ to be running for SDK features.
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

# PIDs of wireless devices that may have battery
_WIRELESS_PIDS = {0x1B65, 0x1B75, 0x1B76}


class CorsairCollector(Collector):
    """Collect metrics from Corsair peripherals via iCUE SDK + HID."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="corsair_icue",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="Corsair iCUE peripheral metrics (battery, device info)",
        requires_hardware="Corsair peripherals",
        optional_dependencies=["hidapi", "cuesdk"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []
        self._sdk_available: bool = False
        self._sdk: Any = None

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
                            "wireless": pid in _WIRELESS_PIDS,
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

        # Try to connect to iCUE SDK for battery readings
        self._sdk_available = await asyncio.to_thread(self._init_sdk)
        if self._sdk_available:
            logger.info("Corsair iCUE SDK connected")
        else:
            logger.info("Corsair iCUE SDK not available, using HID-only mode")

    def _init_sdk(self) -> bool:
        """Try to initialize the Corsair iCUE SDK."""
        try:
            from cuesdk import CueSdk

            sdk = CueSdk()

            def on_state_changed(evt: Any) -> None:
                pass

            sdk.connect(on_state_changed)

            # Give SDK time to connect
            import time

            time.sleep(0.5)

            # Check if we can list devices
            devices, err = sdk.get_devices()
            if err is None and devices:
                self._sdk = sdk
                return True

            sdk.disconnect()
        except ImportError:
            logger.debug("cuesdk not installed")
        except Exception:
            logger.debug("iCUE SDK init failed", exc_info=True)
        return False

    async def collect(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        # Basic device info from HID
        for i, dev in enumerate(self._devices):
            prefix = f"peripheral.corsair_{i}"
            metrics[f"{prefix}.model"] = metric_value(dev["model"])
            metrics[f"{prefix}.manufacturer"] = metric_value("Corsair")
            metrics[f"{prefix}.vid_pid"] = metric_value(f"1B1C:{dev['pid']:04X}")

        # Battery from iCUE SDK
        if self._sdk_available and self._sdk is not None:
            battery_data = await asyncio.to_thread(self._read_batteries)
            metrics.update(battery_data)

        return metrics

    def _read_batteries(self) -> dict[str, Any]:
        """Read battery levels from iCUE SDK."""
        metrics: dict[str, Any] = {}
        try:
            from cuesdk import CorsairDevicePropertyId

            devices, err = self._sdk.get_devices()
            if err is not None or not devices:
                return metrics

            for sdk_dev in devices:
                # Match SDK device to our HID-discovered devices by model name
                sdk_model = (sdk_dev.model or "").strip()
                matched_idx = self._match_device(sdk_model)
                if matched_idx is None:
                    continue

                prefix = f"peripheral.corsair_{matched_idx}"

                # Read battery level
                try:
                    prop, err = self._sdk.get_device_property(
                        sdk_dev.id,
                        CorsairDevicePropertyId.CDPI_BatteryLevel,
                    )
                    if err is None and prop is not None:
                        metrics[f"{prefix}.battery"] = metric_value(float(prop.value), unit="%")
                except Exception:
                    logger.debug("Battery read failed for %s", sdk_model, exc_info=True)

        except Exception:
            logger.debug("iCUE battery collection failed", exc_info=True)

        return metrics

    def _match_device(self, sdk_model: str) -> int | None:
        """Match SDK device model to HID-discovered device index."""
        sdk_lower = sdk_model.lower()
        for i, dev in enumerate(self._devices):
            if dev["model"].lower() in sdk_lower or sdk_lower in dev["model"].lower():
                return i
        return None

    async def teardown(self) -> None:
        if self._sdk is not None:
            import contextlib

            with contextlib.suppress(Exception):
                self._sdk.disconnect()
            self._sdk = None
        self._sdk_available = False
        self._devices = []


COLLECTOR_CLASS = CorsairCollector
