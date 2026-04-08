"""Base classes for the collector framework."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class DeviceInfoProvider(Protocol):
    """Protocol for objects that provide device identification."""

    def device_id(self) -> str: ...
    def device_name(self) -> str: ...
    def device_manufacturer(self) -> str | None: ...
    def device_model(self) -> str | None: ...


class Collector(ABC):
    """Abstract base class for all collectors."""

    name: str = "unnamed"
    default_interval: int = 30  # seconds

    @abstractmethod
    async def probe(self) -> bool:
        """Check if this collector can run on the current system.

        Returns True if the required hardware/software is available.
        """

    @abstractmethod
    async def collect(self) -> dict[str, Any]:
        """Collect metrics and return them as a flat dict.

        Keys should be stable identifiers (e.g. 'cpu_temp', 'battery_level').
        """

    async def setup(self) -> None:
        """One-time setup after probe() succeeds. Override if needed."""

    async def teardown(self) -> None:
        """Cleanup when the collector is stopped. Override if needed."""
