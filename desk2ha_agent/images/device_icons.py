"""Generic device-type SVG icons for the /v1/image endpoint.

Tier 1 of the 3-tier product image system: simple SVG silhouettes
based on device_type (notebook, desktop, monitor, keyboard, mouse, headset).
"""

from __future__ import annotations

# Minimalist SVG icons (24x24 viewBox, neutral colors)
_ICONS: dict[str, str] = {
    "notebook": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="4" y="3" width="16" height="12" rx="1.5" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<rect x="6" y="5" width="12" height="8" rx="0.5" fill="#E2E8F0"/>'
        '<path d="M2 17 L22 17 L20 19 L4 19 Z" fill="#94A3B8"/>'
        "</svg>"
    ),
    "desktop": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="3" y="2" width="18" height="13" rx="1.5" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<rect x="5" y="4" width="14" height="9" rx="0.5" fill="#E2E8F0"/>'
        '<rect x="10" y="16" width="4" height="3" fill="#94A3B8"/>'
        '<rect x="8" y="19" width="8" height="1.5" rx="0.5" fill="#94A3B8"/>'
        "</svg>"
    ),
    "monitor": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="2" y="2" width="20" height="14" rx="1.5" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<rect x="4" y="4" width="16" height="10" rx="0.5" fill="#E2E8F0"/>'
        '<rect x="10" y="17" width="4" height="3" fill="#94A3B8"/>'
        '<rect x="7" y="20" width="10" height="1.5" rx="0.5" fill="#94A3B8"/>'
        "</svg>"
    ),
    "keyboard": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" y="8" width="22" height="10" rx="2" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<rect x="3" y="10" width="2" height="2" rx="0.3" fill="#94A3B8"/>'
        '<rect x="6" y="10" width="2" height="2" rx="0.3" fill="#94A3B8"/>'
        '<rect x="9" y="10" width="2" height="2" rx="0.3" fill="#94A3B8"/>'
        '<rect x="12" y="10" width="2" height="2" rx="0.3" fill="#94A3B8"/>'
        '<rect x="15" y="10" width="2" height="2" rx="0.3" fill="#94A3B8"/>'
        '<rect x="18" y="10" width="3" height="2" rx="0.3" fill="#94A3B8"/>'
        '<rect x="5" y="14" width="14" height="2" rx="0.3" fill="#94A3B8"/>'
        "</svg>"
    ),
    "mouse": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M8 6 C8 3 10 2 12 2 C14 2 16 3 16 6 L16 16 C16 20 14 22 12 22 C10 22 8 20 8 16 Z" '
        'fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<line x1="12" y1="2" x2="12" y2="10" stroke="#94A3B8" stroke-width="0.8"/>'
        '<circle cx="12" cy="7" r="1.5" fill="#94A3B8"/>'
        "</svg>"
    ),
    "headset": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M6 12 C6 7 8 4 12 4 C16 4 18 7 18 12" fill="none" stroke="#64748B" stroke-width="1.5"/>'
        '<rect x="4" y="12" width="4" height="6" rx="1.5" fill="#94A3B8"/>'
        '<rect x="16" y="12" width="4" height="6" rx="1.5" fill="#94A3B8"/>'
        "</svg>"
    ),
    "dock": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="3" y="8" width="18" height="8" rx="2" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<rect x="5" y="10" width="2" height="4" rx="0.5" fill="#94A3B8"/>'
        '<rect x="8" y="10" width="2" height="4" rx="0.5" fill="#94A3B8"/>'
        '<rect x="11" y="10" width="2" height="4" rx="0.5" fill="#94A3B8"/>'
        '<circle cx="18" cy="12" r="1.5" fill="#03A9F4"/>'
        "</svg>"
    ),
    "webcam": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="12" cy="10" r="7" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<circle cx="12" cy="10" r="3.5" fill="#E2E8F0"/>'
        '<circle cx="12" cy="10" r="1.5" fill="#03A9F4"/>'
        '<rect x="10" y="17" width="4" height="3" fill="#94A3B8"/>'
        '<rect x="8" y="20" width="8" height="1.5" rx="0.5" fill="#94A3B8"/>'
        "</svg>"
    ),
    "speaker": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="12" cy="12" r="9" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<circle cx="12" cy="12" r="4" fill="#E2E8F0"/>'
        '<circle cx="12" cy="12" r="1.5" fill="#03A9F4"/>'
        "</svg>"
    ),
    "light": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="12" cy="9" r="5" fill="none" stroke="#FFC107" stroke-width="1.2"/>'
        '<circle cx="12" cy="9" r="2.5" fill="#FFF9C4"/>'
        '<line x1="12" y1="14" x2="12" y2="18" stroke="#94A3B8" stroke-width="1.5"/>'
        '<rect x="9" y="18" width="6" height="2" rx="1" fill="#94A3B8"/>'
        "</svg>"
    ),
    "workstation": (
        '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="6" y="2" width="12" height="18" rx="1.5" fill="none" stroke="#64748B" stroke-width="1.2"/>'
        '<rect x="8" y="4" width="8" height="2" rx="0.3" fill="#E2E8F0"/>'
        '<circle cx="12" cy="9" r="2" fill="#94A3B8"/>'
        '<rect x="9" y="14" width="6" height="1" rx="0.3" fill="#94A3B8"/>'
        '<rect x="9" y="16" width="6" height="1" rx="0.3" fill="#94A3B8"/>'
        '<rect x="8" y="20" width="8" height="2" rx="0.5" fill="#94A3B8"/>'
        "</svg>"
    ),
}

# Fallback for unknown device types
_DEFAULT = "notebook"


def get_device_icon_svg(device_type: str) -> str:
    """Return an SVG string for the given device type."""
    return _ICONS.get(device_type.lower(), _ICONS[_DEFAULT])


def get_supported_types() -> list[str]:
    """Return all supported device type names."""
    return sorted(_ICONS.keys())
