"""aiohttp server implementing the OpenAPI v2.0.0 spec."""

from __future__ import annotations

import logging
import platform
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import web

from desk2ha_agent import __version__
from desk2ha_agent.transport.base import Transport

if TYPE_CHECKING:
    from desk2ha_agent.collector.base import DeviceInfoProvider
    from desk2ha_agent.config import HttpConfig
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
    ) -> None:
        self._config = config
        self._state = state
        self._scheduler = scheduler
        self._info_provider = info_provider
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
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._config.bind, self._config.port)
        await site.start()
        logger.info(
            "HTTP transport listening on %s:%d",
            self._config.bind,
            self._config.port,
        )

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

        Uses Tier 2 vendor-specific icons when manufacturer/model is known,
        falls back to Tier 1 generic device type icons.
        """
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
