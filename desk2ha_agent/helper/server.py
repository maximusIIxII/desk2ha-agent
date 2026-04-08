"""Elevated helper HTTP server.

Runs as a separate process with admin privileges and exposes metrics
that require elevation (e.g. Dell DCM WMI) via localhost HTTP.

The main agent queries this helper instead of accessing WMI directly,
keeping the agent itself running as a normal user.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from aiohttp import web

from desk2ha_agent import __version__
from desk2ha_agent.collector.base import Collector

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9694
COLLECT_INTERVAL = 30.0


class ElevatedHelper:
    """Collects metrics from elevated-only collectors and serves them via HTTP."""

    def __init__(self, port: int = DEFAULT_PORT, bind: str = "127.0.0.1") -> None:
        self._port = port
        self._bind = bind
        self._collectors: list[Collector] = []
        self._metrics: dict[str, Any] = {}
        self._last_collect: float = 0.0
        self._collect_task: asyncio.Task[None] | None = None
        self._runner: web.AppRunner | None = None

    async def discover_collectors(self) -> None:
        """Probe and activate collectors that need elevation."""
        from desk2ha_agent.helper.registry import ELEVATED_MODULES

        for module_path in ELEVATED_MODULES:
            try:
                import importlib

                mod = importlib.import_module(module_path)
                cls = getattr(mod, "COLLECTOR_CLASS", None)
                if cls is None:
                    continue

                instance = cls()
                if await instance.probe():
                    await instance.setup()
                    self._collectors.append(instance)
                    logger.info("Helper: activated %s", instance.meta.name)
                else:
                    logger.info("Helper: %s not available", instance.meta.name)
            except Exception:
                logger.debug("Helper: failed to load %s", module_path, exc_info=True)

        logger.info("Helper: %d collector(s) active", len(self._collectors))

    async def start(self) -> None:
        """Start the helper HTTP server and collection loop."""
        await self.discover_collectors()

        # Initial collection
        await self._collect_once()

        # Start periodic collection
        self._collect_task = asyncio.create_task(self._collect_loop(), name="helper-collect")

        # Start HTTP server
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._bind, self._port)
        await site.start()
        logger.info("Helper listening on %s:%d", self._bind, self._port)

    async def stop(self) -> None:
        """Stop the helper."""
        if self._collect_task is not None:
            self._collect_task.cancel()

        if self._runner is not None:
            await self._runner.cleanup()

        for c in self._collectors:
            try:
                await c.teardown()
            except Exception:
                logger.debug("Teardown failed for %s", c.meta.name, exc_info=True)

        logger.info("Helper stopped")

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
        return app

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "agent_version": __version__,
                "collectors": [c.meta.name for c in self._collectors],
                "last_collect": self._last_collect,
            }
        )

    async def _handle_metrics(self, _request: web.Request) -> web.Response:
        return web.json_response(self._metrics)

    async def _collect_once(self) -> None:
        """Run all elevated collectors and merge metrics."""
        merged: dict[str, Any] = {}
        for collector in self._collectors:
            try:
                result = await collector.collect()
                merged.update(result)
            except Exception:
                logger.debug("Helper collect failed for %s", collector.meta.name, exc_info=True)
        self._metrics = merged
        self._last_collect = time.time()
        logger.debug("Helper collected %d metrics", len(merged))

    async def _collect_loop(self) -> None:
        """Periodically collect metrics."""
        while True:
            await asyncio.sleep(COLLECT_INTERVAL)
            await self._collect_once()
