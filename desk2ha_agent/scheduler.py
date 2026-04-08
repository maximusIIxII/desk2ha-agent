"""Periodic collector scheduler with per-collector intervals."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from desk2ha_agent.collector.base import Collector
    from desk2ha_agent.state import StateCache

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 30.0


class Scheduler:
    """Runs collectors on periodic schedules and writes results to state."""

    def __init__(
        self,
        collectors: Sequence[Collector],
        state: StateCache,
        intervals: dict[str, float] | None = None,
    ) -> None:
        self._collectors = list(collectors)
        self._state = state
        self._intervals = intervals or {}
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def collectors(self) -> list[Collector]:
        return self._collectors

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self._tasks)

    async def start(self) -> None:
        for collector in self._collectors:
            interval = self._intervals.get(
                collector.meta.name, DEFAULT_INTERVAL
            )
            task = asyncio.create_task(
                self._poll_loop(collector, interval),
                name=f"scheduler-{collector.meta.name}",
            )
            self._tasks.append(task)
            logger.info(
                "Started collector %s (interval=%.0fs)", collector.meta.name, interval
            )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("All collectors stopped")

    async def _poll_loop(self, collector: Collector, interval: float) -> None:
        while True:
            try:
                metrics = await collector.collect()
                if metrics:
                    await self._state.update(metrics)
                    logger.debug(
                        "Collector %s returned %d metrics",
                        collector.meta.name, len(metrics),
                    )
            except Exception:
                logger.exception("Collector %s failed", collector.meta.name)
            await asyncio.sleep(interval)
