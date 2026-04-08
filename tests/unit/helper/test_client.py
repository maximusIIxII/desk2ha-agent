"""Tests for the helper HTTP client."""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from desk2ha_agent.helper.client import HelperClient


def test_default_url():
    client = HelperClient()
    assert client._base_url == "http://127.0.0.1:9694"


def test_custom_url():
    client = HelperClient(port=9999, host="192.168.1.1")
    assert client._base_url == "http://192.168.1.1:9999"


@pytest.mark.asyncio
async def test_is_available_with_real_server():
    """Test is_available against a real aiohttp test server."""
    app = web.Application()
    app.router.add_get("/health", lambda _: web.json_response({"status": "ok"}))

    async with TestClient(TestServer(app)) as tc:
        port = tc.port
        client = HelperClient(port=port)
        result = await client.is_available()
        assert result is True
        assert client._available is True


@pytest.mark.asyncio
async def test_get_metrics_with_real_server():
    """Test get_metrics against a real aiohttp test server."""
    metrics = {"cpu_package": {"value": 55.0, "unit": "Cel"}}
    app = web.Application()
    app.router.add_get("/metrics", lambda _: web.json_response(metrics))

    async with TestClient(TestServer(app)) as tc:
        client = HelperClient(port=tc.port)
        result = await client.get_metrics()
        assert result["cpu_package"]["value"] == 55.0


@pytest.mark.asyncio
async def test_is_available_connection_refused():
    client = HelperClient(port=1)
    result = await client.is_available()
    assert result is False
    assert client._available is False


@pytest.mark.asyncio
async def test_get_metrics_connection_refused():
    client = HelperClient(port=1)
    client._available = True
    result = await client.get_metrics()
    assert result == {}
    assert client._available is False
