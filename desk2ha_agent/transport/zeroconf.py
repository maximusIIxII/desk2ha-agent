"""Zeroconf/mDNS service advertisement.

Advertises the agent as ``_desk2ha._tcp.local.`` so that Home Assistant
can auto-discover it via the Zeroconf config flow.
"""

from __future__ import annotations

import logging
import platform
import socket
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from desk2ha_agent.collector.base import DeviceInfoProvider
    from desk2ha_agent.config import HttpConfig


def _get_local_ip() -> str:
    """Get the primary local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ZeroconfAdvertiser:
    """Advertise the agent via mDNS/Zeroconf."""

    def __init__(
        self,
        http_config: HttpConfig,
        info_provider: DeviceInfoProvider | None = None,
    ) -> None:
        self._http_config = http_config
        self._info_provider = info_provider
        self._zc: object | None = None
        self._info: object | None = None

    async def start(self) -> None:
        """Register the Zeroconf service."""
        try:
            from zeroconf import IPVersion, ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError:
            logger.debug("zeroconf package not installed — skipping advertisement")
            return

        device_key = "unknown"
        hostname = platform.node()
        if self._info_provider is not None:
            device_key = self._info_provider.get_device_key() or device_key

        ip = _get_local_ip()
        port = self._http_config.port

        properties = {
            "device_key": device_key,
            "hostname": hostname,
            "version": "0.1.0",
        }

        # Add hardware info if available
        if self._info_provider is not None:
            hw = self._info_provider.get_hardware()
            if hw:
                if hw.get("manufacturer"):
                    properties["manufacturer"] = hw["manufacturer"]
                if hw.get("model"):
                    properties["model"] = hw["model"]

        self._info = ServiceInfo(
            "_desk2ha._tcp.local.",
            f"Desk2HA {hostname}._desk2ha._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties=properties,
            server=f"{hostname}.local.",
        )

        self._zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        await self._zc.async_register_service(self._info)
        logger.info(
            "Zeroconf: advertising _desk2ha._tcp on %s:%d (device_key=%s)",
            ip,
            port,
            device_key,
        )

    async def stop(self) -> None:
        """Unregister the Zeroconf service."""
        if self._zc is not None and self._info is not None:
            await self._zc.async_unregister_service(self._info)
            await self._zc.async_close()
            logger.info("Zeroconf: service unregistered")
