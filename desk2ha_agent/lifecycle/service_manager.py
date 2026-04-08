"""Service restart across platforms."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


async def restart_service() -> dict[str, str]:
    """Trigger a service restart. Returns immediately; restart happens async."""
    return await asyncio.to_thread(_restart_sync)


def _restart_sync() -> dict[str, str]:
    try:
        if sys.platform == "win32":
            # NSSM restart
            subprocess.Popen(
                ["nssm", "restart", "Desk2HAAgent"],
                creationflags=subprocess.DETACHED_PROCESS,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["launchctl", "kickstart", "-k", "system/com.desk2ha.agent"],
            )
        else:
            subprocess.Popen(
                ["systemctl", "restart", "desk2ha-agent"],
            )
        logger.info("Service restart triggered")
        return {"status": "completed", "message": "Restart triggered"}
    except Exception as exc:
        logger.error("Failed to restart service: %s", exc)
        return {"status": "failed", "message": str(exc)}
