"""Windows platform collector -- WMI queries for identity, battery, OS info, system metrics."""

from __future__ import annotations

import asyncio
import logging
import platform
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

# Prime psutil.cpu_percent so subsequent non-blocking calls return valid data.
psutil.cpu_percent(interval=None)


def _safe_wmi_import() -> bool:
    """Check if WMI is available (Windows only)."""
    try:
        import wmi  # noqa: F401

        return True
    except ImportError:
        return False


class WindowsPlatformCollector(Collector):
    """Collects identity, battery, thermals, and system metrics on Windows."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="windows_platform",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.WINDOWS},
        capabilities={"presence", "inventory", "battery", "thermals"},
        description="Windows WMI/psutil host telemetry",
        requires_software=None,
    )

    def __init__(self) -> None:
        self._identity: dict[str, Any] | None = None
        self._hardware: dict[str, Any] | None = None
        self._os: dict[str, Any] | None = None
        self._device_key: str | None = None
        self._thermal_fallback_warned: bool = False
        # Cached WMI static info (collected once, republished every cycle)
        self._wmi_static_collected: bool = False
        self._wmi_static: dict[str, dict[str, Any]] = {}

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
        """Check if running on Windows."""
        return sys.platform == "win32"

    async def setup(self) -> None:
        """No-op; identity collection happens on first collect."""

    async def teardown(self) -> None:
        """No-op; no persistent resources."""

    # --- Collector implementation ---

    async def collect(self) -> dict[str, Any]:
        """Collect metrics via WMI in a background thread, with psutil fallback."""
        if not _safe_wmi_import():
            logger.debug("WMI not available -- collecting psutil metrics only")
            now = time.time()
            metrics: dict[str, Any] = {}
            self._collect_psutil_metrics(metrics, now)
            return metrics
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        """Synchronous WMI collection -- runs in a thread."""
        import pythoncom  # type: ignore[import-untyped]
        import wmi  # type: ignore[import-untyped]

        pythoncom.CoInitialize()
        try:
            conn = wmi.WMI()
            now = time.time()
            metrics: dict[str, Any] = {}

            # --- Identity (cached after first successful query) ---
            if self._identity is None:
                self._collect_identity(conn)

            # --- Battery ---
            self._collect_battery(conn, metrics, now)

            # --- Lid state (notebooks) ---
            self._collect_lid_state(metrics)

            # --- Thermals fallback (standard WMI, no vendor tool needed) ---
            self._collect_thermals_fallback(metrics, now)

            # --- System metrics (psutil live + WMI static) ---
            self._collect_system_metrics(conn, metrics, now)

            return metrics
        except Exception:
            logger.exception("windows_platform WMI collection failed")
            return {}
        finally:
            pythoncom.CoUninitialize()

    def _collect_identity(self, conn: object) -> None:
        """Query Win32_ComputerSystem, Win32_BIOS, Win32_OperatingSystem."""
        try:
            # Computer system
            cs_list = conn.Win32_ComputerSystem()  # type: ignore[attr-defined]
            cs = cs_list[0] if cs_list else None

            # BIOS (service tag / serial)
            bios_list = conn.Win32_BIOS()  # type: ignore[attr-defined]
            bios = bios_list[0] if bios_list else None

            # OS
            os_list = conn.Win32_OperatingSystem()  # type: ignore[attr-defined]
            os_obj = os_list[0] if os_list else None

            # Network adapters for MAC addresses
            adapters = conn.Win32_NetworkAdapterConfiguration(IPEnabled=True)  # type: ignore[attr-defined]
            macs = [a.MACAddress.lower().replace("-", ":") for a in adapters if a.MACAddress]

            serial = bios.SerialNumber if bios else None
            hostname = platform.node()

            self._identity = {
                "service_tag": serial,
                "serial_number": serial,
                "mac_addresses": macs or [],
                "hostname": hostname,
            }

            # Device key: prefer serial, then MAC, then hostname
            if serial:
                self._device_key = f"ST-{serial}"
            elif macs:
                primary_mac = macs[0].replace(":", "")
                self._device_key = f"MAC-{primary_mac}"
            else:
                slug = hostname.lower().replace(" ", "_")
                self._device_key = f"HOST-{slug}"

            # Determine device type from chassis
            device_type = "unknown"
            if cs:
                chassis_types = getattr(cs, "PCSystemType", None)
                if chassis_types == 2:
                    device_type = "notebook"
                elif chassis_types == 1:
                    device_type = "desktop"
                elif chassis_types == 4:
                    device_type = "server"
                elif chassis_types == 8:
                    device_type = "workstation"

            self._hardware = {
                "manufacturer": cs.Manufacturer if cs else "Unknown",
                "model": cs.Model if cs else None,
                "device_type": device_type,
                "bios_version": bios.SMBIOSBIOSVersion if bios else None,
                "serial_number": serial,
            }

            self._os = {
                "family": "windows",
                "version": os_obj.Version if os_obj else None,
                "build": os_obj.BuildNumber if os_obj else None,
                "architecture": platform.machine(),
            }

            logger.info(
                "Device identity: %s (%s) -- key=%s",
                self._hardware.get("model"),
                serial,
                self._device_key,
            )

        except Exception:
            logger.exception("Failed to collect device identity")

    def _collect_battery(self, conn: object, metrics: dict[str, Any], now: float) -> None:
        """Query Win32_Battery for battery metrics."""
        try:
            batteries = conn.Win32_Battery()  # type: ignore[attr-defined]
            if not batteries:
                return

            bat = batteries[0]

            # Battery level
            level = getattr(bat, "EstimatedChargeRemaining", None)
            if level is not None:
                metrics["battery.level_percent"] = metric_value(float(level), unit="%")

            # Battery status mapping
            status_map = {
                1: "discharging",
                2: "ac",
                3: "full",
                4: "low",
                5: "critical",
                6: "charging",
                7: "charging",
                8: "charging",
                9: "charging",
            }
            status_code = getattr(bat, "BatteryStatus", None)
            if status_code is not None:
                state = status_map.get(int(status_code), "unknown")
                metrics["battery.state"] = metric_value(state)

            # Estimated runtime
            runtime = getattr(bat, "EstimatedRunTime", None)
            if runtime is not None and int(runtime) != 71582788:
                metrics["battery.time_remaining_seconds"] = metric_value(
                    float(int(runtime) * 60), unit="s"
                )

        except Exception:
            logger.exception("Failed to collect battery metrics")

    def _collect_lid_state(self, metrics: dict[str, Any]) -> None:
        """Detect laptop lid open/closed state.

        Windows: Uses CallNtPowerInformation(SystemPowerCapabilities) to check
        if lid is present, then reads ACPI lid state via WMI.
        """
        if not self._hardware or self._hardware.get("device_type") != "notebook":
            return

        try:
            import ctypes
            import ctypes.wintypes

            # Check if lid hardware is present via PowrProf.dll
            # SystemPowerCapabilities = 4, struct is 84 bytes
            buf = ctypes.create_string_buffer(84)
            result = ctypes.windll.powrprof.CallNtPowerInformation(
                4,  # SystemPowerCapabilities
                None,
                0,
                buf,
                84,
            )
            if result != 0:
                return
            # Byte offset 2 = LidPresent (BOOLEAN)
            lid_present = buf[2]
            if not lid_present:
                return

            # Read actual lid state via user32 — if the system is running
            # and we're collecting, the lid is open (closed lid → sleep/hibernate
            # unless external display keeps it awake, in which case "closed" is
            # still correct to report).
            # Use the display state as proxy: EnumDisplayMonitors with builtin display
            monitor_count = ctypes.c_int(0)

            @ctypes.WINFUNCTYPE(
                ctypes.c_bool,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.wintypes.RECT),
                ctypes.c_void_p,
            )
            def _monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                monitor_count.value += 1
                return True

            ctypes.windll.user32.EnumDisplayMonitors(None, None, _monitor_enum_proc, 0)

            # If we have at least one monitor active, lid is open
            # (or closed with external display — both mean "usable")
            metrics["system.lid_open"] = metric_value(monitor_count.value > 0)
        except Exception:
            logger.debug("Lid state detection failed", exc_info=True)

    def _collect_thermals_fallback(self, metrics: dict[str, Any], now: float) -> None:
        """Query MSAcpi_ThermalZoneTemperature for basic CPU temp."""
        import wmi  # type: ignore[import-untyped]

        try:
            wmi_conn = wmi.WMI(namespace=r"root\wmi")
            sensors = wmi_conn.MSAcpi_ThermalZoneTemperature()
            for i, sensor in enumerate(sensors):
                raw = getattr(sensor, "CurrentTemperature", None)
                if raw is None:
                    continue
                celsius = round((float(raw) / 10.0) - 273.15, 1)
                if celsius < 0 or celsius > 150:
                    continue

                key = "cpu_package" if i == 0 else f"thermal_zone_{i}"
                metrics[key] = metric_value(celsius, unit="Cel")
        except Exception:
            if not self._thermal_fallback_warned:
                logger.info("MSAcpi_ThermalZoneTemperature not available (may need admin)")
                self._thermal_fallback_warned = True

    # --- System metrics (psutil + WMI static) ---

    def _collect_system_metrics(self, conn: object, metrics: dict[str, Any], now: float) -> None:
        """Collect live psutil metrics and cached WMI static info."""
        self._collect_psutil_metrics(metrics, now)
        self._collect_wmi_static(conn, metrics, now)

    def _collect_psutil_metrics(self, metrics: dict[str, Any], now: float) -> None:
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
            metrics["system.ram_used_gb"] = metric_value(round(vmem.used / 1024**3, 2), unit="GB")
            metrics["system.ram_total_gb"] = metric_value(
                round(vmem.total / 1024**3, 2), unit="GB"
            )
            metrics["system.ram_usage_percent"] = metric_value(vmem.percent, unit="%")

            swap = psutil.swap_memory()
            metrics["system.swap_usage_percent"] = metric_value(swap.percent, unit="%")

            disk_path = "C:\\" if sys.platform == "win32" else "/"
            try:
                disk = psutil.disk_usage(disk_path)
                metrics["system.disk_usage_percent"] = metric_value(disk.percent, unit="%")
                metrics["system.disk_free_gb"] = metric_value(
                    round(disk.free / 1024**3, 2), unit="GB"
                )
            except OSError:
                logger.debug("Failed to read disk usage for %s", disk_path)

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

    def _collect_wmi_static(self, conn: object, metrics: dict[str, Any], now: float) -> None:
        """Collect slow-changing WMI info once, then republish from cache."""
        if self._wmi_static_collected:
            for key, cached in self._wmi_static.items():
                metrics[key] = metric_value(cached["value"], unit=cached.get("unit"))
            return

        try:
            static: dict[str, dict[str, Any]] = {}

            # --- CPU info ---
            try:
                procs = conn.Win32_Processor()  # type: ignore[attr-defined]
                if procs:
                    cpu = procs[0]
                    name = getattr(cpu, "Name", None)
                    if name:
                        static["system.cpu_model"] = {"value": str(name).strip()}
                    cores = getattr(cpu, "NumberOfCores", None)
                    if cores is not None:
                        static["system.cpu_cores"] = {"value": int(cores)}
                    threads = getattr(cpu, "NumberOfLogicalProcessors", None)
                    if threads is not None:
                        static["system.cpu_threads"] = {"value": int(threads)}
            except Exception:
                logger.debug("WMI Win32_Processor query failed", exc_info=True)

            # --- GPU info ---
            try:
                gpus = conn.Win32_VideoController()  # type: ignore[attr-defined]
                if gpus:
                    gpu = gpus[0]
                    gpu_name = getattr(gpu, "Name", None)
                    if gpu_name:
                        static["system.gpu_model"] = {"value": str(gpu_name).strip()}
                    adapter_ram = getattr(gpu, "AdapterRAM", None)
                    if adapter_ram is not None and int(adapter_ram) > 0:
                        static["system.gpu_vram_gb"] = {
                            "value": round(int(adapter_ram) / 1024**3, 1),
                            "unit": "GB",
                        }
                    driver_ver = getattr(gpu, "DriverVersion", None)
                    if driver_ver:
                        static["system.gpu_driver"] = {"value": str(driver_ver)}
                    h_res = getattr(gpu, "CurrentHorizontalResolution", None)
                    v_res = getattr(gpu, "CurrentVerticalResolution", None)
                    if h_res and v_res:
                        static["system.screen_resolution"] = {"value": f"{h_res}x{v_res}"}
            except Exception:
                logger.debug("WMI Win32_VideoController query failed", exc_info=True)

            # --- OS info ---
            try:
                os_list = conn.Win32_OperatingSystem()  # type: ignore[attr-defined]
                if os_list:
                    os_obj = os_list[0]
                    caption = getattr(os_obj, "Caption", None)
                    if caption:
                        static["system.os_name"] = {"value": str(caption).strip()}
                    version = getattr(os_obj, "Version", None)
                    if version:
                        static["system.os_version"] = {"value": str(version)}
                    build = getattr(os_obj, "BuildNumber", None)
                    if build:
                        static["system.os_build"] = {"value": str(build)}
            except Exception:
                logger.debug("WMI Win32_OperatingSystem query failed", exc_info=True)

            # --- BIOS version ---
            try:
                bios_list = conn.Win32_BIOS()  # type: ignore[attr-defined]
                if bios_list:
                    bios_ver = getattr(bios_list[0], "SMBIOSBIOSVersion", None)
                    if bios_ver:
                        static["system.bios_version"] = {"value": str(bios_ver)}
            except Exception:
                logger.debug("WMI Win32_BIOS query failed", exc_info=True)

            # --- Disk model ---
            try:
                disks = conn.Win32_DiskDrive()  # type: ignore[attr-defined]
                if disks:
                    disk_model = getattr(disks[0], "Model", None)
                    if disk_model:
                        static["system.disk_model"] = {"value": str(disk_model).strip()}
            except Exception:
                logger.debug("WMI Win32_DiskDrive query failed", exc_info=True)

            self._wmi_static = static
            self._wmi_static_collected = True
            for key, val in static.items():
                metrics[key] = metric_value(val["value"], unit=val.get("unit"))

            logger.info(
                "Collected %d WMI static system metrics (cached for future cycles)",
                len(static),
            )

        except Exception:
            logger.exception("Failed to collect WMI static system metrics")


COLLECTOR_CLASS = WindowsPlatformCollector
