"""Dell Peripheral HID Feature Reports vendor collector.

Reads extended controls from Dell wireless peripherals connected via
Dell Secure Link receivers (KB900, MS900, KM7321W) using HID Feature Reports.

Receiver VID:PID: 413c:2119 (v1), 413c:2141 (v2)
Vendor Usage Pages: 0xFF02 and 0xFF83

The receiver acts as a relay — Feature Reports are forwarded to
the active peripheral device behind the receiver.

Discovery phase required: use ``tools/hid_sniffer.py`` to map the
relay protocol and byte offsets before enabling write operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

_DELL_VID = 0x413C

# Dell Secure Link Receiver VID:PID pairs
_RECEIVER_PIDS: set[int] = {0x2119, 0x2141, 0xB091}

# Vendor usage pages for Dell peripherals
_VENDOR_USAGE_PAGES: set[int] = {0xFF02, 0xFF83}

# Auth magic bytes (hypothesis from FK-15 Feinkonzept)
_AUTH_MAGIC = bytes([0x44, 0x45, 0x4C, 0x4C])  # "DELL"

# Known peripheral types by paired slot info
_PERIPHERAL_TYPES: dict[int, str] = {
    0x01: "keyboard",
    0x02: "mouse",
    0x03: "combo",
}

# Report byte offsets (discovered via hid_sniffer, model-specific)
_KB_REPORT_MAP: dict[str, int] = {
    "backlight_level": 4,  # 0=off, 1=low, 2=medium, 3=high
    "active_slot": 5,
}

_MS_REPORT_MAP: dict[str, int] = {
    "dpi": 4,  # DPI preset index (0-3)
    "polling_rate": 5,
    "active_slot": 6,
}

_BACKLIGHT_LEVELS: dict[int, str] = {0: "off", 1: "low", 2: "medium", 3: "high"}
_BACKLIGHT_REVERSE: dict[str, int] = {"off": 0, "low": 1, "medium": 2, "high": 3}
_DPI_PRESETS: dict[int, int] = {0: 1000, 1: 1600, 2: 2400, 3: 4000}


class DellPeripheralCollector(Collector):
    """Read Dell wireless peripheral controls via HID Feature Reports."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="dell_peripheral",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "control"},
        description=("Dell Secure Link peripheral controls (KB900/MS900 backlight, DPI, battery)"),
        requires_hardware="Dell Secure Link Receiver (413c:2119/2141)",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._receivers: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate, _DELL_VID)
            self._receivers = []
            seen: set[bytes] = set()

            for dev in all_devs:
                path = dev.get("path", b"")
                if path in seen:
                    continue
                pid = dev.get("product_id", 0)
                usage_page = dev.get("usage_page", 0)

                if pid in _RECEIVER_PIDS and usage_page in _VENDOR_USAGE_PAGES:
                    self._receivers.append(dev)
                    seen.add(path)
                    logger.info(
                        "Dell Secure Link Receiver found: PID %04x, usage_page 0x%04X",
                        pid,
                        usage_page,
                    )

            return len(self._receivers) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("Dell peripheral probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        logger.info("Dell peripheral collector: %d receiver(s)", len(self._receivers))

    async def collect(self) -> dict[str, Any]:
        if not self._receivers:
            return {}
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        import hid

        metrics: dict[str, Any] = {}

        for i, recv in enumerate(self._receivers):
            prefix = f"peripheral.dell_receiver_{i}"
            metrics[f"{prefix}.manufacturer"] = metric_value("Dell")
            metrics[f"{prefix}.model"] = metric_value("Universal Receiver")
            metrics[f"{prefix}.device_type"] = metric_value("receiver")

            try:
                h = hid.device()
                h.open_path(recv["path"])

                # Try to read Feature Report from receiver
                # Report ID 0x01 — device status / paired peripherals
                report = h.get_feature_report(0x01, 64)
                if report and len(report) > 6:
                    # Parse peripheral type from report
                    periph_type_byte = report[3] if len(report) > 3 else 0
                    periph_type = _PERIPHERAL_TYPES.get(periph_type_byte, "unknown")

                    if periph_type in ("keyboard", "combo"):
                        kb_prefix = f"peripheral.dell_kb_{i}"
                        metrics[f"{kb_prefix}.manufacturer"] = metric_value("Dell")
                        metrics[f"{kb_prefix}.device_type"] = metric_value("keyboard")

                        bl_offset = _KB_REPORT_MAP.get("backlight_level")
                        if bl_offset and len(report) > bl_offset:
                            bl = report[bl_offset]
                            metrics[f"{kb_prefix}.backlight_level"] = metric_value(
                                _BACKLIGHT_LEVELS.get(bl, str(bl))
                            )

                        slot_offset = _KB_REPORT_MAP.get("active_slot")
                        if slot_offset and len(report) > slot_offset:
                            metrics[f"{kb_prefix}.active_slot"] = metric_value(
                                float(report[slot_offset])
                            )

                    if periph_type in ("mouse", "combo"):
                        ms_prefix = f"peripheral.dell_ms_{i}"
                        metrics[f"{ms_prefix}.manufacturer"] = metric_value("Dell")
                        metrics[f"{ms_prefix}.device_type"] = metric_value("mouse")

                        dpi_offset = _MS_REPORT_MAP.get("dpi")
                        if dpi_offset and len(report) > dpi_offset:
                            dpi_idx = report[dpi_offset]
                            dpi = _DPI_PRESETS.get(dpi_idx, dpi_idx * 400)
                            metrics[f"{ms_prefix}.dpi"] = metric_value(float(dpi), unit="DPI")

                    # Battery level (if available in report)
                    if len(report) > 10:
                        battery = report[10]
                        if 0 < battery <= 100:
                            target_prefix = (
                                f"peripheral.dell_kb_{i}"
                                if periph_type == "keyboard"
                                else f"peripheral.dell_ms_{i}"
                            )
                            metrics[f"{target_prefix}.battery_level"] = metric_value(
                                float(battery), unit="%"
                            )

                h.close()
            except Exception:
                logger.debug(
                    "Dell peripheral read failed for receiver %d",
                    i,
                    exc_info=True,
                )

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if command == "peripheral.set_backlight":
            return await asyncio.to_thread(self._set_backlight, target, parameters)
        if command == "peripheral.set_dpi":
            return await asyncio.to_thread(self._set_dpi, target, parameters)
        raise NotImplementedError

    def _set_backlight(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        level = str(parameters.get("level", parameters.get("value", "medium")))
        if level not in _BACKLIGHT_REVERSE:
            return {
                "status": "failed",
                "message": f"Invalid level: {level}. Options: {list(_BACKLIGHT_REVERSE)}",
            }

        if not self._receivers:
            return {"status": "failed", "message": "No receiver found"}

        recv = self._receivers[0]
        offset = _KB_REPORT_MAP.get("backlight_level")
        if offset is None:
            return {"status": "failed", "message": "Backlight not mapped"}

        try:
            h = hid.device()
            h.open_path(recv["path"])
            report = h.get_feature_report(0x01, 64)
            if not report or len(report) <= offset:
                h.close()
                return {"status": "failed", "message": "Cannot read report"}

            report_list = list(report)
            report_list[offset] = _BACKLIGHT_REVERSE[level]
            h.send_feature_report(bytes(report_list))
            time.sleep(0.1)
            h.close()
            return {"status": "completed", "level": level}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    def _set_dpi(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dpi = int(parameters.get("dpi", parameters.get("value", 1600)))
        # Find closest DPI preset
        dpi_idx = min(
            _DPI_PRESETS,
            key=lambda k: abs(_DPI_PRESETS[k] - dpi),
        )

        if not self._receivers:
            return {"status": "failed", "message": "No receiver found"}

        recv = self._receivers[0]
        offset = _MS_REPORT_MAP.get("dpi")
        if offset is None:
            return {"status": "failed", "message": "DPI not mapped"}

        try:
            h = hid.device()
            h.open_path(recv["path"])
            report = h.get_feature_report(0x01, 64)
            if not report or len(report) <= offset:
                h.close()
                return {"status": "failed", "message": "Cannot read report"}

            report_list = list(report)
            report_list[offset] = dpi_idx
            h.send_feature_report(bytes(report_list))
            time.sleep(0.1)
            h.close()
            return {"status": "completed", "dpi": _DPI_PRESETS[dpi_idx]}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    async def teardown(self) -> None:
        self._receivers.clear()


COLLECTOR_CLASS = DellPeripheralCollector
