"""Check for new agent releases on GitHub."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any

from desk2ha_agent import __version__

logger = logging.getLogger(__name__)

GITHUB_RELEASES_URL = (
    "https://api.github.com/repos/maximusIIxII/desk2ha-agent/releases/latest"
)
_TIMEOUT = 10


async def check_for_update() -> dict[str, Any]:
    """Check GitHub for the latest release.

    Returns a dict with:
      installed_version, latest_version, update_available,
      release_url, release_notes (summary)
    """
    return await asyncio.to_thread(_check_sync)


def _check_sync() -> dict[str, Any]:
    result: dict[str, Any] = {
        "installed_version": __version__,
        "latest_version": __version__,
        "update_available": False,
    }

    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"desk2ha-agent/{__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())

        tag = data.get("tag_name", "")
        # Strip leading 'v' if present
        latest = tag.lstrip("v")

        result["latest_version"] = latest
        result["update_available"] = _is_newer(latest, __version__)
        result["release_url"] = data.get("html_url", "")

        body = data.get("body", "")
        if body and len(body) > 500:
            body = body[:500] + "..."
        result["release_notes"] = body

    except Exception as exc:
        logger.debug("Version check failed: %s", exc)
        result["error"] = str(exc)

    return result


def _is_newer(latest: str, current: str) -> bool:
    """Compare semver strings. Returns True if latest > current."""
    try:
        lat = tuple(int(x) for x in latest.split(".")[:3])
        cur = tuple(int(x) for x in current.split(".")[:3])
        return lat > cur
    except (ValueError, IndexError):
        return False
