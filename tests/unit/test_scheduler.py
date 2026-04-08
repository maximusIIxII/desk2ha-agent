"""Tests for the Scheduler."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)
from desk2ha_agent.scheduler import Scheduler
from desk2ha_agent.state import StateCache


class FastCollector(Collector):
    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="fast",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.ANY},
        capabilities={"presence"},
        description="Test",
    )
    call_count: int = 0

    async def probe(self) -> bool:
        return True

    async def setup(self) -> None:
        pass

    async def collect(self) -> dict[str, Any]:
        self.call_count += 1
        return {"test": metric_value(self.call_count)}

    async def teardown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_scheduler_runs_collector():
    state = StateCache()
    collector = FastCollector()
    scheduler = Scheduler([collector], state, intervals={"fast": 0.1})

    await scheduler.start()
    assert scheduler.running

    await asyncio.sleep(0.35)
    await scheduler.stop()

    assert collector.call_count >= 2
    snap = await state.snapshot()
    assert "test" in snap
