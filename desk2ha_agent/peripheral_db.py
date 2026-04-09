"""Known peripheral database for device identification and grouping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeripheralSpec:
    """Specification for a known peripheral."""

    manufacturer: str
    model: str
    device_type: str
    """keyboard, mouse, headset, earbuds, dock, webcam, light, receiver, ethernet, speakerphone."""
    parent_vid_pid: str | None = None  # VID:PID of parent device (for composite/embedded chips)
    suppress: bool = False  # Don't show as standalone device (e.g. receiver, embedded chip)


# Key = "VID:PID" in lowercase hex, zero-padded to 4 digits
KNOWN_PERIPHERALS: dict[str, PeripheralSpec] = {
    # Dell peripherals (VID 413c)
    "413c:2119": PeripheralSpec("Dell", "Universal Receiver", "receiver", suppress=True),
    "413c:b091": PeripheralSpec("Dell", "Universal Receiver", "receiver", suppress=True),
    "413c:c015": PeripheralSpec("Dell", "Webcam WB7022", "webcam"),
    "413c:b0a6": PeripheralSpec("Dell", "Webcam WB7022", "webcam"),
    "413c:d001": PeripheralSpec("Dell", "KM7321W Keyboard", "keyboard"),
    # VIA Labs USB hub chip (inside Dell DA305 and other docks)
    "2109:8884": PeripheralSpec("Dell", "DA305 USB-C Hub", "dock"),
    "2109:2822": PeripheralSpec("Dell", "DA305 USB-C Hub", "dock"),
    # ASIX (commonly embedded in Dell docks)
    "0b95:1790": PeripheralSpec(
        "ASIX",
        "AX88179 Ethernet",
        "ethernet",
        parent_vid_pid="2109:8884",
        suppress=True,
    ),
    # Logitech
    "046d:c900": PeripheralSpec("Logitech", "Litra Glow", "light"),
    "046d:c901": PeripheralSpec("Logitech", "Litra Beam", "light"),
    "046d:c548": PeripheralSpec("Logitech", "Bolt Receiver", "receiver", suppress=True),
    "046d:c52b": PeripheralSpec("Logitech", "Unifying Receiver", "receiver", suppress=True),
    # Jabra / GN Audio
    "0b0e:24f1": PeripheralSpec("Jabra", "Speak2 75", "speakerphone"),
    "0b0e:0412": PeripheralSpec("Jabra", "Speak2 75", "speakerphone"),
    "0b0e:0a00": PeripheralSpec("Jabra", "Link 380", "receiver", suppress=True),
}

# VID-only manufacturer lookup (fallback when full VID:PID not in database)
VID_MANUFACTURERS: dict[str, str] = {
    "413c": "Dell",
    "046d": "Logitech",
    "0b0e": "Jabra",
    "0b95": "ASIX",
    "045e": "Microsoft",
    "04f2": "Chicony",
    "8087": "Intel",
    "1532": "Razer",
    "1038": "SteelSeries",
    "1b1c": "Corsair",
    "17ef": "Lenovo",
    "03f0": "HP",
    "0bda": "Realtek",
    "2109": "VIA Labs",
}

# Additional generic USB device name patterns to filter out
GENERIC_USB_PATTERNS: set[str] = {
    "usb-massenspeichergerät",
    "usb-massenspeichergerat",
    "usb mass storage",
    "kompatibles usb-speichergerät",
    "kompatibles usb-speichergerat",
    "compatible usb storage",
    "winusb-gerät",
    "winusb-gerat",
    "winusb device",
    "usb-eingabegerät",
    "usb-eingabegerat",
    "usb input device",
    "usb-verbundgerät",
    "usb-verbundgerat",
    "usb composite device",
}


def lookup_peripheral(vid_pid: str) -> PeripheralSpec | None:
    """Look up a peripheral by VID:PID string (e.g. '413c:b06e')."""
    return KNOWN_PERIPHERALS.get(vid_pid.lower())


def lookup_manufacturer(vid: str) -> str | None:
    """Look up manufacturer by VID string (e.g. '413c')."""
    return VID_MANUFACTURERS.get(vid.lower())


def is_generic_name(name: str) -> bool:
    """Check if a device name matches known generic/driver patterns."""
    return name.lower().strip() in GENERIC_USB_PATTERNS
