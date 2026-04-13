"""USB HID battery collector for wired/wireless peripherals."""

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

# Known HID usage pages for battery reporting
_USAGE_PAGE_POWER_DEVICE = 0x0084  # USB HID Power Device Page
_USAGE_PAGE_BATTERY = 0x0085  # USB HID Battery System Page


class HIDBatteryCollector(Collector):
    """Read battery levels from USB HID peripherals."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="hid_battery",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="USB HID battery level for keyboards, mice, headsets",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            devices = await asyncio.to_thread(hid.enumerate)
            # Filter for devices with battery/power usage pages
            self._devices = [
                d
                for d in devices
                if d.get("usage_page") in (_USAGE_PAGE_POWER_DEVICE, _USAGE_PAGE_BATTERY)
            ]
            return len(self._devices) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("HID enumeration failed", exc_info=True)
            return False

    async def setup(self) -> None:
        if self._devices:
            logger.info(
                "HID battery: found %d device(s) with battery reporting",
                len(self._devices),
            )

    async def collect(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        import hid

        metrics: dict[str, Any] = {}

        # Re-enumerate to catch new/removed devices
        try:
            all_devices = hid.enumerate()
            battery_devices = [
                d
                for d in all_devices
                if d.get("usage_page") in (_USAGE_PAGE_POWER_DEVICE, _USAGE_PAGE_BATTERY)
            ]
        except Exception:
            logger.debug("HID re-enumeration failed", exc_info=True)
            battery_devices = self._devices

        for dev_info in battery_devices:
            vid = dev_info.get("vendor_id", 0)
            pid = dev_info.get("product_id", 0)
            serial = dev_info.get("serial_number", "") or ""
            product = dev_info.get("product_string", "") or "Unknown"
            manufacturer = dev_info.get("manufacturer_string", "") or "Unknown"

            device_key = f"USB-{vid:04X}_{pid:04X}"
            if serial:
                device_key += f"_{serial[:8]}"

            try:
                h = hid.device()
                h.open_path(dev_info["path"])
                h.set_nonblocking(True)

                # Try to read battery level via feature report
                # Many devices use report ID 0x20 for battery
                for report_id in (0x20, 0x01, 0x00):
                    try:
                        data = h.get_feature_report(report_id, 64)
                        if data and len(data) > 1:
                            # Battery level is often the first byte after report ID
                            level = data[1] if len(data) > 1 else data[0]
                            if 0 <= level <= 100:
                                prefix = f"peripheral.{device_key}"
                                metrics[f"{prefix}.battery_level"] = metric_value(
                                    float(level), unit="%"
                                )
                                metrics[f"{prefix}.model"] = metric_value(product)
                                metrics[f"{prefix}.manufacturer"] = metric_value(manufacturer)

                                # Multi-host tracking
                                if serial:
                                    metrics[f"{prefix}.global_id"] = metric_value(
                                        f"usb:{vid:04X}:{pid:04X}:{serial}"
                                    )
                                else:
                                    metrics[f"{prefix}.global_id"] = metric_value(None)
                                if self.host_device_key:
                                    metrics[f"{prefix}.connected_host"] = metric_value(
                                        self.host_device_key
                                    )
                                break
                    except Exception:
                        continue

                h.close()
            except Exception:
                logger.debug(
                    "Failed to read HID battery from %s",
                    device_key,
                    exc_info=True,
                )

        return metrics

    async def teardown(self) -> None:
        self._devices = []


COLLECTOR_CLASS = HIDBatteryCollector
