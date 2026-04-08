"""Transport base class."""

from __future__ import annotations

import abc


class Transport(abc.ABC):
    """Base class for transports (HTTP, MQTT)."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Start the transport."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop the transport."""
