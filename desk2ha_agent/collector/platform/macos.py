"""macOS platform collector -- system_profiler and ioreg for host telemetry."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
import subprocess
import sys
import time
from typing import Any, ClassVar

import psutil

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)


class MacosPlatformCollector(Collector):
    """Collects identity and battery info from macOS APIs."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="macos_platform",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.MACOS},
        capabilities={"presence", "inventory", "battery"},
        description="macOS system_profiler/ioreg host telemetry",
    )

    def __init__(self) -> None:
        self._identity: dict[str, Any] | None = None
        self._hardware: dict[str, Any] | None = None
        self._os: dict[str, Any] | None = None
        self._device_key: str | None = None

    # --- DeviceInfoProvider implementation ---

    def get_identity(self) -> dict[str, Any] | None:
        return self._identity

    def get_hardware(self) -> dict[str, Any] | None:
        return self._hardware

    def get_os(self) -> dict[str, Any] | None:
        return self._os

    def get_device_key(self) -> str | None:
        return self._device_key

    # --- Collector lifecycle ---

    async def probe(self) -> bool:
        """Check if running on macOS."""
        return sys.platform == "darwin"

    async def setup(self) -> None:
        """No-op; identity collection happens on first collect."""

    async def teardown(self) -> None:
        """No-op; no persistent resources."""

    # --- Collector implementation ---

    async def collect(self) -> dict[str, Any]:
        """Collect metrics in a background thread."""
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        now = time.time()
        metrics: dict[str, Any] = {}

        if self._identity is None:
            self._collect_identity()

        self._collect_battery(metrics, now)
        self._collect_psutil_metrics(metrics, now)
        return metrics

    def _collect_identity(self) -> None:
        """Read identity from system_profiler."""
        try:
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType", "-json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = json.loads(result.stdout)
            hw = data.get("SPHardwareDataType", [{}])[0]

            serial = hw.get("serial_number")
            model = hw.get("machine_model") or hw.get("model_name")
            manufacturer = hw.get("machine_name", "Unknown")
            hostname = platform.node()

            self._identity = {
                "service_tag": serial,
                "serial_number": serial,
                "mac_addresses": [],
                "hostname": hostname,
            }

            if serial:
                self._device_key = f"ST-{serial}"
            else:
                self._device_key = f"HOST-{hostname.lower()}"

            self._hardware = {
                "manufacturer": manufacturer,
                "model": model,
                "device_type": "notebook",
                "serial_number": serial,
            }

            mac_ver = platform.mac_ver()
            self._os = {
                "family": "macos",
                "version": mac_ver[0] if mac_ver[0] else platform.release(),
                "architecture": platform.machine(),
            }

            logger.info("Device identity: %s (%s)", model, serial)

        except Exception:
            logger.warning("Failed to read system_profiler", exc_info=True)
            hostname = platform.node()
            self._identity = {
                "service_tag": None,
                "serial_number": None,
                "mac_addresses": [],
                "hostname": hostname,
            }
            self._hardware = {
                "manufacturer": "Unknown",
                "model": None,
                "device_type": "unknown",
            }
            self._os = {
                "family": "macos",
                "version": platform.release(),
                "architecture": platform.machine(),
            }
            self._device_key = f"HOST-{hostname.lower()}"

    def _collect_battery(
        self, metrics: dict[str, Any], now: float
    ) -> None:
        """Read battery from pmset / ioreg."""
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            # Parse: "InternalBattery-0 (id=...)  87%; charging; 1:23 remaining"
            match = re.search(r"(\d+)%;\s*(\w+)", result.stdout)
            if match:
                level = int(match.group(1))
                state = match.group(2).lower()

                metrics["battery.level_percent"] = metric_value(
                    float(level), unit="%"
                )
                metrics["battery.state"] = metric_value(state)

            # Check if on AC
            if "AC Power" in result.stdout:
                metrics["power.source"] = metric_value("ac")
            elif "Battery Power" in result.stdout:
                metrics["power.source"] = metric_value("battery")

        except Exception:
            logger.debug("Failed to read battery from pmset", exc_info=True)

    def _collect_psutil_metrics(
        self, metrics: dict[str, Any], now: float
    ) -> None:
        """Collect cross-platform live metrics via psutil."""
        try:
            metrics["system.cpu_usage_percent"] = metric_value(
                psutil.cpu_percent(interval=0), unit="%"
            )

            freq = psutil.cpu_freq()
            if freq is not None:
                metrics["system.cpu_frequency_mhz"] = metric_value(
                    round(freq.current, 0), unit="MHz"
                )

            vmem = psutil.virtual_memory()
            metrics["system.ram_used_gb"] = metric_value(
                round(vmem.used / 1024**3, 2), unit="GB"
            )
            metrics["system.ram_total_gb"] = metric_value(
                round(vmem.total / 1024**3, 2), unit="GB"
            )
            metrics["system.ram_usage_percent"] = metric_value(
                vmem.percent, unit="%"
            )

            swap = psutil.swap_memory()
            metrics["system.swap_usage_percent"] = metric_value(
                swap.percent, unit="%"
            )

            try:
                disk = psutil.disk_usage("/")
                metrics["system.disk_usage_percent"] = metric_value(
                    disk.percent, unit="%"
                )
                metrics["system.disk_free_gb"] = metric_value(
                    round(disk.free / 1024**3, 2), unit="GB"
                )
            except OSError:
                logger.debug("Failed to read disk usage for /")

            net = psutil.net_io_counters()
            if net is not None:
                metrics["system.net_sent_mb"] = metric_value(
                    round(net.bytes_sent / 1024**2, 2), unit="MB"
                )
                metrics["system.net_recv_mb"] = metric_value(
                    round(net.bytes_recv / 1024**2, 2), unit="MB"
                )

            metrics["system.uptime_hours"] = metric_value(
                round((time.time() - psutil.boot_time()) / 3600, 2), unit="h"
            )

            metrics["system.process_count"] = metric_value(len(psutil.pids()))

        except Exception:
            logger.exception("Failed to collect psutil system metrics")


COLLECTOR_CLASS = MacosPlatformCollector
