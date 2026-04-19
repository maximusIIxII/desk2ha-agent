"""Tests for desk2ha_agent.__main__ helpers."""

from __future__ import annotations

import asyncio

import pytest

from desk2ha_agent.__main__ import _wait_for_device_key


class _FakeProvider:
    """DeviceInfoProvider that flips from None to a key after N probe calls."""

    def __init__(self, key: str | None, flip_after_calls: int = 0) -> None:
        self._key = key
        self._flip_after = flip_after_calls
        self._calls = 0

    def get_device_key(self) -> str | None:
        self._calls += 1
        if self._calls > self._flip_after:
            return self._key
        return None

    # Unused abstract-ish surface for Protocol compatibility
    def get_identity(self) -> dict:
        return {}

    def get_hardware(self) -> dict:
        return {}

    def get_os(self) -> dict | None:
        return None


@pytest.mark.asyncio
async def test_wait_returns_immediately_when_key_already_present():
    p = _FakeProvider("ST-ABC")
    key = await _wait_for_device_key(p, timeout=1.0, poll_interval=0.05)
    assert key == "ST-ABC"


@pytest.mark.asyncio
async def test_wait_polls_until_key_resolves():
    # Flip to a key after the first probe — simulates platform collector
    # resolving device_key during its first collect cycle.
    p = _FakeProvider("ST-XYZ", flip_after_calls=1)
    key = await _wait_for_device_key(p, timeout=2.0, poll_interval=0.05)
    assert key == "ST-XYZ"


@pytest.mark.asyncio
async def test_wait_returns_none_on_timeout():
    """If get_device_key() never returns a value, we give up and log a warning.

    The production code continues startup without propagation in that case —
    peripherals stay functional, only connected_host is missing.
    """
    p = _FakeProvider(None)  # never resolves
    start = asyncio.get_running_loop().time()
    key = await _wait_for_device_key(p, timeout=0.2, poll_interval=0.05)
    elapsed = asyncio.get_running_loop().time() - start
    assert key is None
    # Allow some slack but confirm we did not block significantly longer
    assert elapsed < 0.6
