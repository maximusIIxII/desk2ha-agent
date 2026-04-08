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
_CAP_PROP_FRAME_WIDTH = 3
_CAP_PROP_FRAME_HEIGHT = 4
_CAP_PROP_FPS = 5
_CAP_PROP_BRIGHTNESS = 10
_CAP_PROP_CONTRAST = 11
_CAP_PROP_SATURATION = 12
_CAP_PROP_HUE = 13
_CAP_PROP_GAIN = 14
_CAP_PROP_EXPOSURE = 15
_CAP_PROP_SHARPNESS = 20
_CAP_PROP_GAMMA = 22
_CAP_PROP_ZOOM = 27
_CAP_PROP_FOCUS = 28
_CAP_PROP_PAN = 33
_CAP_PROP_TILT = 34
_CAP_PROP_ROLL = 35
_CAP_PROP_BACKLIGHT = 32
_CAP_PROP_AUTOFOCUS = 39
_CAP_PROP_AUTO_EXPOSURE = 21
_CAP_PROP_AUTO_WB = 44
_CAP_PROP_WHITE_BALANCE = 45


class UVCCollector(Collector):
    """Collect UVC webcam controls via OpenCV."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="uvc",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "control"},
        description="UVC webcam brightness, contrast, white balance, FOV controls",
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
                # Resolution
                w = cap.get(_CAP_PROP_FRAME_WIDTH)
                h = cap.get(_CAP_PROP_FRAME_HEIGHT)
                if w > 0 and h > 0:
                    metrics[f"{prefix}.resolution"] = metric_value(f"{int(w)}x{int(h)}")
                fps = cap.get(_CAP_PROP_FPS)
                if fps > 0:
                    metrics[f"{prefix}.fps"] = metric_value(float(fps), unit="fps")

                # Numeric controls
                props = {
                    "brightness": (_CAP_PROP_BRIGHTNESS, None),
                    "contrast": (_CAP_PROP_CONTRAST, None),
                    "saturation": (_CAP_PROP_SATURATION, None),
                    "hue": (_CAP_PROP_HUE, None),
                    "gain": (_CAP_PROP_GAIN, None),
                    "gamma": (_CAP_PROP_GAMMA, None),
                    "white_balance": (_CAP_PROP_WHITE_BALANCE, "K"),
                    "sharpness": (_CAP_PROP_SHARPNESS, None),
                    "exposure": (_CAP_PROP_EXPOSURE, None),
                    "zoom": (_CAP_PROP_ZOOM, None),
                    "focus": (_CAP_PROP_FOCUS, None),
                    "pan": (_CAP_PROP_PAN, None),
                    "tilt": (_CAP_PROP_TILT, None),
                    "backlight_compensation": (_CAP_PROP_BACKLIGHT, None),
                }

                for name, (prop_id, unit) in props.items():
                    val = cap.get(prop_id)
                    if val >= 0:
                        metrics[f"{prefix}.{name}"] = metric_value(val, unit=unit)

                # Boolean controls
                for name, prop_id in [
                    ("autofocus", _CAP_PROP_AUTOFOCUS),
                    ("auto_wb", _CAP_PROP_AUTO_WB),
                    ("auto_exposure", _CAP_PROP_AUTO_EXPOSURE),
                ]:
                    val = cap.get(prop_id)
                    if val >= 0:
                        metrics[f"{prefix}.{name}"] = metric_value(bool(val))

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
            "webcam.set_focus": _CAP_PROP_FOCUS,
            "webcam.set_exposure": _CAP_PROP_EXPOSURE,
            "webcam.set_gain": _CAP_PROP_GAIN,
            "webcam.set_gamma": _CAP_PROP_GAMMA,
            "webcam.set_hue": _CAP_PROP_HUE,
            "webcam.set_white_balance": _CAP_PROP_WHITE_BALANCE,
            "webcam.set_pan": _CAP_PROP_PAN,
            "webcam.set_tilt": _CAP_PROP_TILT,
            "webcam.set_backlight_compensation": _CAP_PROP_BACKLIGHT,
        }

        # Boolean toggle commands
        toggle_map = {
            "webcam.set_autofocus": _CAP_PROP_AUTOFOCUS,
            "webcam.set_auto_wb": _CAP_PROP_AUTO_WB,
            "webcam.set_auto_exposure": _CAP_PROP_AUTO_EXPOSURE,
        }

        if command in toggle_map:
            value = bool(parameters.get("value", True))
            await asyncio.to_thread(self._set_prop_sync, cv2, idx, toggle_map[command], int(value))
            return {"status": "completed"}

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
