"""Agent self-update via pip."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


async def self_update(version: str | None = None, source: str = "pypi") -> dict[str, str]:
    """Download and install a new version of the agent.

    Returns dict with status and message.
    """
    return await asyncio.to_thread(_update_sync, version, source)


def _update_sync(version: str | None, source: str) -> dict[str, str]:
    pkg = "desk2ha-agent"
    if version:
        pkg = f"{pkg}=={version}"

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--index-url",
                "https://pypi.org/simple/",
                pkg,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("Agent updated to %s", version or "latest")
            return {"status": "completed", "message": f"Updated to {version or 'latest'}"}
        else:
            logger.error("Update failed: %s", result.stderr)
            return {"status": "failed", "message": result.stderr[:500]}
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}
