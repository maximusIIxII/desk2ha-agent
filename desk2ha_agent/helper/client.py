"""HTTP client for querying the elevated helper process."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from desk2ha_agent.helper.server import DEFAULT_PORT

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=5)


class HelperClient:
    """Queries the elevated helper for privileged metrics."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> None:
        self._base_url = f"http://{host}:{port}"
        self._available: bool | None = None

    async def is_available(self) -> bool:
        """Check if the helper process is running."""
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT) as session,
                session.get(f"{self._base_url}/health") as resp,
            ):
                if resp.status == 200:
                    self._available = True
                    return True
        except (aiohttp.ClientError, OSError):
            pass
        self._available = False
        return False

    async def get_metrics(self) -> dict[str, Any]:
        """Fetch metrics from the helper. Returns empty dict on failure."""
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT) as session,
                session.get(f"{self._base_url}/metrics") as resp,
            ):
                if resp.status == 200:
                    return await resp.json()
        except (aiohttp.ClientError, OSError):
            if self._available is not False:
                logger.info("Helper not reachable at %s", self._base_url)
                self._available = False
        return {}
