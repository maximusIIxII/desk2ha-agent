"""HTTP client for querying the elevated helper process."""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

from desk2ha_agent.helper.server import DEFAULT_PORT, HELPER_SECRET_ENV

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=5)


class HelperClient:
    """Queries the elevated helper for privileged metrics."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host: str = "127.0.0.1",
        secret: str | None = None,
    ) -> None:
        self._base_url = f"http://{host}:{port}"
        self._secret = secret
        self._available: bool | None = None

    def _auth_headers(self) -> dict[str, str]:
        """Build auth headers from config secret or env var fallback."""
        secret = self._secret or os.environ.get(HELPER_SECRET_ENV, "")
        if secret:
            return {"Authorization": f"Bearer {secret}"}
        return {}

    async def is_available(self) -> bool:
        """Check if the helper process is running."""
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT) as session,
                session.get(f"{self._base_url}/health", headers=self._auth_headers()) as resp,
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
                session.get(f"{self._base_url}/metrics", headers=self._auth_headers()) as resp,
            ):
                if resp.status == 200:
                    return await resp.json()
        except (aiohttp.ClientError, OSError):
            if self._available is not False:
                logger.info("Helper not reachable at %s", self._base_url)
                self._available = False
        return {}
