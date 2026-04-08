"""Entry point: python -m desk2ha_agent."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Desk2HA agent."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logger.info("Desk2HA Agent v%s starting", __import__("desk2ha_agent").__version__)
    # TODO: Initialize config, collectors, transports, scheduler
    asyncio.run(_run())


async def _run() -> None:
    """Main async loop."""
    logger.info("Agent running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    main()
