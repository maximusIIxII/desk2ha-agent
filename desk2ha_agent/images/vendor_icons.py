"""Tier 2 product images: vendor-specific device silhouettes.

More detailed SVG silhouettes keyed by manufacturer + model pattern.
Falls back to Tier 1 generic icons if no vendor match found.
"""

from __future__ import annotations

import re
from typing import Any

from desk2ha_agent.images.device_icons import get_device_icon_svg

# Vendor-specific SVG silhouettes (48x48 viewBox for more detail)
# Keyed by (manufacturer_pattern, model_pattern) -> SVG
_VENDOR_ICONS: list[tuple[str, str, str, str]] = [
    # (manufacturer_regex, model_regex, device_type, svg)
    # Dell Precision mobile workstations
    (
        r"dell",
        r"precision.*(5\d{3}|7\d{3})",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#1565C0" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#E3F2FD"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#90CAF9"/>'
        '<text x="24" y="17" text-anchor="middle" font-size="4" fill="#1565C0" font-family="sans-serif">DELL</text>'
        "</svg>",
    ),
    # Dell Latitude
    (
        r"dell",
        r"latitude",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#1565C0" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#E3F2FD"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#BBDEFB"/>'
        '<text x="24" y="17" text-anchor="middle" font-size="4" fill="#1565C0" font-family="sans-serif">DELL</text>'
        "</svg>",
    ),
    # Dell OptiPlex
    (
        r"dell",
        r"optiplex",
        "desktop",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="14" y="4" width="20" height="36" rx="2" fill="none" stroke="#1565C0" stroke-width="1.5"/>'
        '<rect x="17" y="7" width="14" height="3" rx="0.5" fill="#E3F2FD"/>'
        '<circle cx="24" cy="16" r="3" fill="#90CAF9"/>'
        '<rect x="17" y="28" width="14" height="1.5" rx="0.3" fill="#90CAF9"/>'
        '<rect x="17" y="31" width="14" height="1.5" rx="0.3" fill="#90CAF9"/>'
        '<circle cx="24" cy="38" r="1" fill="#1565C0"/>'
        '<rect x="16" y="42" width="16" height="2" rx="0.5" fill="#90CAF9"/>'
        "</svg>",
    ),
    # Dell UltraSharp monitors
    (
        r"dell",
        r"u\d{4}",
        "monitor",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="2" y="2" width="44" height="30" rx="1.5" fill="none" stroke="#1565C0" stroke-width="1.5"/>'
        '<rect x="4" y="4" width="40" height="26" rx="0.5" fill="#E3F2FD"/>'
        '<rect x="20" y="33" width="8" height="6" fill="#90CAF9"/>'
        '<rect x="14" y="39" width="20" height="3" rx="1" fill="#BBDEFB"/>'
        "</svg>",
    ),
    # HP EliteBook
    (
        r"hp|hewlett",
        r"elitebook",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#0096D6" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#E1F5FE"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#B3E5FC"/>'
        '<text x="24" y="17" text-anchor="middle" font-size="4" fill="#0096D6" font-family="sans-serif">hp</text>'
        "</svg>",
    ),
    # HP ZBook
    (
        r"hp|hewlett",
        r"zbook",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#0096D6" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#E1F5FE"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#81D4FA"/>'
        '<text x="24" y="17" text-anchor="middle" font-size="4" fill="#0096D6" font-family="sans-serif">hp</text>'
        "</svg>",
    ),
    # Lenovo ThinkPad
    (
        r"lenovo",
        r"thinkpad",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#333333" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#F5F5F5"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#424242"/>'
        '<circle cx="40" cy="6" r="1.5" fill="#E53935"/>'
        "</svg>",
    ),
    # Lenovo ThinkStation
    (
        r"lenovo",
        r"thinkstation",
        "workstation",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="12" y="2" width="24" height="40" rx="2" fill="none" stroke="#333333" stroke-width="1.5"/>'
        '<rect x="15" y="5" width="18" height="4" rx="0.5" fill="#F5F5F5"/>'
        '<circle cx="24" cy="15" r="4" fill="#E0E0E0"/>'
        '<rect x="15" y="26" width="18" height="1.5" rx="0.3" fill="#BDBDBD"/>'
        '<rect x="15" y="29" width="18" height="1.5" rx="0.3" fill="#BDBDBD"/>'
        '<rect x="15" y="32" width="18" height="1.5" rx="0.3" fill="#BDBDBD"/>'
        '<circle cx="36" cy="4" r="1" fill="#E53935"/>'
        '<rect x="14" y="44" width="20" height="2" rx="0.5" fill="#424242"/>'
        "</svg>",
    ),
    # Apple MacBook
    (
        r"apple",
        r"macbook",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="3" fill="none" stroke="#A0A0A0" stroke-width="1.2"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1.5" fill="#F5F5F5"/>'
        '<path d="M2 32 L46 32 L44 34 L4 34 Z" fill="#C0C0C0"/>'
        '<circle cx="24" cy="17" r="2" fill="#C0C0C0"/>'
        "</svg>",
    ),
    # Generic Dell (any other Dell product)
    (
        r"dell",
        r".*",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#1565C0" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#E3F2FD"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#BBDEFB"/>'
        "</svg>",
    ),
    # Generic HP
    (
        r"hp|hewlett",
        r".*",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#0096D6" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#E1F5FE"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#B3E5FC"/>'
        "</svg>",
    ),
    # Generic Lenovo
    (
        r"lenovo",
        r".*",
        "notebook",
        '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="4" width="36" height="26" rx="2" fill="none" stroke="#333333" stroke-width="1.5"/>'
        '<rect x="9" y="7" width="30" height="20" rx="1" fill="#F5F5F5"/>'
        '<path d="M2 32 L46 32 L42 36 L6 36 Z" fill="#616161"/>'
        "</svg>",
    ),
]


def get_vendor_icon_svg(manufacturer: str, model: str, device_type: str = "notebook") -> str:
    """Return the best-matching vendor-specific SVG icon.

    Checks manufacturer + model against known patterns. Falls back to
    Tier 1 generic icons if no vendor match is found.
    """
    mfg_lower = manufacturer.lower().strip()
    model_lower = model.lower().strip()

    for mfg_pattern, model_pattern, _dtype, svg in _VENDOR_ICONS:
        if re.search(mfg_pattern, mfg_lower) and re.search(model_pattern, model_lower):
            return svg

    # Tier 1 fallback
    return get_device_icon_svg(device_type)


def get_device_image(hw_info: dict[str, Any]) -> str:
    """Get the best available device image from hardware info.

    This is the main entry point for the product image system.
    Tries Tier 2 (vendor) first, then falls back to Tier 1 (generic).
    """
    manufacturer = hw_info.get("manufacturer", "")
    model = hw_info.get("model", "")
    device_type = hw_info.get("device_type", "notebook")

    return get_vendor_icon_svg(manufacturer, model, device_type)
