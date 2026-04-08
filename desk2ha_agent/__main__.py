"""Entry point: python -m desk2ha_agent."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import logging.handlers
import signal
import sys
from pathlib import Path

from desk2ha_agent import __version__
from desk2ha_agent.collector.base import DeviceInfoProvider
from desk2ha_agent.config import load_config
from desk2ha_agent.plugin_registry import discover_collectors, get_current_platform
from desk2ha_agent.scheduler import Scheduler
from desk2ha_agent.state import StateCache

logger = logging.getLogger("desk2ha_agent")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="desk2ha_agent",
        description="Desk2HA Agent — multi-vendor desktop telemetry",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        required=True,
        help="Path to TOML configuration file",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"desk2ha-agent {__version__}",
    )
    parser.add_argument(
        "--service",
        action="store_true",
        help="Run as system service (no tray icon, no console hide)",
    )
    return parser.parse_args(argv)


def _hide_console_window() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _setup_logging(config_path: Path, level: str) -> None:
    log_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    console = logging.StreamHandler()
    console.setFormatter(log_fmt)
    root.addHandler(console)

    log_dir = config_path.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "desk2ha-agent.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_fmt)
    root.addHandler(file_handler)


async def _run(config_path: Path, *, service_mode: bool = False) -> None:
    config = load_config(config_path)
    _setup_logging(config_path, config.logging.level)

    logger.info("Desk2HA Agent %s starting", __version__)
    logger.info("Config loaded from %s", config_path)

    # Discover and activate collectors
    platform = get_current_platform()
    disabled = set(config.collectors.disabled)
    collectors = await discover_collectors(platform, disabled)

    if not collectors:
        logger.warning("No collectors activated — agent will serve empty metrics")

    # Find the first DeviceInfoProvider
    info_provider: DeviceInfoProvider | None = None
    for c in collectors:
        if isinstance(c, DeviceInfoProvider):
            info_provider = c
            break

    # Wire components
    state = StateCache()
    intervals = {k: float(v) for k, v in config.collectors.intervals.items()}
    scheduler = Scheduler(collectors, state, intervals)

    # Start collectors
    await scheduler.start()
    await asyncio.sleep(1.0)  # Let collectors gather initial data

    # Start HTTP transport
    http = None
    if config.http.enabled:
        from desk2ha_agent.transport.http import HttpTransport

        http = HttpTransport(config.http, state, scheduler, info_provider)
        await http.start()

    # Start MQTT transport
    mqtt_transport = None
    if config.mqtt.enabled:
        from desk2ha_agent.transport.mqtt import MqttTransport

        mqtt_transport = MqttTransport(config.mqtt, state, info_provider, scheduler)
        await mqtt_transport.start()

    # Zeroconf advertisement (if HTTP enabled)
    zeroconf_adv = None
    if config.http.enabled:
        try:
            from desk2ha_agent.transport.zeroconf import ZeroconfAdvertiser

            zeroconf_adv = ZeroconfAdvertiser(config.http, info_provider)
            await zeroconf_adv.start()
        except ImportError:
            logger.debug("zeroconf not installed — skipping mDNS advertisement")

    # Tray icon (Windows only, interactive mode)
    tray = None
    if sys.platform == "win32" and not service_mode:
        try:
            from desk2ha_agent.tray.tray_helper import TrayIcon

            log_file = config_path.parent / "logs" / "desk2ha-agent.log"
            tray = TrayIcon(version=__version__, log_file=log_file)
            tray.start()
        except ImportError:
            logger.debug("pystray not installed — skipping tray icon")

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

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")

    # Graceful shutdown
    logger.info("Shutting down...")
    if zeroconf_adv is not None:
        await zeroconf_adv.stop()
    if mqtt_transport is not None:
        await mqtt_transport.stop()
    if http is not None:
        await http.stop()
    await scheduler.stop()

    # Teardown collectors
    for c in collectors:
        try:
            await c.teardown()
        except Exception:
            logger.exception("Teardown failed for %s", c.meta.name)

    if tray is not None:
        tray.stop()
    logger.info("Goodbye")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if not args.service:
        _hide_console_window()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(args.config, service_mode=args.service))


if __name__ == "__main__":
    main()
