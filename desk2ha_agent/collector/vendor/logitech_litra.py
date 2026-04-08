"""Logitech Litra Glow/Beam vendor collector.

Controls and reads Logitech Litra desk lamps via USB HID.
Supports power on/off, brightness (20-250 lumen), and color
temperature (2700-6500K).

Protocol reference: github.com/timrogers/litra-rs
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

# Logitech Litra HID identifiers
_LITRA_VIDS_PIDS: list[tuple[int, int]] = [
    (0x046D, 0xC900),  # Litra Glow
    (0x046D, 0xC901),  # Litra Beam
    (0x046D, 0xC903),  # Litra Beam LX
]
_USAGE_PAGE = 0xFF43  # Logitech vendor-specific

# HID report structure: 20 bytes, report ID 0x11
_REPORT_ID = 0x11
_HEADER = [0x11, 0xFF, 0x04]

# Command opcodes
_CMD_POWER_SET = 0x1C
_CMD_POWER_GET = 0x01
_CMD_BRIGHTNESS_SET = 0x4C
_CMD_BRIGHTNESS_GET = 0x31
_CMD_COLOR_TEMP_SET = 0x9C
_CMD_COLOR_TEMP_GET = 0x81

_BRIGHTNESS_MIN = 20
_BRIGHTNESS_MAX = 250
_COLOR_TEMP_MIN = 2700
_COLOR_TEMP_MAX = 6500


def _build_report(cmd: int, p0: int = 0, p1: int = 0) -> list[int]:
    """Build a 20-byte HID output report."""
    return [*_HEADER, cmd, p0, p1] + [0x00] * 14


def _uint16_be(value: int) -> tuple[int, int]:
    """Convert int to big-endian uint16 bytes."""
    return (value >> 8) & 0xFF, value & 0xFF


class LogitechLitraCollector(Collector):
    """Control and read Logitech Litra desk lamps."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="logitech_litra",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "control"},
        description="Logitech Litra Glow/Beam brightness and color temp",
        requires_hardware="Logitech Litra Glow/Beam",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate)
            self._devices = []
            for vid, pid in _LITRA_VIDS_PIDS:
                for dev in all_devs:
                    if (
                        dev.get("vendor_id") == vid
                        and dev.get("product_id") == pid
                        and dev.get("usage_page") == _USAGE_PAGE
                    ):
                        self._devices.append(dev)
                        break  # One per VID/PID pair

            return len(self._devices) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("Litra probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        logger.info(
            "Logitech Litra: found %d device(s)",
            len(self._devices),
        )

    async def collect(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        import hid

        metrics: dict[str, Any] = {}

        for i, dev_info in enumerate(self._devices):
            prefix = f"peripheral.litra_{i}"
            product = dev_info.get("product_string", "Litra")

            metrics[f"{prefix}.model"] = metric_value(product)
            metrics[f"{prefix}.manufacturer"] = metric_value("Logitech")

            try:
                h = hid.device()
                h.open_path(dev_info["path"])
                h.set_nonblocking(True)

                # Read power state
                power = self._read_value(h, _CMD_POWER_GET)
                if power is not None:
                    is_on = power > 0
                    metrics[f"{prefix}.power"] = metric_value(is_on)

                # Read brightness
                brightness = self._read_value(h, _CMD_BRIGHTNESS_GET)
                if brightness is not None:
                    metrics[f"{prefix}.brightness_lumen"] = metric_value(
                        float(brightness), unit="lm"
                    )
                    # Also as percentage
                    pct = round(
                        (brightness - _BRIGHTNESS_MIN) / (_BRIGHTNESS_MAX - _BRIGHTNESS_MIN) * 100
                    )
                    metrics[f"{prefix}.brightness_percent"] = metric_value(
                        float(max(0, min(100, pct))), unit="%"
                    )

                # Read color temperature
                color_temp = self._read_value(h, _CMD_COLOR_TEMP_GET)
                if color_temp is not None:
                    metrics[f"{prefix}.color_temp"] = metric_value(float(color_temp), unit="K")

                h.close()
            except Exception:
                logger.debug("Failed to read Litra %d", i, exc_info=True)

        return metrics

    def _read_value(self, h: Any, cmd: int) -> int | None:
        """Send a GET command and read the uint16 response."""
        try:
            report = _build_report(cmd)
            h.write(report)

            # Read response (may need a few attempts)
            for _ in range(10):
                data = h.read(20)
                if data and len(data) >= 6 and data[3] == cmd:
                    return (data[4] << 8) | data[5]
            return None
        except Exception:
            return None

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if not command.startswith("litra."):
            raise NotImplementedError

        return await asyncio.to_thread(self._execute_sync, command, target, parameters)

    def _execute_sync(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        import hid

        # Find device index from target (e.g. "peripheral.litra_0")
        idx = 0
        if target:
            parts = target.rsplit("_", 1)
            if len(parts) == 2 and parts[-1].isdigit():
                idx = int(parts[-1])

        if idx >= len(self._devices):
            return {"status": "failed", "message": f"Litra {idx} not found"}

        try:
            h = hid.device()
            h.open_path(self._devices[idx]["path"])

            if command == "litra.set_power":
                on = bool(parameters.get("value", parameters.get("on", True)))
                h.write(_build_report(_CMD_POWER_SET, 0x01 if on else 0x00))

            elif command == "litra.set_brightness":
                lumen = int(parameters.get("value", parameters.get("lumen", 100)))
                lumen = max(_BRIGHTNESS_MIN, min(_BRIGHTNESS_MAX, lumen))
                hi, lo = _uint16_be(lumen)
                h.write(_build_report(_CMD_BRIGHTNESS_SET, hi, lo))

            elif command == "litra.set_color_temp":
                kelvin = int(parameters.get("value", parameters.get("kelvin", 4000)))
                kelvin = max(_COLOR_TEMP_MIN, min(_COLOR_TEMP_MAX, kelvin))
                # Round to nearest 100
                kelvin = round(kelvin / 100) * 100
                hi, lo = _uint16_be(kelvin)
                h.write(_build_report(_CMD_COLOR_TEMP_SET, hi, lo))

            else:
                h.close()
                raise NotImplementedError(f"Unknown litra command: {command}")

            h.close()
            return {"status": "completed"}

        except NotImplementedError:
            raise
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    async def teardown(self) -> None:
        self._devices = []


COLLECTOR_CLASS = LogitechLitraCollector
