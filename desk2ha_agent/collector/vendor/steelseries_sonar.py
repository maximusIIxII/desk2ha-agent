"""SteelSeries GG Sonar vendor collector.

Reads audio settings from the SteelSeries Sonar application via its
local REST API. Sonar runs as part of SteelSeries GG on Windows and
exposes volume, mute, and chat-mix endpoints on a random localhost port.

Port discovery: reads C:/ProgramData/SteelSeries/GG/coreProps.json
to find the GG hub address, then queries /subApps for the Sonar URL.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

_CORE_PROPS = Path("C:/ProgramData/SteelSeries/GG/coreProps.json")

_CHANNELS = ("master", "game", "chatRender", "media", "aux")


class SteelSeriesSonarCollector(Collector):
    """Read audio volumes and chat-mix from SteelSeries Sonar."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="steelseries_sonar",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS},
        capabilities={"audio"},
        description="SteelSeries Sonar volume, mute, and chat-mix",
        requires_hardware="SteelSeries GG with Sonar enabled",
        optional_dependencies=["aiohttp"],
    )

    def __init__(self) -> None:
        self._sonar_url: str = ""

    async def probe(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            url = await self._discover_sonar_url()
            if url:
                self._sonar_url = url
                return True
        except Exception:
            logger.debug("Sonar probe failed", exc_info=True)
        return False

    async def setup(self) -> None:
        logger.info("SteelSeries Sonar: %s", self._sonar_url)

    async def collect(self) -> dict[str, Any]:
        import aiohttp

        metrics: dict[str, Any] = {}
        prefix = "audio.sonar"

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Volume settings (classic mode)
                async with session.get(f"{self._sonar_url}/volumeSettings/classic") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for channel in _CHANNELS:
                            ch_data = data.get(channel)
                            if not ch_data:
                                continue
                            vol = ch_data.get("volume")
                            muted = ch_data.get("muted")
                            if vol is not None:
                                metrics[f"{prefix}.{channel}_volume"] = metric_value(
                                    round(float(vol) * 100, 1), unit="%"
                                )
                            if muted is not None:
                                metrics[f"{prefix}.{channel}_muted"] = metric_value(bool(muted))

                # Chat-mix
                async with session.get(f"{self._sonar_url}/chatMix") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        balance = data.get("balance")
                        if balance is not None:
                            metrics[f"{prefix}.chatmix_balance"] = metric_value(
                                round(float(balance), 2)
                            )

        except Exception:
            logger.debug("Sonar collect failed", exc_info=True)

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Set Sonar volume or mute state."""
        import aiohttp

        if not command.startswith("sonar."):
            raise NotImplementedError

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if command == "sonar.set_volume":
                    channel = parameters.get("channel", "master")
                    volume = float(parameters.get("value", 0.5))
                    volume = max(0.0, min(1.0, volume))
                    async with session.put(
                        f"{self._sonar_url}/volumeSettings/classic/{channel}/Volume/{volume}"
                    ) as resp:
                        if resp.status == 200:
                            return {"status": "completed"}
                        return {"status": "failed", "message": f"HTTP {resp.status}"}

                if command == "sonar.set_mute":
                    channel = parameters.get("channel", "master")
                    muted = str(bool(parameters.get("value", True))).lower()
                    async with session.put(
                        f"{self._sonar_url}/volumeSettings/classic/{channel}/Mute/{muted}"
                    ) as resp:
                        if resp.status == 200:
                            return {"status": "completed"}
                        return {"status": "failed", "message": f"HTTP {resp.status}"}

                if command == "sonar.set_chatmix":
                    balance = float(parameters.get("value", 0.0))
                    balance = max(-1.0, min(1.0, balance))
                    async with session.put(f"{self._sonar_url}/chatMix/{balance}") as resp:
                        if resp.status == 200:
                            return {"status": "completed"}
                        return {"status": "failed", "message": f"HTTP {resp.status}"}

        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

        raise NotImplementedError(f"Unknown sonar command: {command}")

    async def _discover_sonar_url(self) -> str | None:
        """Discover the Sonar REST URL via SteelSeries GG coreProps."""
        import ssl

        import aiohttp

        if not _CORE_PROPS.is_file():
            return None

        props = json.loads(_CORE_PROPS.read_text())
        gg_address = props.get("address")
        if not gg_address:
            return None

        gg_url = f"https://{gg_address}"

        # GG uses a self-signed cert
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        timeout = aiohttp.ClientTimeout(total=5)
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        async with (
            aiohttp.ClientSession(timeout=timeout, connector=connector) as session,
            session.get(f"{gg_url}/subApps") as resp,
        ):
            if resp.status != 200:
                return None
            data = await resp.json()

        sonar = data.get("subApps", {}).get("sonar", {})
        web_url = sonar.get("metadata", {}).get("webServerAddress")
        if web_url:
            return web_url.rstrip("/")
        return None

    async def teardown(self) -> None:
        self._sonar_url = ""


COLLECTOR_CLASS = SteelSeriesSonarCollector
