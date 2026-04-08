"""UVC webcam control collector."""

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

# OpenCV UVC property IDs
_CAP_PROP_BRIGHTNESS = 10
_CAP_PROP_CONTRAST = 11
_CAP_PROP_SATURATION = 12
_CAP_PROP_EXPOSURE = 15
_CAP_PROP_SHARPNESS = 20
_CAP_PROP_ZOOM = 27
_CAP_PROP_AUTOFOCUS = 39
_CAP_PROP_AUTO_WB = 44
_CAP_PROP_WHITE_BALANCE = 45


class UVCCollector(Collector):
    """Collect UVC webcam controls via OpenCV."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="uvc",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral"},
        description="UVC webcam brightness, contrast, white balance controls",
        requires_software="OpenCV (opencv-python)",
        optional_dependencies=["opencv-python"],
    )

    def __init__(self) -> None:
        self._camera_indices: list[int] = []

    async def probe(self) -> bool:
        try:
            import cv2

            return await asyncio.to_thread(self._probe_sync, cv2)
        except ImportError:
            return False

    def _probe_sync(self, cv2: Any) -> bool:
        """Check for available cameras."""
        for idx in range(4):  # Check first 4 camera indices
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                self._camera_indices.append(idx)
                cap.release()
        return len(self._camera_indices) > 0

    async def setup(self) -> None:
        if self._camera_indices:
            logger.info(
                "UVC: found %d camera(s) at indices %s",
                len(self._camera_indices),
                self._camera_indices,
            )

    async def collect(self) -> dict[str, Any]:
        try:
            import cv2

            return await asyncio.to_thread(self._collect_sync, cv2)
        except ImportError:
            return {}

    def _collect_sync(self, cv2: Any) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        for idx in self._camera_indices:
            cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                continue

            prefix = f"webcam.{idx}"
            try:
                props = {
                    "brightness": (_CAP_PROP_BRIGHTNESS, None),
                    "contrast": (_CAP_PROP_CONTRAST, None),
                    "saturation": (_CAP_PROP_SATURATION, None),
                    "white_balance": (_CAP_PROP_WHITE_BALANCE, "K"),
                    "sharpness": (_CAP_PROP_SHARPNESS, None),
                    "exposure": (_CAP_PROP_EXPOSURE, None),
                    "zoom": (_CAP_PROP_ZOOM, None),
                }

                for name, (prop_id, unit) in props.items():
                    val = cap.get(prop_id)
                    if val >= 0:
                        metrics[f"{prefix}.{name}"] = metric_value(val, unit=unit)

                # Boolean controls
                autofocus = cap.get(_CAP_PROP_AUTOFOCUS)
                if autofocus >= 0:
                    metrics[f"{prefix}.autofocus"] = metric_value(bool(autofocus))
                auto_wb = cap.get(_CAP_PROP_AUTO_WB)
                if auto_wb >= 0:
                    metrics[f"{prefix}.auto_wb"] = metric_value(bool(auto_wb))

            finally:
                cap.release()

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Set UVC controls."""
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("opencv-python not installed") from exc

        idx = int(target.split(".")[-1]) if "." in target else 0

        prop_map = {
            "webcam.set_brightness": _CAP_PROP_BRIGHTNESS,
            "webcam.set_contrast": _CAP_PROP_CONTRAST,
            "webcam.set_saturation": _CAP_PROP_SATURATION,
            "webcam.set_sharpness": _CAP_PROP_SHARPNESS,
            "webcam.set_zoom": _CAP_PROP_ZOOM,
        }

        if command in prop_map:
            value = parameters.get("value", 0)
            await asyncio.to_thread(self._set_prop_sync, cv2, idx, prop_map[command], int(value))
            return {"status": "completed"}

        raise NotImplementedError(f"Unknown command: {command}")

    def _set_prop_sync(self, cv2: Any, idx: int, prop: int, value: int) -> None:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            raise RuntimeError(f"Camera {idx} not available")
        try:
            cap.set(prop, value)
        finally:
            cap.release()

    async def teardown(self) -> None:
        self._camera_indices = []


COLLECTOR_CLASS = UVCCollector
