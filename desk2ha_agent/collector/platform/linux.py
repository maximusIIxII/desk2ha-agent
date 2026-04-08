"""Linux platform collector -- sysfs/DMI for identity, thermals, battery."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
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

_DMI_PATH = Path("/sys/class/dmi/id")
_THERMAL_PATH = Path("/sys/class/thermal")
_POWER_PATH = Path("/sys/class/power_supply")
_HWMON_PATH = Path("/sys/class/hwmon")


def _read_sysfs(path: Path) -> str | None:
    """Read a sysfs file, returning None if unavailable."""
    try:
        return path.read_text().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


class LinuxPlatformCollector(Collector):
    """Collects identity, thermals, and battery from Linux sysfs/DMI."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="linux_platform",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.LINUX},
        capabilities={"presence", "inventory", "thermals", "battery"},
        description="Linux sysfs/DMI host telemetry",
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
        """Check if running on Linux."""
        return sys.platform == "linux"

    async def setup(self) -> None:
        """No-op; identity collection happens on first collect."""

    async def teardown(self) -> None:
        """No-op; no persistent resources."""

    # --- Collector implementation ---

    async def collect(self) -> dict[str, Any]:
        """Collect metrics from sysfs in a background thread."""
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        """Synchronous collection from /sys."""
        now = time.time()
        metrics: dict[str, Any] = {}

        if self._identity is None:
            self._collect_identity()

        self._collect_thermals(metrics, now)
        self._collect_battery(metrics, now)
        self._collect_psutil_metrics(metrics, now)

        return metrics

    def _collect_identity(self) -> None:
        """Read DMI identity from /sys/class/dmi/id/."""
        serial = _read_sysfs(_DMI_PATH / "product_serial")
        manufacturer = _read_sysfs(_DMI_PATH / "sys_vendor")
        model = _read_sysfs(_DMI_PATH / "product_name")
        bios_version = _read_sysfs(_DMI_PATH / "bios_version")
        chassis = _read_sysfs(_DMI_PATH / "chassis_type")

        # Read MAC addresses
        macs: list[str] = []
        try:
            result = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for mac in re.findall(r"link/ether\s+([0-9a-f:]{17})", result.stdout):
                if mac != "00:00:00:00:00:00":
                    macs.append(mac)
        except Exception:
            pass

        hostname = platform.node()

        self._identity = {
            "service_tag": serial,
            "serial_number": serial,
            "mac_addresses": macs,
            "hostname": hostname,
        }

        if serial:
            self._device_key = f"ST-{serial}"
        elif macs:
            self._device_key = f"MAC-{macs[0].replace(':', '')}"
        else:
            self._device_key = f"HOST-{hostname.lower()}"

        # Determine device type from chassis
        device_type = "unknown"
        if chassis:
            chassis_map = {
                "3": "desktop",
                "4": "desktop",
                "8": "notebook",
                "9": "notebook",
                "10": "notebook",
                "14": "notebook",
                "17": "server",
                "23": "server",
            }
            device_type = chassis_map.get(chassis, "unknown")

        self._hardware = {
            "manufacturer": manufacturer or "Unknown",
            "model": model,
            "device_type": device_type,
            "bios_version": bios_version,
            "serial_number": serial,
        }

        self._os = {
            "family": "linux",
            "version": platform.release(),
            "build": platform.version(),
            "architecture": platform.machine(),
        }

        logger.info(
            "Device identity: %s (%s) -- key=%s", model, serial, self._device_key
        )

    def _collect_thermals(
        self, metrics: dict[str, Any], now: float
    ) -> None:
        """Read thermal zones and hwmon sensors."""
        # Thermal zones
        if _THERMAL_PATH.exists():
            for zone in sorted(_THERMAL_PATH.glob("thermal_zone*")):
                temp_str = _read_sysfs(zone / "temp")
                zone_type = _read_sysfs(zone / "type") or zone.name
                if temp_str is not None:
                    try:
                        celsius = round(int(temp_str) / 1000.0, 1)
                        if 0 < celsius < 150:
                            key = zone_type.lower().replace(" ", "_")
                            metrics[key] = metric_value(celsius, unit="Cel")
                    except ValueError:
                        pass

        # hwmon sensors (coretemp, etc.)
        if _HWMON_PATH.exists():
            for hwmon in _HWMON_PATH.iterdir():
                name = _read_sysfs(hwmon / "name") or ""
                for temp_input in sorted(hwmon.glob("temp*_input")):
                    temp_str = _read_sysfs(temp_input)
                    label_file = temp_input.with_name(
                        temp_input.name.replace("_input", "_label")
                    )
                    label = _read_sysfs(label_file) or temp_input.stem
                    if temp_str is not None:
                        try:
                            celsius = round(int(temp_str) / 1000.0, 1)
                            if 0 < celsius < 150:
                                key = f"{name}_{label}".lower().replace(" ", "_")
                                metrics[key] = metric_value(celsius, unit="Cel")
                        except ValueError:
                            pass

                # Fan sensors
                for fan_input in sorted(hwmon.glob("fan*_input")):
                    fan_str = _read_sysfs(fan_input)
                    if fan_str is not None:
                        try:
                            rpm = int(fan_str)
                            idx = fan_input.stem.replace("fan", "").replace(
                                "_input", ""
                            )
                            metrics[f"fan.{idx}"] = metric_value(
                                float(rpm), unit="/min"
                            )
                        except ValueError:
                            pass

    def _collect_battery(
        self, metrics: dict[str, Any], now: float
    ) -> None:
        """Read battery info from /sys/class/power_supply/."""
        if not _POWER_PATH.exists():
            return

        for ps in _POWER_PATH.iterdir():
            ps_type = _read_sysfs(ps / "type")
            if ps_type != "Battery":
                continue

            capacity = _read_sysfs(ps / "capacity")
            if capacity is not None:
                metrics["battery.level_percent"] = metric_value(
                    float(capacity), unit="%"
                )

            status = _read_sysfs(ps / "status")
            if status is not None:
                state_map = {
                    "Charging": "charging",
                    "Discharging": "discharging",
                    "Full": "full",
                    "Not charging": "idle",
                }
                metrics["battery.state"] = metric_value(
                    state_map.get(status, status.lower())
                )

            # Cycle count
            cycles = _read_sysfs(ps / "cycle_count")
            if cycles is not None and cycles != "0":
                metrics["battery.cycle_count"] = metric_value(float(cycles))

            # Design and full charge capacity (uWh -> Wh)
            design = _read_sysfs(ps / "energy_full_design")
            if design is not None:
                metrics["battery.design_capacity_wh"] = metric_value(
                    round(int(design) / 1_000_000, 2), unit="Wh"
                )

            full = _read_sysfs(ps / "energy_full")
            if full is not None:
                metrics["battery.full_charge_capacity_wh"] = metric_value(
                    round(int(full) / 1_000_000, 2), unit="Wh"
                )

            break  # Only first battery

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


COLLECTOR_CLASS = LinuxPlatformCollector
