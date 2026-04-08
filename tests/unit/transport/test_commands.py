"""Tests for /v1/commands endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
)
from desk2ha_agent.config import HttpConfig
from desk2ha_agent.scheduler import Scheduler
from desk2ha_agent.state import StateCache
from desk2ha_agent.transport.http import HttpTransport

_TEST_TOKEN = "test-secret-token"
_AUTH = {"Authorization": f"Bearer {_TEST_TOKEN}"}


class _ControlCollector(Collector):
    """Collector that supports commands."""

    meta = CollectorMeta(
        name="test_control",
        tier=CollectorTier.GENERIC,
        platforms={Platform.ANY},
        capabilities={"control", "display"},
        description="test control collector",
    )

    def __init__(self) -> None:
        self.last_command: tuple[str, str, dict[str, Any]] | None = None

    async def probe(self) -> bool:
        return True

    async def setup(self) -> None:
        pass

    async def collect(self) -> dict[str, Any]:
        return {}

    async def teardown(self) -> None:
        pass

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if not command.startswith("display."):
            raise NotImplementedError
        self.last_command = (command, target, parameters)
        return {"status": "completed"}


class _NoCommandCollector(Collector):
    """Collector that does not support commands."""

    meta = CollectorMeta(
        name="readonly",
        tier=CollectorTier.PLATFORM,
        platforms={Platform.ANY},
        capabilities={"thermals"},
        description="read-only collector",
    )

    async def probe(self) -> bool:
        return True

    async def setup(self) -> None:
        pass

    async def collect(self) -> dict[str, Any]:
        return {}

    async def teardown(self) -> None:
        pass


def _make_transport(
    collectors: list[Collector] | None = None,
) -> tuple[HttpTransport, list[Collector]]:
    config = HttpConfig(enabled=True, auth_token=_TEST_TOKEN)
    state = StateCache()
    ctrl = _ControlCollector()
    ro = _NoCommandCollector()
    all_collectors = collectors or [ro, ctrl]
    scheduler = Scheduler(collectors=all_collectors, state=state)
    transport = HttpTransport(config=config, state=state, scheduler=scheduler)
    return transport, all_collectors


@pytest.fixture
async def client():
    transport, _ = _make_transport()
    async with TestClient(TestServer(transport.app)) as c:
        yield c


@pytest.fixture
async def client_with_collectors():
    transport, collectors = _make_transport()
    async with TestClient(TestServer(transport.app)) as c:
        yield c, collectors


async def test_commands_list(client: TestClient) -> None:
    resp = await client.get("/v1/commands", headers=_AUTH)
    assert resp.status == 200
    data = await resp.json()
    assert len(data["commands"]) == 1
    assert data["commands"][0]["collector"] == "test_control"


async def test_command_execute_success(client_with_collectors) -> None:
    client, collectors = client_with_collectors
    resp = await client.post(
        "/v1/commands",
        headers=_AUTH,
        json={
            "command": "display.set_brightness",
            "target": "display.0",
            "parameters": {"value": 50},
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "completed"

    ctrl = [c for c in collectors if isinstance(c, _ControlCollector)][0]
    assert ctrl.last_command == ("display.set_brightness", "display.0", {"value": 50})


async def test_command_not_found(client: TestClient) -> None:
    resp = await client.post(
        "/v1/commands",
        headers=_AUTH,
        json={"command": "nonexistent.command", "target": "", "parameters": {}},
    )
    assert resp.status == 404
    data = await resp.json()
    assert data["error"] == "not_found"


async def test_command_missing_field(client: TestClient) -> None:
    resp = await client.post(
        "/v1/commands",
        headers=_AUTH,
        json={"parameters": {}},
    )
    assert resp.status == 400
