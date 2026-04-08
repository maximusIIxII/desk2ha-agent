"""Tests for StateCache."""

from __future__ import annotations

import pytest

from desk2ha_agent.state import StateCache


@pytest.mark.asyncio
async def test_update_and_snapshot():
    cache = StateCache()
    await cache.update({"cpu_temp": {"value": 55.0, "timestamp": 1.0}})
    snap = await cache.snapshot()
    assert snap["cpu_temp"]["value"] == 55.0


@pytest.mark.asyncio
async def test_callback_invoked():
    cache = StateCache()
    received = []
    cache.register_callback(lambda data: received.append(data))
    await cache.update({"test": {"value": 1}})
    assert len(received) == 1
    assert "test" in received[0]


@pytest.mark.asyncio
async def test_unregister_callback():
    cache = StateCache()
    received = []
    cb = lambda data: received.append(data)
    cache.register_callback(cb)
    cache.unregister_callback(cb)
    await cache.update({"test": {"value": 1}})
    assert len(received) == 0
