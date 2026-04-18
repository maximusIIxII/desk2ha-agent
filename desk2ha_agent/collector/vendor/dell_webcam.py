"""Dell Webcam Extension Units vendor collector.

Reads extended controls from Dell business webcams (WB7022, WB5023, etc.)
via HID Feature Reports on the vendor usage page 0xFF83.

Controls: HDR, AI Auto-Framing, Field of View, Noise Reduction,
Digital Zoom, Background Blur, Presence Detection.

Discovery phase required: use ``tools/hid_sniffer.py`` to map byte offsets
for each webcam model before enabling write operations.
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

# Dell webcam VID:PID pairs (vendor usage page 0xFF83)
_DELL_WEBCAM_PIDS: dict[tuple[int, int], str] = {
    (0x413C, 0xC015): "Dell WB7022 4K",
    (0x413C, 0xB0A6): "Dell WB7022 4K",
    (0x413C, 0xD001): "Dell WB7022 4K",  # Presence sensor companion (same physical device)
}

_DELL_VID = 0x413C
_VENDOR_USAGE_PAGE = 0xFF83

# Known HID Feature Report byte offsets (discovered via hid_sniffer)
# These are model-specific and may need adjustment per firmware version
_REPORT_MAP: dict[str, dict[str, int]] = {
    "wb7022": {
        "hdr": 4,
        "auto_framing": 5,
        "fov": 6,  # 0=65, 1=78, 2=90
        "noise_reduction": 7,
        "digital_zoom": 8,  # 10-40 (1.0x-4.0x)
    },
}

_FOV_MAP: dict[int, str] = {0: "65", 1: "78", 2: "90"}
_FOV_REVERSE: dict[str, int] = {"65": 0, "78": 1, "90": 2}


class DellWebcamCollector(Collector):
    """Read extended webcam controls via HID Feature Reports."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="dell_webcam",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "control"},
        description="Dell webcam Extension Units (HDR, AI framing, FoV, zoom)",
        requires_hardware="Dell WB7022/WB5023 webcam",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate, _DELL_VID)
            self._devices = []
            seen: set[bytes] = set()

            for dev in all_devs:
                path = dev.get("path", b"")
                if path in seen:
                    continue
                vid = dev.get("vendor_id", 0)
                pid = dev.get("product_id", 0)
                usage_page = dev.get("usage_page", 0)

                if (vid, pid) in _DELL_WEBCAM_PIDS and usage_page == _VENDOR_USAGE_PAGE:
                    self._devices.append(dev)
                    seen.add(path)
                    logger.info(
                        "Dell webcam found: %s (VID:PID %04x:%04x)",
                        _DELL_WEBCAM_PIDS[(vid, pid)],
                        vid,
                        pid,
                    )

            return len(self._devices) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("Dell webcam probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        logger.info("Dell webcam collector: %d device(s)", len(self._devices))

    async def collect(self) -> dict[str, Any]:
        if not self._devices:
            return {}
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        import hid

        metrics: dict[str, Any] = {}

        for i, dev_info in enumerate(self._devices):
            vid = dev_info.get("vendor_id", 0)
            pid = dev_info.get("product_id", 0)
            model_name = _DELL_WEBCAM_PIDS.get((vid, pid), "Dell Webcam")
            prefix = f"webcam.{i}"

            metrics[f"{prefix}.model"] = metric_value(model_name)
            metrics[f"{prefix}.manufacturer"] = metric_value("Dell")

            # Determine report map for this model
            model_key = "wb7022" if "7022" in model_name else None
            if model_key is None:
                continue

            report_map = _REPORT_MAP.get(model_key, {})
            if not report_map:
                continue

            try:
                h = hid.device()
                h.open_path(dev_info["path"])

                # Read Feature Report (report ID 0x01)
                report = h.get_feature_report(0x01, 64)
                if report and len(report) > 8:
                    # HDR
                    if "hdr" in report_map:
                        hdr_byte = report[report_map["hdr"]]
                        metrics[f"{prefix}.hdr"] = metric_value(bool(hdr_byte))

                    # AI Auto-Framing
                    if "auto_framing" in report_map:
                        af_byte = report[report_map["auto_framing"]]
                        metrics[f"{prefix}.auto_framing"] = metric_value(bool(af_byte))

                    # Field of View
                    if "fov" in report_map:
                        fov_byte = report[report_map["fov"]]
                        fov_str = _FOV_MAP.get(fov_byte, str(fov_byte))
                        metrics[f"{prefix}.fov"] = metric_value(fov_str)

                    # Noise Reduction
                    if "noise_reduction" in report_map:
                        nr_byte = report[report_map["noise_reduction"]]
                        metrics[f"{prefix}.noise_reduction"] = metric_value(bool(nr_byte))

                    # Digital Zoom (1.0x - 4.0x)
                    if "digital_zoom" in report_map:
                        zoom_byte = report[report_map["digital_zoom"]]
                        zoom = round(float(zoom_byte) / 10.0, 1)
                        metrics[f"{prefix}.digital_zoom"] = metric_value(zoom)

                h.close()
            except Exception:
                logger.debug("Dell webcam read failed for %s", model_name, exc_info=True)

            # Multi-host tracking (uppercase hex to match USB collector format)
            serial = dev_info.get("serial_number", "")
            if serial:
                metrics[f"{prefix}.global_id"] = metric_value(f"usb:{vid:04X}:{pid:04X}:{serial}")
            else:
                # VID:PID-only fallback for deduplication
                metrics[f"{prefix}.global_id"] = metric_value(f"usb:{vid:04X}:{pid:04X}")

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if command == "webcam.set_hdr":
            return await asyncio.to_thread(self._set_feature_bool, target, "hdr", parameters)
        if command == "webcam.set_auto_framing":
            return await asyncio.to_thread(
                self._set_feature_bool, target, "auto_framing", parameters
            )
        if command == "webcam.set_fov":
            return await asyncio.to_thread(self._set_fov, target, parameters)
        if command == "webcam.set_noise_reduction":
            return await asyncio.to_thread(
                self._set_feature_bool, target, "noise_reduction", parameters
            )
        if command == "webcam.set_digital_zoom":
            return await asyncio.to_thread(self._set_digital_zoom, target, parameters)
        raise NotImplementedError

    def _find_device(self, target: str) -> tuple[dict[str, Any] | None, str | None]:
        """Find device by target prefix (e.g. 'webcam.0')."""
        for i, dev in enumerate(self._devices):
            if target == f"webcam.{i}":
                vid = dev.get("vendor_id", 0)
                pid = dev.get("product_id", 0)
                name = _DELL_WEBCAM_PIDS.get((vid, pid), "")
                model_key = "wb7022" if "7022" in name else None
                return dev, model_key
        return None, None

    def _set_feature_bool(
        self, target: str, feature: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        import hid

        dev, model_key = self._find_device(target)
        if dev is None or model_key is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        report_map = _REPORT_MAP.get(model_key, {})
        offset = report_map.get(feature)
        if offset is None:
            return {"status": "failed", "message": f"Feature not mapped: {feature}"}

        enabled = bool(parameters.get("enabled", parameters.get("value", True)))

        try:
            h = hid.device()
            h.open_path(dev["path"])

            report = h.get_feature_report(0x01, 64)
            if not report or len(report) <= offset:
                h.close()
                return {"status": "failed", "message": "Cannot read feature report"}

            report_list = list(report)
            report_list[offset] = 1 if enabled else 0
            h.send_feature_report(bytes(report_list))
            time.sleep(0.1)
            h.close()
            return {"status": "completed", feature: enabled}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    def _set_fov(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dev, model_key = self._find_device(target)
        if dev is None or model_key is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        fov = str(parameters.get("fov", parameters.get("value", "78")))
        if fov not in _FOV_REVERSE:
            return {
                "status": "failed",
                "message": f"Invalid FoV: {fov}. Options: {list(_FOV_REVERSE)}",
            }

        report_map = _REPORT_MAP.get(model_key, {})
        offset = report_map.get("fov")
        if offset is None:
            return {"status": "failed", "message": "FoV not mapped"}

        try:
            h = hid.device()
            h.open_path(dev["path"])
            report = h.get_feature_report(0x01, 64)
            if not report or len(report) <= offset:
                h.close()
                return {"status": "failed", "message": "Cannot read feature report"}

            report_list = list(report)
            report_list[offset] = _FOV_REVERSE[fov]
            h.send_feature_report(bytes(report_list))
            time.sleep(0.1)
            h.close()
            return {"status": "completed", "fov": fov}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    def _set_digital_zoom(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dev, model_key = self._find_device(target)
        if dev is None or model_key is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        zoom = float(parameters.get("zoom", parameters.get("value", 1.0)))
        if zoom < 1.0 or zoom > 4.0:
            return {"status": "failed", "message": "Zoom must be 1.0-4.0"}

        report_map = _REPORT_MAP.get(model_key, {})
        offset = report_map.get("digital_zoom")
        if offset is None:
            return {"status": "failed", "message": "Digital zoom not mapped"}

        try:
            h = hid.device()
            h.open_path(dev["path"])
            report = h.get_feature_report(0x01, 64)
            if not report or len(report) <= offset:
                h.close()
                return {"status": "failed", "message": "Cannot read feature report"}

            report_list = list(report)
            report_list[offset] = int(zoom * 10)
            h.send_feature_report(bytes(report_list))
            time.sleep(0.1)
            h.close()
            return {"status": "completed", "zoom": zoom}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    async def teardown(self) -> None:
        self._devices.clear()


COLLECTOR_CLASS = DellWebcamCollector
