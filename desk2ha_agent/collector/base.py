"""Base classes for the collector framework."""

from __future__ import annotations

import abc
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class Platform(StrEnum):
    """Supported platforms."""

    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ANY = "any"


class CollectorTier(StrEnum):
    """Collector tier in the 3-layer architecture."""

    PLATFORM = "platform"
    GENERIC = "generic"
    VENDOR = "vendor"


@dataclass
class CollectorMeta:
    """Metadata for collector registration and discovery."""

    name: str
    tier: CollectorTier
    platforms: set[Platform]
    capabilities: set[str]
    description: str
    requires_software: str | None = None
    requires_hardware: str | None = None
    optional_dependencies: list[str] = field(default_factory=list)


class Collector(abc.ABC):
    """Abstract base class for all metric collectors."""

    meta: ClassVar[CollectorMeta]

    @abc.abstractmethod
    async def probe(self) -> bool:
        """Check if this collector can run on the current system.

        Called once at startup. Returns True if the collector should be activated.
        Must NOT raise exceptions -- return False on any error.
        """

    @abc.abstractmethod
    async def setup(self) -> None:
        """Initialize the collector after probe() returned True.

        Open connections, start background tasks, etc.
        """

    @abc.abstractmethod
    async def collect(self) -> dict[str, Any]:
        """Collect metrics and return a dict of metric_key -> value.

        Called periodically by the scheduler.
        On partial failure: return available metrics.
        On total failure: return empty dict (don't raise).
        """

    @abc.abstractmethod
    async def teardown(self) -> None:
        """Clean up resources. Called on shutdown."""

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a control command. Override in collectors that support commands."""
        raise NotImplementedError(f"{self.meta.name} does not support commands")


@runtime_checkable
class DeviceInfoProvider(Protocol):
    """Protocol for collectors that provide device identity."""

    def get_identity(self) -> dict[str, Any] | None: ...
    def get_hardware(self) -> dict[str, Any] | None: ...
    def get_os(self) -> dict[str, Any] | None: ...
    def get_device_key(self) -> str | None: ...


@runtime_checkable
class PeripheralProvider(Protocol):
    """Protocol for collectors that discover peripheral devices."""

    def get_peripherals(self) -> list[dict[str, Any]]: ...


def metric_value(
    value: float | str | bool | None,
    unit: str | None = None,
    stale: bool = False,
) -> dict[str, Any]:
    """Create a MetricValue dict with current timestamp."""
    result: dict[str, Any] = {"value": value, "timestamp": time.time()}
    if unit is not None:
        result["unit"] = unit
    if stale:
        result["stale"] = True
    return result
