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
                exe,
                "--output",
                "json",
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
        except (TimeoutError, json.JSONDecodeError):
            return False
        except Exception:
            logger.debug("headsetcontrol probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        logger.info("HeadsetControl: found %d device(s)", self._device_count)

    async def collect(self) -> dict[str, Any]:
        if self._exe is None:
            return {}

        try:
            proc = await asyncio.create_subprocess_exec(
                self._exe,
                "--output",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode != 0:
                logger.debug("headsetcontrol returned %d", proc.returncode)
                return {}

            data = json.loads(stdout)
            return self._parse_devices(data.get("devices", []))
        except TimeoutError:
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

            # Prefer VID:PID for stable, roaming-capable device key
            id_vendor = dev.get("id_vendor", "")
            id_product = dev.get("id_product", "")
            if id_vendor and id_product:
                vid_pid = f"{id_vendor.lower()}_{id_product.lower()}"
                prefix = f"peripheral.headset_{vid_pid}"
                global_id = f"usb:{id_vendor.upper()}:{id_product.upper()}"
            else:
                # Fallback to product name slug (not roaming-capable)
                slug = product.lower().replace(" ", "_").replace("-", "_")[:30]
                prefix = f"peripheral.headset_{slug}"
                global_id = None

            metrics[f"{prefix}.model"] = metric_value(product)

            vendor = dev.get("vendor")
            if vendor:
                metrics[f"{prefix}.manufacturer"] = metric_value(vendor)

            # Multi-host tracking
            metrics[f"{prefix}.global_id"] = metric_value(global_id)
            if self.host_device_key:
                metrics[f"{prefix}.connected_host"] = metric_value(self.host_device_key)

            # Battery
            battery = dev.get("battery")
            if battery is not None:
                status = battery.get("status", "")
                level = battery.get("level", -1)

                if isinstance(level, int | float) and 0 <= level <= 100:
                    metrics[f"{prefix}.battery_level"] = metric_value(float(level), unit="%")

                if status:
                    metrics[f"{prefix}.charging"] = metric_value(status.lower() == "charging")

            # Capabilities / features
            caps = dev.get("capabilities", {})

            sidetone = caps.get("sidetone")
            if sidetone is not None and isinstance(sidetone, int | float):
                metrics[f"{prefix}.sidetone"] = metric_value(int(sidetone), unit="level")

            led = caps.get("lights")
            if led is not None:
                metrics[f"{prefix}.led"] = metric_value(bool(led))

            chatmix = caps.get("chatmix")
            if chatmix is not None and isinstance(chatmix, int | float):
                metrics[f"{prefix}.chatmix"] = metric_value(int(chatmix))

            # Equalizer preset if available
            eq_preset = caps.get("equalizer_preset")
            if eq_preset is not None:
                metrics[f"{prefix}.equalizer_preset"] = metric_value(str(eq_preset))

            # Inactive timeout if available
            inactive = caps.get("inactive_time")
            if inactive is not None and isinstance(inactive, int | float):
                metrics[f"{prefix}.inactive_timeout"] = metric_value(int(inactive))

            # Voice prompts
            voice_prompts = caps.get("voice_prompts")
            if voice_prompts is not None:
                metrics[f"{prefix}.voice_prompts"] = metric_value(bool(voice_prompts))

            # Firmware if available
            firmware = dev.get("firmware_version")
            if firmware:
                metrics[f"{prefix}.firmware"] = metric_value(str(firmware))

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute headset control commands via CLI."""
        if self._exe is None:
            raise RuntimeError("headsetcontrol not available")

        if command == "headset.set_sidetone":
            value = int(parameters["value"])
            if not 0 <= value <= 128:
                raise ValueError(f"Sidetone must be 0-128, got {value}")
            await self._run_cli("-s", str(value))
            return {"status": "completed"}

        if command == "headset.set_led":
            on = parameters.get("value", parameters.get("enabled", True))
            await self._run_cli("-l", "1" if on else "0")
            return {"status": "completed"}

        if command == "headset.set_chatmix":
            value = int(parameters["value"])
            if not 0 <= value <= 128:
                raise ValueError(f"Chatmix must be 0-128, got {value}")
            await self._run_cli("-m", str(value))
            return {"status": "completed"}

        if command == "headset.set_inactive_timeout":
            value = int(parameters["value"])
            if not 0 <= value <= 90:
                raise ValueError(f"Inactive timeout must be 0-90, got {value}")
            await self._run_cli("-i", str(value))
            return {"status": "completed"}

        if command == "headset.set_equalizer_preset":
            preset = str(parameters.get("preset", parameters.get("value", "0")))
            await self._run_cli("-p", preset)
            return {"status": "completed"}

        if command == "headset.set_voice_prompts":
            on = parameters.get("value", parameters.get("enabled", True))
            await self._run_cli("--voice-prompt", "1" if on else "0")
            return {"status": "completed"}

        raise NotImplementedError(f"Unknown command: {command}")

    async def _run_cli(self, *args: str) -> None:
        """Run headsetcontrol with arguments."""
        proc = await asyncio.create_subprocess_exec(
            self._exe,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(
                f"headsetcontrol {' '.join(args)} failed (rc={proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )

    async def teardown(self) -> None:
        self._exe = None


COLLECTOR_CLASS = HeadsetControlCollector
