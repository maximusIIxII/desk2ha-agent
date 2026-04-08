"""Network metrics collector.

Reports WiFi signal strength (RSSI), Ethernet link speed, and
active network interface information. Cross-platform via psutil
and platform-specific tools.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
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


class NetworkCollector(Collector):
    """Collect network interface metrics."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="network",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"network"},
        description="Network interface info, WiFi RSSI, Ethernet speed",
    )

    async def probe(self) -> bool:
        addrs = psutil.net_if_addrs()
        return len(addrs) > 0

    async def setup(self) -> None:
        logger.info("Network collector activated")

    async def collect(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}

        # Interface stats
        stats = psutil.net_if_stats()
        for iface, st in stats.items():
            if not st.isup:
                continue
            slug = iface.lower().replace(" ", "_").replace("-", "_")[:20]

            if st.speed > 0:
                metrics[f"network.{slug}.speed_mbps"] = metric_value(float(st.speed), unit="Mbps")

        # WiFi signal strength (platform-specific)
        try:
            wifi = await asyncio.to_thread(self._get_wifi_rssi)
            if wifi:
                metrics.update(wifi)
        except Exception:
            logger.debug("WiFi RSSI collection failed", exc_info=True)

        return metrics

    def _get_wifi_rssi(self) -> dict[str, Any]:
        """Get WiFi signal strength via platform tools."""
        if sys.platform == "win32":
            return self._wifi_rssi_windows()
        if sys.platform == "linux":
            return self._wifi_rssi_linux()
        if sys.platform == "darwin":
            return self._wifi_rssi_macos()
        return {}

    def _wifi_rssi_windows(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            metrics: dict[str, Any] = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                if "Signal" in line and "%" in line:
                    pct = line.split(":")[1].strip().rstrip("%")
                    metrics["network.wifi_signal_percent"] = metric_value(float(pct), unit="%")
                elif "SSID" in line and "BSSID" not in line:
                    ssid = line.split(":", 1)[1].strip()
                    if ssid:
                        metrics["network.wifi_ssid"] = metric_value(ssid)
            return metrics
        except Exception:
            return {}

    def _wifi_rssi_linux(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["iwconfig"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            metrics: dict[str, Any] = {}
            for line in result.stdout.splitlines():
                if "Signal level" in line:
                    parts = line.split("Signal level=")
                    if len(parts) > 1:
                        dbm = parts[1].split()[0].rstrip("dBm")
                        metrics["network.wifi_rssi_dbm"] = metric_value(float(dbm), unit="dBm")
                if "ESSID:" in line:
                    ssid = line.split('ESSID:"')[1].rstrip('"') if 'ESSID:"' in line else ""
                    if ssid:
                        metrics["network.wifi_ssid"] = metric_value(ssid)
            return metrics
        except Exception:
            return {}

    def _wifi_rssi_macos(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                [
                    "/System/Library/PrivateFrameworks/Apple80211.framework"
                    "/Versions/Current/Resources/airport",
                    "-I",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            metrics: dict[str, Any] = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("agrCtlRSSI:"):
                    rssi = line.split(":")[1].strip()
                    metrics["network.wifi_rssi_dbm"] = metric_value(float(rssi), unit="dBm")
                elif line.startswith("SSID:"):
                    ssid = line.split(":", 1)[1].strip()
                    if ssid:
                        metrics["network.wifi_ssid"] = metric_value(ssid)
            return metrics
        except Exception:
            return {}

    async def teardown(self) -> None:
        pass


COLLECTOR_CLASS = NetworkCollector
