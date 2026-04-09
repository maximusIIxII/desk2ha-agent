"""Entry point: python -m desk2ha_agent.helper (or desk2ha-helper CLI)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import logging.handlers
import os
import secrets
import signal
import sys
from pathlib import Path

from desk2ha_agent import __version__
from desk2ha_agent.helper.server import DEFAULT_PORT, HELPER_SECRET_ENV, ElevatedHelper

logger = logging.getLogger("desk2ha_agent.helper")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="desk2ha-helper",
        description="Desk2HA Elevated Helper — privileged metric collector",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--bind",
        "-b",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Log directory (default: current directory)",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"desk2ha-helper {__version__}",
    )
    return parser.parse_args(argv)


def _setup_logging(log_dir: Path | None) -> None:
    log_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(log_fmt)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "desk2ha-helper.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(log_fmt)
        root.addHandler(file_handler)


def _check_admin() -> bool:
    """Check if running with admin/root privileges."""
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        import os

        return os.geteuid() == 0


async def _run(port: int, bind: str) -> None:
    if not _check_admin():
        logger.warning(
            "Helper is NOT running with admin privileges — elevated collectors may not work"
        )

    # Generate a shared secret if not already set (e.g. by a parent process)
    if not os.environ.get(HELPER_SECRET_ENV):
        generated_secret = secrets.token_urlsafe(32)
        os.environ[HELPER_SECRET_ENV] = generated_secret
        logger.info(
            "Generated helper auth secret — set %s env var in the agent to connect",
            HELPER_SECRET_ENV,
        )

    helper = ElevatedHelper(port=port, bind=bind)
    await helper.start()

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    else:
        signal.signal(signal.SIGINT, lambda *_: _signal_handler())
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, lambda *_: _signal_handler())

    with contextlib.suppress(KeyboardInterrupt):
        await stop_event.wait()

    await helper.stop()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _setup_logging(args.log_dir)
    logger.info("Desk2HA Helper %s starting on %s:%d", __version__, args.bind, args.port)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(args.port, args.bind))


if __name__ == "__main__":
    main()
