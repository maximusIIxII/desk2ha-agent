"""Tests for the elevated helper server."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from desk2ha_agent.helper.server import ElevatedHelper


@pytest.fixture
def helper():
    return ElevatedHelper(port=0, bind="127.0.0.1")


def test_initial_state(helper):
    assert helper._collectors == []
    assert helper._metrics == {}
    assert helper._last_collect == 0.0


@pytest.mark.asyncio
async def test_collect_once_empty(helper):
    """No collectors → empty metrics."""
    await helper._collect_once()
    assert helper._metrics == {}
    assert helper._last_collect > 0


@pytest.mark.asyncio
async def test_collect_once_with_collector(helper):
    """Collector returns metrics → merged into helper._metrics."""
    mock_collector = MagicMock()
    mock_collector.collect = AsyncMock(
        return_value={"cpu_package": {"value": 55.0, "unit": "Cel"}}
    )
    helper._collectors = [mock_collector]

    await helper._collect_once()

    assert "cpu_package" in helper._metrics
    assert helper._metrics["cpu_package"]["value"] == 55.0


@pytest.mark.asyncio
async def test_collect_once_collector_failure(helper):
    """Collector raises → gracefully returns empty for that collector."""
    good = MagicMock()
    good.collect = AsyncMock(return_value={"fan.cpu": {"value": 1788}})

    bad = MagicMock()
    bad.collect = AsyncMock(side_effect=RuntimeError("WMI failed"))
    bad.meta = MagicMock()
    bad.meta.name = "broken"

    helper._collectors = [bad, good]
    await helper._collect_once()

    # Good collector's metrics should still be there
    assert "fan.cpu" in helper._metrics


@pytest.mark.asyncio
async def test_health_endpoint(helper):
    app = helper._create_app()

    from aiohttp.test_utils import TestClient, TestServer

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "collectors" in data


@pytest.mark.asyncio
async def test_metrics_endpoint(helper):
    helper._metrics = {"cpu_package": {"value": 60.0, "unit": "Cel"}}
    app = helper._create_app()

    from aiohttp.test_utils import TestClient, TestServer

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/metrics")
        assert resp.status == 200
        data = await resp.json()
        assert data["cpu_package"]["value"] == 60.0


@pytest.mark.asyncio
async def test_discover_no_modules(helper):
    with patch("desk2ha_agent.helper.registry.ELEVATED_MODULES", ["fake.nonexistent.module"]):
        await helper.discover_collectors()
    assert helper._collectors == []
