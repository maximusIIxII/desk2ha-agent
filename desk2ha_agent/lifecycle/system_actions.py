"""System-level actions: lock, sleep, shutdown, hibernate."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


async def lock_screen() -> dict[str, str]:
    """Lock the workstation."""
    return await asyncio.to_thread(_lock_sync)


async def sleep_system() -> dict[str, str]:
    """Put the system to sleep."""
    return await asyncio.to_thread(_sleep_sync)


async def shutdown_system(delay: int = 0) -> dict[str, str]:
    """Shut down the system."""
    return await asyncio.to_thread(_shutdown_sync, delay)


async def hibernate_system() -> dict[str, str]:
    """Hibernate the system."""
    return await asyncio.to_thread(_hibernate_sync)


def _lock_sync() -> dict[str, str]:
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.LockWorkStation()
        elif sys.platform == "darwin":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "q" '
                    "using {command down, control down}",
                ],
                timeout=5,
            )
        else:
            subprocess.run(["loginctl", "lock-session"], timeout=5)
        logger.info("Screen locked")
        return {"status": "completed", "action": "lock"}
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}


def _sleep_sync() -> dict[str, str]:
    try:
        if sys.platform == "win32":
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Add-Type -Assembly System.Windows.Forms;"
                    " [System.Windows.Forms.Application]"
                    "::SetSuspendState('Suspend',$false,$false)",
                ],
                timeout=5,
            )
        elif sys.platform == "darwin":
            subprocess.run(["pmset", "sleepnow"], timeout=5)
        else:
            subprocess.run(["systemctl", "suspend"], timeout=5)
        logger.info("System sleep triggered")
        return {"status": "completed", "action": "sleep"}
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}


def _shutdown_sync(delay: int = 0) -> dict[str, str]:
    try:
        if sys.platform == "win32":
            cmd = ["shutdown", "/s", "/t", str(delay)]
        elif sys.platform == "darwin":
            cmd = ["sudo", "shutdown", "-h", f"+{max(1, delay // 60)}"]
        else:
            cmd = ["sudo", "shutdown", "-h", f"+{max(1, delay // 60)}"]
        subprocess.Popen(cmd)
        logger.info("System shutdown triggered (delay=%ds)", delay)
        return {"status": "completed", "action": "shutdown", "delay": delay}
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}


def _hibernate_sync() -> dict[str, str]:
    try:
        if sys.platform == "win32":
            subprocess.run(["shutdown", "/h"], timeout=5)
        elif sys.platform == "linux":
            subprocess.run(["systemctl", "hibernate"], timeout=5)
        else:
            return {"status": "failed", "message": "Hibernate not supported on this platform"}
        logger.info("System hibernate triggered")
        return {"status": "completed", "action": "hibernate"}
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}
