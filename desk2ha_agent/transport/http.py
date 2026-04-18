"""aiohttp server implementing the OpenAPI v2.0.0 spec."""

from __future__ import annotations

import logging
import os
import platform
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from desk2ha_agent import __version__
from desk2ha_agent.transport.base import Transport

if TYPE_CHECKING:
    from desk2ha_agent.collector.base import DeviceInfoProvider
    from desk2ha_agent.config import HttpConfig
    from desk2ha_agent.lifecycle.policy import PolicyReceiver
    from desk2ha_agent.scheduler import Scheduler
    from desk2ha_agent.state import StateCache

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0.0"
_FALLBACK_DEVICE_KEY = "DESK-DEV0001"

_Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _bearer_auth_middleware(token: str) -> Any:
    """Middleware that checks Bearer token on protected routes."""

    @web.middleware
    async def middleware(
        request: web.Request,
        handler: _Handler,
    ) -> web.StreamResponse:
        if request.path == "/v1/health":
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {token}":
            return web.json_response(
                {"error": "unauthorized", "message": "Missing or invalid bearer token"},
                status=401,
            )
        return await handler(request)

    return middleware


class HttpTransport(Transport):
    """aiohttp-based HTTP server exposing the agent API."""

    def __init__(
        self,
        config: HttpConfig,
        state: StateCache,
        scheduler: Scheduler,
        info_provider: DeviceInfoProvider | None = None,
        policy_receiver: PolicyReceiver | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._scheduler = scheduler
        self._info_provider = info_provider
        self._policy_receiver = policy_receiver
        self._config_path = config_path
        self._start_time = time.monotonic()
        self._app = self._create_app()
        self._runner: web.AppRunner | None = None

    def _create_app(self) -> web.Application:
        assert self._config.auth_token is not None
        app = web.Application(
            middlewares=[_bearer_auth_middleware(self._config.auth_token)],
            client_max_size=65536,  # 64 KB request body limit
        )
        app.router.add_get("/v1/health", self._handle_health)
        app.router.add_get("/v1/info", self._handle_info)
        app.router.add_get("/v1/metrics", self._handle_metrics)
        app.router.add_get("/v1/metrics/prometheus", self._handle_metrics_prometheus)
        app.router.add_get("/v1/config", self._handle_config)
        app.router.add_get("/v1/image/{device_key}", self._handle_image)
        app.router.add_get("/v1/commands", self._handle_commands_list)
        app.router.add_post("/v1/commands", self._handle_commands_execute)
        app.router.add_get("/v1/commands/{command_id}", self._handle_commands_status)
        app.router.add_get("/v1/update/check", self._handle_update_check)
        app.router.add_post("/v1/update/install", self._handle_update_install)
        return app

    @property
    def app(self) -> web.Application:
        """Expose the app for testing."""
        return self._app

    async def start(self) -> None:
        """Start the HTTP server."""
        # Kill any existing agent on this port before starting
        await self._kill_existing(self._config.port)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.bind, self._config.port)
        await site.start()
        logger.info(
            "HTTP transport listening on %s:%d",
            self._config.bind,
            self._config.port,
        )

    @staticmethod
    async def _kill_existing(port: int) -> None:
        """Kill any process already listening on the given port."""
        import asyncio
        import sys

        if sys.platform == "win32":
            cmd = f'netstat -ano | findstr ":{port} " | findstr "LISTEN"'
        else:
            cmd = f"lsof -ti tcp:{port}"
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if not stdout.strip():
                return
            for line in stdout.decode().strip().splitlines():
                pid = line.strip().split()[-1] if sys.platform == "win32" else line.strip()
                if pid.isdigit() and int(pid) != os.getpid():
                    logger.warning("Killing existing agent on port %d (PID %s)", port, pid)
                    if sys.platform == "win32":
                        await asyncio.create_subprocess_shell(f"taskkill /PID {pid} /F")
                    else:
                        os.kill(int(pid), 15)
                    await asyncio.sleep(1)
        except Exception:
            logger.debug("Could not check for existing agent", exc_info=True)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._runner is not None:
            await self._runner.cleanup()
            logger.info("HTTP transport stopped")

    def _get_device_key(self) -> str:
        if self._info_provider is not None:
            key = self._info_provider.get_device_key()
            if key is not None:
                return key
        return _FALLBACK_DEVICE_KEY

    def _get_capabilities(self) -> list[str]:
        """Collect capabilities from all collectors via collector.meta.capabilities."""
        caps: set[str] = set()
        for collector in self._scheduler.collectors:
            caps.update(collector.meta.capabilities)
        return sorted(caps)

    def _get_collector_statuses(self) -> list[dict[str, Any]]:
        return [
            {
                "name": c.meta.name,
                "tier": c.meta.tier.value,
                "healthy": True,
            }
            for c in self._scheduler.collectors
        ]

    def _get_peripherals(self) -> list[dict[str, Any]]:
        """Collect peripherals from PeripheralProvider collectors."""
        from desk2ha_agent.collector.base import PeripheralProvider

        peripherals: list[dict[str, Any]] = []
        for collector in self._scheduler.collectors:
            if isinstance(collector, PeripheralProvider):
                peripherals.extend(collector.get_peripherals())
        return peripherals

    async def _handle_health(self, _request: web.Request) -> web.Response:
        status = "ok" if self._scheduler.running else "degraded"
        uptime = int(time.monotonic() - self._start_time)
        resp = {
            "schema_version": SCHEMA_VERSION,
            "agent_version": __version__,
            "device_key": self._get_device_key(),
            "status": status,
            "uptime_seconds": uptime,
        }
        return web.json_response(resp)

    async def _handle_info(self, _request: web.Request) -> web.Response:
        identity: dict[str, Any]
        hardware: dict[str, Any]
        os_info: dict[str, Any] | None = None

        if self._info_provider is not None:
            identity = self._info_provider.get_identity() or {
                "hostname": platform.node(),
            }
            hardware = self._info_provider.get_hardware() or {}
            os_info = self._info_provider.get_os()
        else:
            identity = {"hostname": platform.node()}
            hardware = {"device_type": "desktop"}

        resp: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "agent_version": __version__,
            "device_key": self._get_device_key(),
            "identity": identity,
            "hardware": hardware,
            "capabilities": self._get_capabilities(),
            "collectors": self._get_collector_statuses(),
            "peripherals": self._get_peripherals(),
            "config": self._build_config_summary(),
        }
        if os_info is not None:
            resp["os"] = os_info

        return web.json_response(resp)

    async def _handle_metrics(self, _request: web.Request) -> web.Response:
        all_metrics = await self._state.snapshot()

        # Partition metrics by category prefix
        system: dict[str, Any] = {}
        thermals: dict[str, Any] = {}
        power: dict[str, Any] = {}
        battery: dict[str, Any] = {}
        displays: dict[str, dict[str, Any]] = {}
        peripherals: dict[str, dict[str, Any]] = {}
        audio: dict[str, dict[str, Any]] = {}
        agent: dict[str, Any] = {}

        for key, value in all_metrics.items():
            if key.startswith("system."):
                system[key.removeprefix("system.")] = value
            elif key.startswith("power."):
                power[key.removeprefix("power.")] = value
            elif key.startswith("battery."):
                battery[key.removeprefix("battery.")] = value
            elif key.startswith("display."):
                parts = key.split(".", 2)
                if len(parts) == 3:
                    dev_id = f"{parts[0]}.{parts[1]}"
                    metric_name = parts[2]
                    displays.setdefault(dev_id, {})[metric_name] = value
            elif key.startswith("peripheral."):
                parts = key.split(".", 2)
                if len(parts) == 3:
                    dev_id = f"{parts[0]}.{parts[1]}"
                    metric_name = parts[2]
                    peripherals.setdefault(dev_id, {})[metric_name] = value
            elif key.startswith("audio."):
                parts = key.split(".", 2)
                if len(parts) == 3:
                    dev_id = f"{parts[0]}.{parts[1]}"
                    metric_name = parts[2]
                    audio.setdefault(dev_id, {})[metric_name] = value
            elif key.startswith("agent."):
                agent[key.removeprefix("agent.")] = value
            elif key.startswith("fleet."):
                agent[key] = value  # Fleet metrics reported under agent section
            elif key.startswith("network."):
                system[key] = value  # Network metrics go to system
            elif key.startswith("webcam."):
                parts = key.split(".", 2)
                if len(parts) == 3:
                    dev_id = f"peripheral.{parts[0]}_{parts[1]}"
                    peripherals.setdefault(dev_id, {})[parts[2]] = value
            else:
                # Thermal metrics (cpu_package, skin, fan.*)
                thermals[key] = value

        resp: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "agent_version": __version__,
            "device_key": self._get_device_key(),
            "snapshot_timestamp": time.time(),
        }

        if system:
            resp["system"] = system
        if thermals:
            resp["thermals"] = thermals
        if power:
            resp["power"] = power
        if battery:
            resp["battery"] = battery
        if displays:
            resp["displays"] = _serialize_nested(displays)
        if peripherals:
            resp["peripherals"] = _serialize_nested(peripherals)
        if audio:
            resp["audio"] = _serialize_nested(audio)
        if agent:
            resp["agent"] = agent

        return web.json_response(resp)

    async def _handle_metrics_prometheus(self, _request: web.Request) -> web.Response:
        """GET /v1/metrics/prometheus -- OpenMetrics text exposition."""
        all_metrics = await self._state.snapshot()
        device_key = self._get_device_key()
        hostname = platform.node()
        uptime = int(time.monotonic() - self._start_time)

        lines: list[str] = []

        # Agent metadata
        lines.append("# HELP desk2ha_agent_info Agent metadata")
        lines.append("# TYPE desk2ha_agent_info gauge")
        lines.append(
            f'desk2ha_agent_info{{version="{__version__}"'
            f',device_key="{device_key}",hostname="{hostname}"}} 1'
        )
        lines.append("# HELP desk2ha_agent_uptime_seconds Agent uptime")
        lines.append("# TYPE desk2ha_agent_uptime_seconds counter")
        lines.append(f"desk2ha_agent_uptime_seconds {uptime}")

        # Convert all state metrics
        for key, raw_value in sorted(all_metrics.items()):
            value, unit = _extract_metric_value(raw_value)
            if value is None:
                continue

            prom_name = _to_prometheus_name(key, unit)

            # Determine labels for nested keys (display.0.X, peripheral.Y.Z)
            labels = _extract_labels(key, device_key, hostname)

            if isinstance(value, bool):
                num_value = "1" if value else "0"
            elif isinstance(value, (int, float)):
                num_value = str(value)
            elif isinstance(value, str):
                # String values become info-style labels
                labels += f',value="{_escape_label_value(value)}"'
                num_value = "1"
            else:
                continue

            label_str = f"{{{labels}}}" if labels else ""
            lines.append(f"# TYPE {prom_name} gauge")
            lines.append(f"{prom_name}{label_str} {num_value}")

        lines.append("# EOF")
        body = "\n".join(lines) + "\n"
        return web.Response(
            text=body,
            content_type="text/plain",
            charset="utf-8",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    async def _handle_config(self, _request: web.Request) -> web.Response:
        """GET /v1/config -- return redacted config summary."""
        resp = {
            "schema_version": SCHEMA_VERSION,
            "agent_version": __version__,
            "config": self._build_config_summary(),
        }
        return web.json_response(resp)

    async def _handle_image(self, request: web.Request) -> web.Response:
        """GET /v1/image/{device_key} -- serve device icon SVG.

        For host device: uses Tier 2 vendor-specific icons.
        For peripherals: maps device_key to device type icon.
        """
        device_key = request.match_info.get("device_key", "host")

        # Peripheral image: determine device type from key or current metrics
        if device_key != "host" and device_key.startswith("peripheral."):
            svg = self._get_peripheral_icon(device_key)
            return web.Response(
                text=svg,
                content_type="image/svg+xml",
                headers={"Cache-Control": "public, max-age=3600"},
            )

        # Display image (display.0 or display_0)
        if device_key.startswith("display.") or device_key.startswith("display_"):
            from desk2ha_agent.images.device_icons import get_device_icon_svg

            return web.Response(
                text=get_device_icon_svg("monitor"),
                content_type="image/svg+xml",
                headers={"Cache-Control": "public, max-age=3600"},
            )

        # Host device: Tier 2 vendor icon
        from desk2ha_agent.images.vendor_icons import get_device_image

        hw_info: dict[str, Any] = {"device_type": "notebook"}
        if self._info_provider is not None:
            hw = self._info_provider.get_hardware()
            if hw:
                hw_info = hw

        svg = get_device_image(hw_info)
        return web.Response(
            text=svg,
            content_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    def _get_peripheral_icon(self, device_key: str) -> str:
        """Map a peripheral device_key to the appropriate device type SVG."""
        from desk2ha_agent.images.device_icons import get_device_icon_svg

        key_lower = device_key.lower()

        # Match device type from device_key patterns AND peripheral_db
        if "webcam" in key_lower or "camera" in key_lower:
            return get_device_icon_svg("webcam")
        if "keyboard" in key_lower or "kb" in key_lower:
            return get_device_icon_svg("keyboard")
        if "mouse" in key_lower:
            return get_device_icon_svg("mouse")
        if "headset" in key_lower or "earbud" in key_lower:
            return get_device_icon_svg("headset")
        if "dock" in key_lower or "hub" in key_lower:
            return get_device_icon_svg("dock")
        if "litra" in key_lower or "light" in key_lower:
            return get_device_icon_svg("light")
        if "speak" in key_lower:
            return get_device_icon_svg("speaker")

        # USB peripherals: look up VID:PID in peripheral_db for device type
        if "usb_" in key_lower:
            import re

            vid_pid_match = re.search(r"usb_([0-9a-f]{4})_([0-9a-f]{4})", key_lower)
            if vid_pid_match:
                from desk2ha_agent.peripheral_db import lookup_peripheral

                vid, pid = vid_pid_match.group(1), vid_pid_match.group(2)
                spec = lookup_peripheral(f"{vid}:{pid}")
                if spec:
                    type_map = {
                        "keyboard": "keyboard",
                        "mouse": "mouse",
                        "headset": "headset",
                        "earbuds": "headset",
                        "dock": "dock",
                        "webcam": "webcam",
                        "light": "light",
                        "speakerphone": "speaker",
                        "speaker": "speaker",
                    }
                    mapped = type_map.get(spec.device_type, "")
                    if mapped:
                        return get_device_icon_svg(mapped)

        # BT peripherals: look up model name from key suffix
        if "bt_" in key_lower:
            # Can't determine type from MAC address alone — use generic BT icon
            return get_device_icon_svg("headset")

        return get_device_icon_svg("notebook")

    async def _handle_commands_list(self, _request: web.Request) -> web.Response:
        """GET /v1/commands -- list available commands."""
        commands = []
        for collector in self._scheduler.collectors:
            caps = collector.meta.capabilities
            if "control" in caps or "display" in caps:
                commands.append(
                    {
                        "collector": collector.meta.name,
                        "capabilities": sorted(collector.meta.capabilities),
                    }
                )
        return web.json_response(
            {
                "schema_version": SCHEMA_VERSION,
                "agent_version": __version__,
                "commands": commands,
            }
        )

    async def _handle_commands_execute(self, request: web.Request) -> web.Response:
        """POST /v1/commands -- execute a command."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "bad_request", "message": "Invalid JSON body"},
                status=400,
            )

        command = body.get("command", "")
        target = body.get("target", "")
        parameters = body.get("parameters", {})

        if not command:
            return web.json_response(
                {"error": "bad_request", "message": "Missing 'command' field"},
                status=400,
            )

        # Agent-level commands (not routed to collectors)
        if command == "agent.restart":
            from desk2ha_agent.lifecycle.service_manager import restart_service

            result = await restart_service()
            return web.json_response(result)

        if command == "system.usb_reset":
            from desk2ha_agent.lifecycle.usb_watchdog import usb_reset

            result = await usb_reset()
            return web.json_response(result)

        if command == "system.kvm_diagnose":
            from desk2ha_agent.lifecycle.kvm_diagnose import kvm_diagnose

            data = await kvm_diagnose()
            return web.json_response({"status": "completed", "diagnostics": data})

        if command in (
            "system.lock",
            "system.sleep",
            "system.shutdown",
            "system.restart",
            "system.hibernate",
        ):
            from desk2ha_agent.lifecycle import system_actions

            action_map = {
                "system.lock": system_actions.lock_screen,
                "system.sleep": system_actions.sleep_system,
                "system.shutdown": lambda: system_actions.shutdown_system(
                    parameters.get("delay", 0)
                ),
                "system.restart": lambda: system_actions.restart_system(
                    parameters.get("delay", 0)
                ),
                "system.hibernate": system_actions.hibernate_system,
            }
            result = await action_map[command]()
            return web.json_response(result)

        if command == "remote.wake_on_lan":
            from desk2ha_agent.lifecycle.system_actions import wake_on_lan

            mac = parameters.get("mac", "")
            if not mac:
                return web.json_response(
                    {"error": "bad_request", "message": "Missing 'mac' parameter"},
                    status=400,
                )
            result = await wake_on_lan(mac)
            return web.json_response(result)

        if command == "agent.update":
            from desk2ha_agent.lifecycle.self_update import self_update

            version = parameters.get("version")
            result = await self_update(version=version)
            return web.json_response(result)

        # Bulk config command
        if command == "config.bulk_set" and self._config_path is not None:
            import asyncio

            from desk2ha_agent.lifecycle.config_api import bulk_set_config

            result = await asyncio.to_thread(
                bulk_set_config, self._config_path, parameters.get("changes", [])
            )
            return web.json_response(result)

        # Fleet policy commands
        if command.startswith("policy.") and self._policy_receiver is not None:
            if command == "policy.apply":
                result = await self._policy_receiver.apply_policy(parameters)
                return web.json_response(result)
            if command == "policy.status":
                result = await self._policy_receiver.get_status(parameters)
                return web.json_response(result)
            if command == "policy.remove":
                result = await self._policy_receiver.remove_policy(parameters)
                return web.json_response(result)

        # Route to the right collector
        for collector in self._scheduler.collectors:
            try:
                result = await collector.execute_command(command, target, parameters)
                return web.json_response(result)
            except NotImplementedError:
                continue
            except Exception as exc:
                logger.exception("Command %s failed on %s", command, collector.meta.name)
                return web.json_response(
                    {"error": "command_failed", "message": str(exc)},
                    status=500,
                )

        return web.json_response(
            {"error": "not_found", "message": f"No collector handles command: {command}"},
            status=404,
        )

    async def _handle_commands_status(self, request: web.Request) -> web.Response:
        """GET /v1/commands/{command_id} -- check command status (stub)."""
        command_id = request.match_info["command_id"]
        return web.json_response(
            {"error": "not_found", "message": f"Command {command_id} not found"},
            status=404,
        )

    async def _handle_update_check(self, _request: web.Request) -> web.Response:
        """GET /v1/update/check -- check for agent updates on GitHub."""
        from desk2ha_agent.lifecycle.version_check import check_for_update

        result = await check_for_update()
        return web.json_response(result)

    async def _handle_update_install(self, request: web.Request) -> web.Response:
        """POST /v1/update/install -- install an agent update."""
        from desk2ha_agent.lifecycle.self_update import self_update

        body = await request.json() if request.content_length else {}
        version = body.get("version")
        result = await self_update(version=version)
        return web.json_response(result)

    def _build_config_summary(self) -> dict[str, Any]:
        """Build a redacted config summary for info/config endpoints."""
        return {
            "http": {
                "enabled": True,
                "bind": self._config.bind,
                "port": self._config.port,
            },
            "collectors": {
                "count": len(self._scheduler.collectors),
                "names": [c.meta.name for c in self._scheduler.collectors],
            },
        }


def _serialize_nested(data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize nested metric dicts as an array for JSON response."""
    result: list[dict[str, Any]] = []
    for dev_key, metrics in data.items():
        entry: dict[str, Any] = {"id": dev_key}
        for mk, mv in metrics.items():
            entry[mk] = mv
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Prometheus text exposition helpers
# ---------------------------------------------------------------------------

_UNIT_SUFFIX_MAP: dict[str, str] = {
    "°C": "_celsius",
    "°F": "_fahrenheit",
    "%": "_percent",
    "RPM": "_rpm",
    "rpm": "_rpm",
    "W": "_watts",
    "V": "_volts",
    "A": "_amps",
    "mAh": "_milliamp_hours",
    "Wh": "_watt_hours",
    "MHz": "_megahertz",
    "MB": "_megabytes",
    "GB": "_gigabytes",
    "Mbps": "_mbps",
    "dB": "_decibels",
    "ms": "_milliseconds",
    "s": "_seconds",
    "lux": "_lux",
    "K": "_kelvin",
}

_PROM_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def _to_prometheus_name(key: str, unit: str | None) -> str:
    """Convert a metric key like ``cpu.temperature`` to ``desk2ha_cpu_temperature_celsius``."""
    name = "desk2ha_" + _PROM_NAME_RE.sub("_", key)
    # Collapse consecutive underscores
    while "__" in name:
        name = name.replace("__", "_")
    name = name.strip("_")
    if unit and unit in _UNIT_SUFFIX_MAP:
        suffix = _UNIT_SUFFIX_MAP[unit]
        if not name.endswith(suffix):
            name += suffix
    return name


def _extract_metric_value(
    raw: Any,
) -> tuple[int | float | str | bool | None, str | None]:
    """Extract numeric/string value and unit from a state entry."""
    if isinstance(raw, dict):
        val = raw.get("value")
        unit = raw.get("unit")
        return val, unit
    # Raw scalar stored directly
    if isinstance(raw, (int, float, str, bool)):
        return raw, None
    return None, None


def _extract_labels(key: str, device_key: str, hostname: str) -> str:
    """Build Prometheus label string for nested metric keys."""
    labels = f'device_key="{device_key}",hostname="{hostname}"'
    parts = key.split(".")

    # display.0.brightness → device="display_0"
    # peripheral.usb_046d_c900.battery → device="peripheral_usb_046d_c900"
    # audio.speakers.volume → device="audio_speakers"
    if len(parts) >= 3 and parts[0] in (
        "display",
        "peripheral",
        "audio",
        "webcam",
    ):
        device_id = f"{parts[0]}_{parts[1]}"
        labels += f',device="{device_id}"'

    return labels


def _escape_label_value(value: str) -> str:
    """Escape a string for use as a Prometheus label value."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
