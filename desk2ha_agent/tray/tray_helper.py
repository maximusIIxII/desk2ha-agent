"""System tray icon for Desk2HA Agent (Windows)."""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _create_icon_image() -> Any:
    """Create a tray icon image using Pillow."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    s = size / 16

    # Monitor outline
    draw.rounded_rectangle(
        [1.5 * s, 2.5 * s, 14.5 * s, 11.5 * s],
        radius=int(1.2 * s),
        outline=(200, 200, 200, 255),
        width=max(1, int(1.2 * s)),
    )
    # Left bar (dimmed)
    draw.rounded_rectangle(
        [4 * s, 6 * s, 5.5 * s, 9.5 * s],
        radius=int(0.5 * s),
        fill=(200, 200, 200, 100),
    )
    # Center bar (accent blue)
    draw.rounded_rectangle(
        [7.25 * s, 4.5 * s, 8.75 * s, 9.5 * s],
        radius=int(0.5 * s),
        fill=(3, 169, 244, 255),
    )
    # Right bar (dimmed)
    draw.rounded_rectangle(
        [10.5 * s, 6 * s, 12 * s, 9.5 * s],
        radius=int(0.5 * s),
        fill=(200, 200, 200, 100),
    )
    # Stand
    draw.rounded_rectangle(
        [6 * s, 13 * s, 10 * s, 14 * s],
        radius=int(0.5 * s),
        fill=(200, 200, 200, 255),
    )

    return img


class TrayIcon:
    """System tray icon with menu."""

    def __init__(self, version: str = "?", log_file: Path | None = None) -> None:
        self._version = version
        self._log_file = log_file
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the tray icon in a background thread."""
        try:
            import pystray

            image = _create_icon_image()
            menu = pystray.Menu(
                pystray.MenuItem(
                    f"Desk2HA Agent v{self._version}",
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open Log", self._open_log),
                pystray.MenuItem("Exit", self._exit),
            )

            self._icon = pystray.Icon(
                "desk2ha-agent",
                image,
                f"Desk2HA Agent v{self._version}",
                menu,
            )

            self._thread = threading.Thread(
                target=self._icon.run,
                daemon=True,
                name="tray-icon",
            )
            self._thread.start()
            logger.info("Tray icon started")

        except ImportError:
            logger.debug("pystray not installed — tray icon disabled")
        except Exception:
            logger.debug("Failed to start tray icon", exc_info=True)

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon is not None:
            with contextlib.suppress(Exception):
                self._icon.stop()

    def _open_log(self) -> None:
        """Open the log file in the default editor."""
        if self._log_file and self._log_file.exists():
            if sys.platform == "win32":
                os.startfile(str(self._log_file))  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._log_file)])
            else:
                subprocess.Popen(["xdg-open", str(self._log_file)])

    def _exit(self) -> None:
        """Exit the agent via tray menu."""
        logger.info("Exit requested from tray menu")
        if self._icon:
            self._icon.stop()
        os._exit(0)
