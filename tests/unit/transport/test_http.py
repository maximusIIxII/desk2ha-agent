"""Tests for the HTTP transport."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from desk2ha_agent.collector.base import Collector, CollectorMeta, CollectorTier, Platform
from desk2ha_agent.config import HttpConfig
from desk2ha_agent.scheduler import Scheduler
from desk2ha_agent.state import StateCache
from desk2ha_agent.transport.http import HttpTransport

_TEST_TOKEN = "test-secret-token"


class _StubCollector(Collector):
    meta = CollectorMeta(
        name="stub",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.ANY},
        capabilities={"thermals"},
        description="stub collector for tests",
    )

    async def probe(self) -> bool:
        return True

    async def setup(self) -> None:
        pass

    async def collect(self) -> dict[str, Any]:
        return {}

    async def teardown(self) -> None:
        pass


def _make_transport() -> HttpTransport:
    config = HttpConfig(enabled=True, auth_token=_TEST_TOKEN)
    state = StateCache()
    scheduler = Scheduler(collectors=[_StubCollector()], state=state)
    return HttpTransport(config=config, state=state, scheduler=scheduler)


@pytest.fixture
async def client():
    transport = _make_transport()
    async with TestClient(TestServer(transport.app)) as c:
        yield c


async def test_health_no_auth(client: TestClient) -> None:
    """Health endpoint should return 200 without auth."""
    resp = await client.get("/v1/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] in ("ok", "degraded")
    assert data["schema_version"] == "2.0.0"


async def test_info_requires_auth(client: TestClient) -> None:
    """Info endpoint should return 401 without auth."""
    resp = await client.get("/v1/info")
    assert resp.status == 401


async def test_info_with_auth(client: TestClient) -> None:
    """Info endpoint should return 200 with correct Bearer token."""
    resp = await client.get(
        "/v1/info",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["schema_version"] == "2.0.0"
    assert "device_key" in data
    assert "collectors" in data
    assert "peripherals" in data
    assert "capabilities" in data


async def test_metrics_returns_device_key_and_schema(client: TestClient) -> None:
    """Metrics endpoint should return device_key and schema_version."""
    resp = await client.get(
        "/v1/metrics",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["schema_version"] == "2.0.0"
    assert "device_key" in data
    assert "snapshot_timestamp" in data
