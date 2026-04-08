"""Tests for collector base classes."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)


class DummyCollector(Collector):
    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="dummy",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.ANY},
        capabilities={"presence"},
        description="Test collector",
    )

    async def probe(self) -> bool:
        return True

    async def setup(self) -> None:
        pass

    async def collect(self) -> dict[str, Any]:
        return {"test": metric_value(42.0, unit="Cel")}

    async def teardown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_dummy_collector_probe():
    c = DummyCollector()
    assert await c.probe() is True


@pytest.mark.asyncio
async def test_dummy_collector_collect():
    c = DummyCollector()
    result = await c.collect()
    assert "test" in result
    assert result["test"]["value"] == 42.0
    assert result["test"]["unit"] == "Cel"


def test_metric_value():
    mv = metric_value(23.5, unit="Cel")
    assert mv["value"] == 23.5
    assert mv["unit"] == "Cel"
    assert "timestamp" in mv
    assert mv.get("stale") is None

    mv_stale = metric_value(None, stale=True)
    assert mv_stale["stale"] is True


@pytest.mark.asyncio
async def test_collector_command_not_implemented():
    c = DummyCollector()
    with pytest.raises(NotImplementedError):
        await c.execute_command("foo", "bar", {})
