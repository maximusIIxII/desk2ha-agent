"""USB device enumeration collector.

Lists all connected USB devices with manufacturer, model, and VID/PID.
Reports them as peripheral metrics for HA entity creation.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

# USB devices to skip (hubs, controllers, internal chipsets)
_SKIP_NAMES = {
    "hub",
    "controller",
    "root",
    "billboard",
    "ucm-ucsi",
}

_SKIP_VIDS = {
    "8087",  # Intel internal (Bluetooth chipset)
    "27C6",  # Goodix fingerprint
}

# VID:PID pairs handled by dedicated collectors (skip in USB enum)
_SKIP_VID_PIDS = {
    # Logitech Litra (logitech_litra collector)
    "046D:C900",  # Litra Glow
    "046D:C901",  # Litra Beam
    "FFFF:BACE",  # Litra Glow (G HUB virtual device)
    # Wireless receivers (wireless_receiver collector)
    "413C:2119",  # Dell Universal Receiver
    "413C:2141",  # Dell Universal Receiver v2
    "046D:C548",  # Logitech Bolt Receiver
    "046D:C52B",  # Logitech Unifying Receiver
    "046D:C534",  # Logitech Nano Receiver
    "046D:C545",  # Logitech Lightspeed Receiver
    "0B0E:245D",  # Jabra Link 380
    "0B0E:2481",  # Jabra Link 390
}

# Known VID:PID → friendly name + manufacturer
# Model names should NOT include manufacturer (HA adds it automatically)
_KNOWN_DEVICES: dict[str, tuple[str, str]] = {
    "0B0E:24F1": ("Speak2 75", "Jabra"),
    "0B0E:2483": ("Engage 50 II", "Jabra"),
    "0B0E:245E": ("Evolve2 85", "Jabra"),
    "0B0E:2466": ("Evolve2 75", "Jabra"),
    "413C:C015": ("Webcam WB7022", "Dell"),
    "413C:C011": ("Webcam WB5023", "Dell"),
    "413C:2119": ("Universal Receiver", "Dell"),
    "413C:D001": ("KM7321W Keyboard", "Dell"),
    "046D:C900": ("Bolt Receiver", "Logitech"),
    "046D:C548": ("Unifying Receiver", "Logitech"),
    "046D:C52B": ("Unifying Receiver", "Logitech"),
    "046D:0A87": ("Zone Wireless", "Logitech"),
    "1532:0084": ("DeathAdder V2", "Razer"),
    "1532:026F": ("Huntsman V3", "Razer"),
    "1038:12AD": ("Arctis Nova 7", "SteelSeries"),
    "1B1C:1B65": ("HS80 RGB", "Corsair"),
}


_GENERIC_NAMES = {
    "usb-eingabe",
    "usb-verbund",
    "usb input",
    "usb composite",
}


def _is_generic_name(name: str) -> bool:
    """Check if USB device name is generic/unhelpful."""
    lower = name.lower()
    return any(g in lower for g in _GENERIC_NAMES)


class USBDeviceCollector(Collector):
    """Enumerate connected USB devices."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="usb_devices",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX},
        capabilities={"peripheral", "inventory"},
        description="USB device enumeration (peripherals, webcams, docks)",
    )

    async def probe(self) -> bool:
        if sys.platform == "win32":
            try:
                import wmi  # noqa: F401

                return True
            except ImportError:
                return False
        if sys.platform == "linux":
            from pathlib import Path

            return Path("/sys/bus/usb/devices").exists()
        return False

    async def setup(self) -> None:
        logger.info("USB device enumeration collector activated")

    async def collect(self) -> dict[str, Any]:
        if sys.platform == "win32":
            return await asyncio.to_thread(self._collect_windows)
        if sys.platform == "linux":
            return self._collect_linux()
        return {}

    def _collect_windows(self) -> dict[str, Any]:
        import pythoncom
        import wmi

        pythoncom.CoInitialize()
        try:
            conn = wmi.WMI()
            pnp = conn.Win32_PnPEntity()
            metrics: dict[str, Any] = {}
            idx = 0

            for dev in pnp:
                did = getattr(dev, "DeviceID", "") or ""
                if not did.startswith("USB\\"):
                    continue

                name = getattr(dev, "Name", "") or ""
                if not name:
                    continue

                # Skip internal/generic devices
                name_lower = name.lower()
                if any(s in name_lower for s in _SKIP_NAMES):
                    continue
                if "composite" in name_lower or "generic" in name_lower:
                    continue

                # Extract VID/PID
                vid, pid = "", ""
                for part in did.split("\\"):
                    if "VID_" in part:
                        for segment in part.split("&"):
                            if segment.startswith("VID_"):
                                vid = segment[4:]
                            elif segment.startswith("PID_"):
                                pid = segment[4:]

                if vid.upper() in _SKIP_VIDS:
                    continue
                vid_pid_key = f"{vid.upper()}:{pid.upper()}"
                if vid_pid_key in _SKIP_VID_PIDS:
                    continue

                # Skip interface sub-devices (MI_01, MI_02, etc.)
                if "&MI_" in did and not did.endswith("MI_00"):
                    continue

                mfg = getattr(dev, "Manufacturer", "") or ""

                # Use known device lookup for friendly names
                known = _KNOWN_DEVICES.get(vid_pid_key)
                if known:
                    friendly_name, friendly_mfg = known
                else:
                    friendly_name = name
                    friendly_mfg = mfg

                # Skip remaining generic USB devices without known mapping
                if not known and _is_generic_name(friendly_name):
                    continue

                # Skip generic Windows driver names as manufacturer
                if friendly_mfg.startswith("(Standard"):
                    friendly_mfg = ""

                prefix = f"peripheral.usb_{idx}"
                metrics[f"{prefix}.model"] = metric_value(friendly_name)
                if friendly_mfg:
                    metrics[f"{prefix}.manufacturer"] = metric_value(friendly_mfg)
                if vid and pid:
                    metrics[f"{prefix}.vid_pid"] = metric_value(vid_pid_key)

                idx += 1

            logger.debug("USB enumeration: found %d devices", idx)
            return metrics

        except Exception:
            logger.debug("USB enumeration failed", exc_info=True)
            return {}
        finally:
            pythoncom.CoUninitialize()

    def _collect_linux(self) -> dict[str, Any]:
        from pathlib import Path

        metrics: dict[str, Any] = {}
        idx = 0
        usb_path = Path("/sys/bus/usb/devices")

        for dev_dir in usb_path.iterdir():
            product_file = dev_dir / "product"
            if not product_file.exists():
                continue

            try:
                product = product_file.read_text().strip()
                if not product:
                    continue

                manufacturer = ""
                mfg_file = dev_dir / "manufacturer"
                if mfg_file.exists():
                    manufacturer = mfg_file.read_text().strip()

                vid_file = dev_dir / "idVendor"
                pid_file = dev_dir / "idProduct"
                vid = vid_file.read_text().strip() if vid_file.exists() else ""
                pid = pid_file.read_text().strip() if pid_file.exists() else ""

                if vid.upper() in _SKIP_VIDS:
                    continue

                prefix = f"peripheral.usb_{idx}"
                metrics[f"{prefix}.model"] = metric_value(product)
                if manufacturer:
                    metrics[f"{prefix}.manufacturer"] = metric_value(manufacturer)
                if vid and pid:
                    metrics[f"{prefix}.vid_pid"] = metric_value(f"{vid}:{pid}")
                idx += 1

            except Exception:
                continue

        return metrics

    async def teardown(self) -> None:
        pass


COLLECTOR_CLASS = USBDeviceCollector
