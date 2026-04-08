"""Thread-safe metric cache shared between collectors and transports."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

OnUpdateCallback = Callable[[dict[str, Any]], None]


class StateCache:
    """Asyncio-safe cache holding the most recent collected values.

    Collectors write via ``update``; transports read via ``snapshot``.
    Registered callbacks are invoked after each update for push-based
    transports like MQTT.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {}
        self._callbacks: list[OnUpdateCallback] = []

    def register_callback(self, callback: OnUpdateCallback) -> None:
        self._callbacks.append(callback)

    def unregister_callback(self, callback: OnUpdateCallback) -> None:
        self._callbacks.remove(callback)

    async def update(self, metrics: dict[str, Any]) -> None:
        async with self._lock:
            self._data.update(metrics)
            snapshot = dict(self._data)

        for cb in self._callbacks:
            try:
                cb(snapshot)
            except Exception:
                logger.exception("State callback failed")

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self._data)
