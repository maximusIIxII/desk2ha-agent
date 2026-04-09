"""Phone-home provisioning — agent registers itself with Home Assistant.

On first start, if a ``[provisioning]`` section is present in the config,
the agent sends its connection details to HA so a config entry can be
created automatically.  The provisioning section is removed after a
successful phone-home to prevent repeated calls.
"""

from __future__ import annotations

import logging
import platform
import socket
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)


async def phone_home(
    phone_home_url: str,
    phone_home_token: str,
    agent_port: int,
    auth_token: str,
    config_path: Path,
) -> bool:
    """POST connection details to HA and remove provisioning config on success.

    Returns True if the phone-home was successful.
    """
    if phone_home_url.startswith("http://"):
        logger.warning("Phone-home uses plaintext HTTP — use on trusted networks only")

    hostname = socket.gethostname()
    # Determine local IP by connecting to the HA host
    ha_host = phone_home_url.split("//")[-1].split("/")[0].split(":")[0]
    local_ip = _get_local_ip(ha_host)

    agent_url = f"http://{local_ip}:{agent_port}"

    payload = {
        "phone_home_token": phone_home_token,
        "device_key": f"{hostname}-provisioning",
        "agent_url": agent_url,
        "agent_token": auth_token,
        "hardware": {
            "hostname": hostname,
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "manufacturer": _get_manufacturer(),
            "model": _get_model(),
        },
    }

    try:
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session,
            session.post(phone_home_url, json=payload) as resp,
        ):
            if resp.status == 200:
                logger.info(
                    "Phone-home successful — registered with HA at %s",
                    phone_home_url.split("/desk2ha")[0],
                )
                _remove_provisioning_section(config_path)
                return True
            body = await resp.text()
            logger.warning("Phone-home failed (HTTP %d): %s", resp.status, body)
            return False
    except Exception:
        logger.warning("Phone-home failed — will retry on next start", exc_info=True)
        return False


def _get_local_ip(target_host: str, target_port: int = 80) -> str:
    """Determine local IP by connecting to the target."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_host, target_port))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return socket.gethostname()


def _get_manufacturer() -> str:
    """Best-effort manufacturer detection."""
    if platform.system() == "Windows":
        try:
            import subprocess

            result = subprocess.run(
                ["wmic", "computersystem", "get", "manufacturer", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Manufacturer="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            model = result.stdout.strip()
            return "Apple" if model else "Unknown"
        except Exception:
            pass
    else:
        try:
            return Path("/sys/class/dmi/id/sys_vendor").read_text().strip()
        except Exception:
            pass
    return "Unknown"


def _get_model() -> str:
    """Best-effort model detection."""
    if platform.system() == "Windows":
        try:
            import subprocess

            result = subprocess.run(
                ["wmic", "computersystem", "get", "model", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Model="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() or "Mac"
        except Exception:
            pass
    else:
        try:
            return Path("/sys/class/dmi/id/product_name").read_text().strip()
        except Exception:
            pass
    return "Unknown"


def _remove_provisioning_section(config_path: Path) -> None:
    """Remove [provisioning] section from config TOML so phone-home doesn't repeat."""
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
        out: list[str] = []
        skip = False
        for line in lines:
            stripped = line.strip()
            if stripped == "[provisioning]":
                skip = True
                continue
            if skip and stripped.startswith("["):
                skip = False
            if not skip:
                out.append(line)
        config_path.write_text("".join(out), encoding="utf-8")
        logger.info("Removed [provisioning] section from %s", config_path)
    except Exception:
        logger.warning("Could not remove [provisioning] section", exc_info=True)
