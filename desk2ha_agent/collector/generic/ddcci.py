"""Cross-platform DDC/CI monitor collector via monitorcontrol.

Reads and controls monitor settings (brightness, contrast, volume, power state,
input source) over the DDC/CI bus. Works on Windows, Linux, and macOS with the
``monitorcontrol`` Python package.
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


# ---------------------------------------------------------------------------
# Standard MCCS input source mapping
# ---------------------------------------------------------------------------

_INPUT_SOURCE_MAP: dict[int, str] = {
    0: "OFF",
    1: "VGA1",
    2: "VGA2",
    3: "DVI1",
    4: "DVI2",
    5: "COMPOSITE1",
    6: "COMPOSITE2",
    7: "SVIDEO1",
    8: "SVIDEO2",
    9: "TUNER1",
    10: "TUNER2",
    11: "TUNER3",
    12: "COMPONENT1",
    13: "COMPONENT2",
    14: "COMPONENT3",
    15: "DP1",
    16: "DP2",
    17: "HDMI1",
    18: "HDMI2",
}

# ---------------------------------------------------------------------------
# Vendor-specific input source extensions (Dell U-series, P-series)
# These codes are NOT part of the MCCS standard and may not work on
# non-Dell monitors.
# ---------------------------------------------------------------------------

_VENDOR_INPUT_SOURCE_EXT: dict[int, str] = {
    19: "HDMI3",
    20: "HDMI4",
    21: "DP3",
    22: "DP4",
    23: "USBC1",
    24: "USBC2",
    25: "THUNDERBOLT",
    26: "THUNDERBOLT2",
}

# Merged map for resolution
_ALL_INPUT_SOURCES: dict[int, str] = {**_INPUT_SOURCE_MAP, **_VENDOR_INPUT_SOURCE_EXT}


def _resolve_input_source(raw: object) -> str:
    """Convert a monitorcontrol input source value to a readable name."""
    if hasattr(raw, "name") and isinstance(raw.name, str):
        return raw.name
    if isinstance(raw, int):
        return _ALL_INPUT_SOURCES.get(raw, f"INPUT_{raw}")
    return str(raw)


def _resolve_input_source_to_raw(name: str) -> int | str:
    """Convert an input source name back to raw VCP value for writing."""
    # Check combined map (reverse lookup)
    for val, label in _ALL_INPUT_SOURCES.items():
        if label == name:
            return val
    # Check monitorcontrol enum
    try:
        from monitorcontrol.monitorcontrol import InputSource

        member = InputSource[name]
        value = member.value
        return int(value) if isinstance(value, int) else str(value)
    except (ImportError, KeyError):
        pass
    # Try as raw integer
    try:
        return int(name)
    except ValueError:
        raise ValueError(f"Unknown input source: {name!r}") from None


def _get_input_source_options() -> list[str]:
    """Return all known input source names (enum + vendor extensions)."""
    names: list[str] = []
    try:
        from monitorcontrol.monitorcontrol import InputSource

        names.extend(e.name for e in InputSource)
    except Exception:
        pass
    for label in _ALL_INPUT_SOURCES.values():
        if label not in names:
            names.append(label)
    return names


# ---------------------------------------------------------------------------
# Standard VCP codes
# ---------------------------------------------------------------------------

_VCP_FACTORY_RESET = 0x04
_VCP_FACTORY_COLOR_RESET = 0x08
_VCP_COLOR_PRESET = 0x14
_VCP_RED_GAIN = 0x16
_VCP_GREEN_GAIN = 0x18
_VCP_BLUE_GAIN = 0x1A
_VCP_VOLUME = 0x62
_VCP_RED_BLACK_LEVEL = 0x6C
_VCP_GREEN_BLACK_LEVEL = 0x6E
_VCP_BLUE_BLACK_LEVEL = 0x70
_VCP_SHARPNESS = 0x87
_VCP_AUDIO_MUTE = 0x8D
_VCP_USAGE_HOURS = 0xC0
_VCP_FIRMWARE_LEVEL = 0xC9
_VCP_POWER_MODE = 0xD6

_POWER_STATE_TO_VCP: dict[str, int] = {
    "on": 0x01,
    "standby": 0x04,
    "off": 0x05,
}
_VCP_TO_POWER_STATE: dict[int, str] = {v: k for k, v in _POWER_STATE_TO_VCP.items()}

# MCCS color preset values (VCP 0x14)
_COLOR_PRESET_MAP: dict[int, str] = {
    1: "sRGB",
    2: "native",
    3: "4000K",
    4: "5000K",
    5: "6500K",
    6: "7500K",
    7: "8200K",
    8: "9300K",
    9: "10000K",
    10: "11500K",
    11: "user1",
    12: "user2",
    13: "user3",
}
_COLOR_PRESET_TO_VCP: dict[str, int] = {v: k for k, v in _COLOR_PRESET_MAP.items()}

# ---------------------------------------------------------------------------
# Vendor-specific VCP codes (Dell proprietary)
# These may not work on non-Dell monitors.
# ---------------------------------------------------------------------------

_VCP_PBP_MODE = 0xE0
_VCP_AUTO_BRIGHTNESS = 0xE3
_VCP_KVM_SELECT = 0xE5
_VCP_AUTO_COLOR_TEMP = 0xE6
_VCP_SMART_HDR = 0xE9
_VCP_POWER_NAP = 0xF0

_KVM_SELECT_MAP: dict[int, str] = {0: "PC1", 1: "PC2", 2: "PC3"}
_KVM_SELECT_TO_VCP: dict[str, int] = {v: k for k, v in _KVM_SELECT_MAP.items()}

_PBP_MODE_MAP: dict[int, str] = {0: "off", 1: "pbp"}
_PBP_MODE_TO_VCP: dict[str, int] = {v: k for k, v in _PBP_MODE_MAP.items()}


# ---------------------------------------------------------------------------
# EDID parsing helpers
# ---------------------------------------------------------------------------


def _parse_edid_descriptor(edid: bytes, tag: int) -> str:
    """Extract a string from an EDID descriptor block by tag byte."""
    for offset in (54, 72, 90, 108):
        block = edid[offset : offset + 18]
        if len(block) < 18:
            continue
        if block[0] == 0 and block[1] == 0 and block[2] == 0 and block[3] == tag:
            raw = block[5:18]
            text = raw.split(b"\x0a", 1)[0].split(b"\x00", 1)[0]
            return text.decode("ascii", errors="ignore").strip()
    return ""


def _edid_manufacturer(edid: bytes) -> str:
    """Decode the 3-letter PNPID from EDID bytes 8-9."""
    if len(edid) < 10:
        return ""
    b1, b2 = edid[8], edid[9]
    c1 = chr(((b1 >> 2) & 0x1F) + 64)
    c2 = chr((((b1 & 0x03) << 3) | ((b2 >> 5) & 0x07)) + 64)
    c3 = chr((b2 & 0x1F) + 64)
    return f"{c1}{c2}{c3}"


_PNPID_TO_MANUFACTURER: dict[str, str] = {
    "DEL": "Dell",
    "SHP": "Sharp",
    "LGD": "LG Display",
    "AUO": "AU Optronics",
    "BOE": "BOE",
    "CMN": "Chimei Innolux",
    "SAM": "Samsung",
    "LEN": "Lenovo",
    "ACR": "Acer",
    "HWP": "HP",
    "BNQ": "BenQ",
}


# ---------------------------------------------------------------------------
# Windows-specific monitor identification via registry EDID
# ---------------------------------------------------------------------------


def _get_active_monitor_instance_ids() -> set[str]:
    """Return currently active (connected) monitor PNP device IDs.

    Primary: WMI ``Win32_DesktopMonitor`` — works under LocalSystem and
    user sessions.  Returns PNPDeviceID strings (e.g.
    ``DISPLAY\\DEL439E\\4&247D66C&0&UID24645``).

    Fallback: SetupAPI ``DIGCF_PRESENT`` + ``CM_Get_DevNode_Status``
    ``DN_STARTED`` check.  SetupAPI can return 0 results under some
    sessions, so WMI is preferred.
    """
    ids = _get_active_monitors_wmi()
    if ids:
        return ids
    return _get_active_monitors_setupapi()


def _get_active_monitors_wmi() -> set[str]:
    """Get active monitor PNP device IDs via WMI.

    Uses ``Win32_PnPEntity`` filtered by ``PNPClass='Monitor'`` which
    correctly includes Thunderbolt/USB-C monitors and excludes
    disconnected ones.  Works under both user sessions and LocalSystem.
    """
    try:
        import pythoncom
        import wmi

        # Ensure COM is initialized — required when called from
        # asyncio.to_thread() worker threads where COM isn't set up.
        pythoncom.CoInitialize()
        try:
            c = wmi.WMI()
            active: set[str] = set()
            for p in c.Win32_PnPEntity(PNPClass="Monitor"):
                pnp_id = p.PNPDeviceID
                if pnp_id:
                    active.add(pnp_id.upper())
            if active:
                logger.debug("WMI found %d active monitor(s): %s", len(active), active)
            return active
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        logger.debug("WMI monitor query failed", exc_info=True)
        return set()


def _get_active_monitors_setupapi() -> set[str]:
    """Get active monitor instance IDs via SetupAPI (fallback)."""
    try:
        import ctypes
        from ctypes import wintypes

        setupapi = ctypes.windll.SetupAPI  # type: ignore[attr-defined]
        cfgmgr = ctypes.windll.CfgMgr32  # type: ignore[attr-defined]
        DIGCF_PRESENT = 0x02
        DN_STARTED = 0x00000008

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        GUID_DEVCLASS_MONITOR = GUID(
            0x4D36E96E,
            0xE325,
            0x11CE,
            (ctypes.c_byte * 8)(0xBF, 0xC1, 0x08, 0x00, 0x2B, 0xE1, 0x03, 0x18),
        )

        hdevinfo = setupapi.SetupDiGetClassDevsW(
            ctypes.byref(GUID_DEVCLASS_MONITOR), None, None, DIGCF_PRESENT
        )
        if hdevinfo == -1:
            return set()

        class SP_DEVINFO_DATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("ClassGuid", ctypes.c_byte * 16),
                ("DevInst", wintypes.DWORD),
                ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
            ]

        active: set[str] = set()
        idx = 0
        while True:
            devinfo = SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(hdevinfo, idx, ctypes.byref(devinfo)):
                break
            idx += 1

            status = wintypes.DWORD(0)
            problem = wintypes.DWORD(0)
            cr = cfgmgr.CM_Get_DevNode_Status(
                ctypes.byref(status), ctypes.byref(problem), devinfo.DevInst, 0
            )
            if cr != 0 or not (status.value & DN_STARTED):
                continue

            buf = ctypes.create_unicode_buffer(512)
            if setupapi.SetupDiGetDeviceInstanceIdW(
                hdevinfo, ctypes.byref(devinfo), buf, 512, None
            ):
                active.add(buf.value.upper())

        setupapi.SetupDiDestroyDeviceInfoList(hdevinfo)
        return active
    except Exception:
        logger.debug("SetupAPI active monitor query failed", exc_info=True)
        return set()


def _read_monitor_identities_registry() -> list[dict[str, str]]:
    """Read monitor model/manufacturer from Windows registry EDID data.

    Only returns currently active monitors. Skips internal panels without
    EDID model descriptors.
    """
    import winreg

    active_ids = _get_active_monitor_instance_ids()
    if not active_ids:
        # If we can't determine which monitors are active, return empty
        # rather than including ghost entries from previously-connected
        # monitors whose EDID persists in the registry.
        logger.debug("No active monitor IDs — skipping registry EDID scan")
        return []
    result: list[dict[str, str]] = []
    seen_models: set[str] = set()
    base = r"SYSTEM\CurrentControlSet\Enum\DISPLAY"

    try:
        display_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        logger.debug("Cannot open DISPLAY registry key")
        return []

    try:
        i = 0
        while True:
            try:
                monitor_id = winreg.EnumKey(display_key, i)
                i += 1
            except OSError:
                break

            monitor_path = f"{base}\\{monitor_id}"
            try:
                monitor_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, monitor_path)
            except OSError:
                continue

            j = 0
            while True:
                try:
                    instance = winreg.EnumKey(monitor_key, j)
                    j += 1
                except OSError:
                    break

                instance_id = f"DISPLAY\\{monitor_id}\\{instance}".upper()
                if instance_id not in active_ids:
                    continue

                edid_path = f"{monitor_path}\\{instance}\\Device Parameters"
                try:
                    params_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, edid_path)
                    edid_bytes, _ = winreg.QueryValueEx(params_key, "EDID")
                    winreg.CloseKey(params_key)
                except OSError:
                    continue

                if not isinstance(edid_bytes, bytes) or len(edid_bytes) < 128:
                    continue

                model_raw = _parse_edid_descriptor(edid_bytes, 0xFC)
                pnpid = _edid_manufacturer(edid_bytes)
                manufacturer = _PNPID_TO_MANUFACTURER.get(pnpid, pnpid)

                for prefix in (manufacturer, pnpid):
                    if model_raw.upper().startswith(prefix.upper() + " "):
                        model_raw = model_raw[len(prefix) :].strip()
                        break
                    if model_raw.upper().startswith(prefix.upper()):
                        model_raw = model_raw[len(prefix) :].strip()
                        break

                if model_raw and model_raw not in seen_models:
                    seen_models.add(model_raw)
                    result.append({"model": model_raw, "manufacturer": manufacturer})

            winreg.CloseKey(monitor_key)
    finally:
        winreg.CloseKey(display_key)

    return result


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class DDCCICollector(Collector):
    """Collect and control monitor settings via DDC/CI."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="ddcci",
        tier=CollectorTier.GENERIC,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"display", "control"},
        description="DDC/CI monitor brightness, contrast, volume, input source, power state",
        optional_dependencies=["monitorcontrol"],
    )

    # Number of consecutive empty collects (no live VCP data) before re-probing.
    # Each tick is ~30-60s (collector interval); 3 ticks = 1.5-3min before self-heal kicks in.
    SELF_HEAL_THRESHOLD: ClassVar[int] = 3

    def __init__(self) -> None:
        self._monitor_ids: list[dict[str, str]] | None = None
        self._use_helper: bool = False
        self._helper_client: Any = None
        # Counter: consecutive collects that returned no live VCP data
        # (only registry-cached model/manufacturer). Triggers helper fallback.
        self._empty_collect_streak: int = 0

    @staticmethod
    def _ddcci_smoke_test_sync(monitors: list[Any]) -> bool:
        """Try a real VCP read on at least one monitor.

        ``monitorcontrol.get_monitors()`` returns monitor handles based on the
        Windows monitor registry, not on actual DDC/CI reachability. Under
        NSSM/LocalSystem (no desktop session) the handles exist but every VCP
        read fails. Without this smoke test ``probe()`` returns a false-positive
        and ``_use_helper`` stays ``False`` — leaving the agent stuck with only
        registry-cached ``model``/``manufacturer`` and missing brightness,
        contrast, KVM, input source, etc.

        Returns ``True`` if at least one monitor accepts a VCP read.
        """
        for m in monitors:
            try:
                with m:
                    # Cheap, widely-supported VCP feature. Any successful read
                    # confirms DDC/CI is actually working on this monitor.
                    m.get_luminance()
                return True
            except Exception:
                continue
        return False

    async def probe(self) -> bool:
        """Check if monitorcontrol is importable and any monitor is reachable.

        Three modes of operation:
        - **Direct DDC/CI** — monitors reachable via monitorcontrol AND a VCP
          smoke-test succeeds
        - **Via helper** — helper process has desktop session and DDC/CI access
        - **Registry fallback** — monitors exist but DDC/CI inaccessible
        """
        # Try DDC/CI directly first
        has_monitorcontrol = False
        try:
            import monitorcontrol  # noqa: F401

            has_monitorcontrol = True
        except ImportError:
            pass

        if has_monitorcontrol:
            try:
                monitors = await asyncio.to_thread(monitorcontrol.get_monitors)
                if len(monitors) > 0:
                    smoke_ok = await asyncio.to_thread(self._ddcci_smoke_test_sync, monitors)
                    if smoke_ok:
                        logger.info("DDC/CI: direct access (%d monitors)", len(monitors))
                        return True
                    logger.info(
                        "DDC/CI: get_monitors() returned %d, but VCP smoke-test failed "
                        "— falling through to helper",
                        len(monitors),
                    )
            except Exception:
                logger.debug("DDC/CI probe: get_monitors() failed", exc_info=True)

        # Try helper (runs under user session with desktop access)
        try:
            from desk2ha_agent.helper.client import HelperClient

            self._helper_client = HelperClient()
            if await self._helper_client.is_available():
                metrics = await self._helper_client.get_metrics()
                display_keys = [k for k in metrics if k.startswith("display.")]
                if display_keys:
                    self._use_helper = True
                    logger.info("DDC/CI: using helper (%d display metrics)", len(display_keys))
                    return True
                logger.debug("DDC/CI: helper running but no display metrics")
        except Exception:
            logger.debug("DDC/CI: helper probe failed", exc_info=True)

        # Fall back to registry — monitors may be off or running as LocalSystem
        if sys.platform == "win32":
            try:
                registry_ids = await asyncio.to_thread(_read_monitor_identities_registry)
                if registry_ids:
                    logger.info(
                        "DDC/CI probe: no live monitors, but %d in registry",
                        len(registry_ids),
                    )
                    return True
            except Exception:
                logger.debug("DDC/CI probe: registry check failed", exc_info=True)

        return False

    async def setup(self) -> None:
        """Read monitor identities (Windows only)."""
        if sys.platform == "win32":
            try:
                self._monitor_ids = await asyncio.to_thread(_read_monitor_identities_registry)
                if self._monitor_ids:
                    logger.info(
                        "DDC/CI: identified %d monitor(s) via registry EDID",
                        len(self._monitor_ids),
                    )
            except Exception:
                logger.debug("Failed to read monitor identities", exc_info=True)

    async def collect(self) -> dict[str, Any]:
        """Collect DDC/CI metrics (directly or via helper).

        Self-healing: if the direct path keeps returning only static
        registry-cached metadata (no live VCP data) for ``SELF_HEAL_THRESHOLD``
        consecutive collects, attempt to switch to helper mode. This recovers
        from the half-init state where ``probe()`` returned True at boot but
        live monitors were unavailable (e.g. monitor in standby at agent start,
        or DDC/CI under NSSM/LocalSystem without desktop session).
        """
        if self._use_helper:
            return await self._collect_via_helper()
        try:
            result = await asyncio.to_thread(self._collect_sync)
        except Exception:
            logger.debug("DDC/CI collection failed", exc_info=True)
            result = {}

        if self._has_live_vcp_data(result):
            self._empty_collect_streak = 0
            return result

        self._empty_collect_streak += 1
        if self._empty_collect_streak >= self.SELF_HEAL_THRESHOLD:
            logger.warning(
                "DDC/CI: %d consecutive empty collects — attempting helper fallback",
                self._empty_collect_streak,
            )
            self._empty_collect_streak = 0  # reset to avoid log spam regardless of outcome
            switched = await self._try_helper_fallback()
            if switched:
                return await self._collect_via_helper()

        return result

    @staticmethod
    def _has_live_vcp_data(metrics: dict[str, Any]) -> bool:
        """Return True if metrics contain at least one *live* VCP-derived field.

        ``model`` and ``manufacturer`` are sourced from the registry EDID cache
        and are NOT proof that DDC/CI is actually working. Live indicators are
        values that can only come from a real VCP read: brightness, contrast,
        volume, input source, power_state.
        """
        live_suffixes = (
            ".brightness_percent",
            ".contrast_percent",
            ".volume",
            ".input_source",
            ".power_state",
        )
        return any(k.endswith(live_suffixes) for k in metrics)

    async def _try_helper_fallback(self) -> bool:
        """Try to switch to helper-based collection. Returns True on success."""
        try:
            from desk2ha_agent.helper.client import HelperClient

            if self._helper_client is None:
                self._helper_client = HelperClient()
            if await self._helper_client.is_available():
                metrics = await self._helper_client.get_metrics()
                if any(k.startswith("display.") for k in metrics):
                    self._use_helper = True
                    logger.info(
                        "DDC/CI: switched to helper mode after self-heal (%d display metrics)",
                        sum(1 for k in metrics if k.startswith("display.")),
                    )
                    return True
                logger.info("DDC/CI self-heal: helper available but no display metrics yet")
            else:
                logger.info("DDC/CI self-heal: helper not reachable")
        except Exception:
            logger.debug("DDC/CI self-heal: helper probe failed", exc_info=True)
        return False

    async def _collect_via_helper(self) -> dict[str, Any]:
        """Fetch DDC/CI display metrics from the elevated helper."""
        if self._helper_client is None:
            return {}
        all_metrics = await self._helper_client.get_metrics()
        # Filter to display-related keys only (avoid duplicating dell_dcm data)
        return {k: v for k, v in all_metrics.items() if k.startswith("display.")}

    def _collect_sync(self) -> dict[str, Any]:
        """Synchronous DDC/CI collection."""
        from monitorcontrol import get_monitors

        metrics: dict[str, Any] = {}

        try:
            monitors = get_monitors()
        except Exception:
            logger.debug("DDC/CI monitor enumeration failed", exc_info=True)
            monitors = []

        # Track which registry monitors matched a DDC/CI monitor
        matched_registry_indices: set[int] = set()

        for i, monitor in enumerate(monitors):
            prefix = f"display.{i}"

            # Emit model/manufacturer from cached registry data (Windows)
            if self._monitor_ids and i < len(self._monitor_ids):
                matched_registry_indices.add(i)
                mid = self._monitor_ids[i]
                if mid.get("model"):
                    metrics[f"{prefix}.model"] = metric_value(mid["model"])
                if mid.get("manufacturer"):
                    metrics[f"{prefix}.manufacturer"] = metric_value(mid["manufacturer"])

            try:
                with monitor:
                    # Brightness
                    try:
                        brightness = monitor.get_luminance()
                        metrics[f"{prefix}.brightness_percent"] = metric_value(
                            float(brightness), unit="%"
                        )
                    except Exception:
                        pass

                    # Contrast
                    try:
                        contrast = monitor.get_contrast()
                        metrics[f"{prefix}.contrast_percent"] = metric_value(
                            float(contrast), unit="%"
                        )
                    except Exception:
                        pass

                    # Volume (VCP 0x62)
                    try:
                        vol_raw = monitor.vcp.get_vcp_feature(_VCP_VOLUME)
                        vol_value = vol_raw[0] if isinstance(vol_raw, tuple) else int(vol_raw)
                        metrics[f"{prefix}.volume"] = metric_value(float(vol_value), unit="%")
                    except Exception:
                        pass

                    # Power mode (VCP 0xD6)
                    try:
                        power_raw = monitor.vcp.get_vcp_feature(_VCP_POWER_MODE)
                        power_int = (
                            power_raw[0] if isinstance(power_raw, tuple) else int(power_raw)
                        )
                        power_name = _VCP_TO_POWER_STATE.get(power_int, f"unknown_{power_int}")
                        metrics[f"{prefix}.power_state"] = metric_value(power_name)
                    except Exception:
                        pass

                    # Input source
                    try:
                        source = monitor.get_input_source()
                        metrics[f"{prefix}.input_source"] = metric_value(
                            _resolve_input_source(source)
                        )
                    except Exception:
                        pass

                    # ── Vendor-specific VCP codes (Dell proprietary) ──
                    # These may silently fail on non-Dell monitors.

                    # KVM select (VCP 0xE5)
                    try:
                        kvm_raw = monitor.vcp.get_vcp_feature(_VCP_KVM_SELECT)
                        kvm_int = kvm_raw[0] if isinstance(kvm_raw, tuple) else int(kvm_raw)
                        kvm_name = _KVM_SELECT_MAP.get(kvm_int, f"unknown_{kvm_int}")
                        metrics[f"{prefix}.kvm_active_pc"] = metric_value(kvm_name)
                    except Exception:
                        pass

                    # PBP/PIP mode (VCP 0xE0)
                    try:
                        pbp_raw = monitor.vcp.get_vcp_feature(_VCP_PBP_MODE)
                        pbp_int = pbp_raw[0] if isinstance(pbp_raw, tuple) else int(pbp_raw)
                        pbp_name = _PBP_MODE_MAP.get(pbp_int, f"unknown_{pbp_int}")
                        metrics[f"{prefix}.pbp_mode"] = metric_value(pbp_name)
                    except Exception:
                        pass

                    # Auto brightness (VCP 0xE3)
                    try:
                        ab_raw = monitor.vcp.get_vcp_feature(_VCP_AUTO_BRIGHTNESS)
                        ab_int = ab_raw[0] if isinstance(ab_raw, tuple) else int(ab_raw)
                        metrics[f"{prefix}.auto_brightness"] = metric_value(bool(ab_int))
                    except Exception:
                        pass

                    # Auto color temperature (VCP 0xE6)
                    try:
                        act_raw = monitor.vcp.get_vcp_feature(_VCP_AUTO_COLOR_TEMP)
                        act_int = act_raw[0] if isinstance(act_raw, tuple) else int(act_raw)
                        metrics[f"{prefix}.auto_color_temp"] = metric_value(bool(act_int))
                    except Exception:
                        pass

                    # Smart HDR (VCP 0xE9)
                    try:
                        hdr_raw = monitor.vcp.get_vcp_feature(_VCP_SMART_HDR)
                        hdr_int = hdr_raw[0] if isinstance(hdr_raw, tuple) else int(hdr_raw)
                        metrics[f"{prefix}.smart_hdr"] = metric_value(hdr_int)
                    except Exception:
                        pass

                    # PowerNap (VCP 0xF0)
                    try:
                        pn_raw = monitor.vcp.get_vcp_feature(_VCP_POWER_NAP)
                        pn_int = pn_raw[0] if isinstance(pn_raw, tuple) else int(pn_raw)
                        metrics[f"{prefix}.power_nap"] = metric_value(pn_int)
                    except Exception:
                        pass

                    # ── Standard MCCS codes (extended) ──

                    # RGB Gain (VCP 0x16, 0x18, 0x1A) — 0-100
                    for vcp, suffix in (
                        (_VCP_RED_GAIN, "red_gain"),
                        (_VCP_GREEN_GAIN, "green_gain"),
                        (_VCP_BLUE_GAIN, "blue_gain"),
                    ):
                        try:
                            raw = monitor.vcp.get_vcp_feature(vcp)
                            val = raw[0] if isinstance(raw, tuple) else int(raw)
                            metrics[f"{prefix}.{suffix}"] = metric_value(float(val), unit="%")
                        except Exception:
                            pass

                    # RGB Black Level (VCP 0x6C, 0x6E, 0x70) — 0-100
                    for vcp, suffix in (
                        (_VCP_RED_BLACK_LEVEL, "red_black_level"),
                        (_VCP_GREEN_BLACK_LEVEL, "green_black_level"),
                        (_VCP_BLUE_BLACK_LEVEL, "blue_black_level"),
                    ):
                        try:
                            raw = monitor.vcp.get_vcp_feature(vcp)
                            val = raw[0] if isinstance(raw, tuple) else int(raw)
                            metrics[f"{prefix}.{suffix}"] = metric_value(float(val), unit="%")
                        except Exception:
                            pass

                    # Color preset (VCP 0x14)
                    try:
                        cp_raw = monitor.vcp.get_vcp_feature(_VCP_COLOR_PRESET)
                        cp_int = cp_raw[0] if isinstance(cp_raw, tuple) else int(cp_raw)
                        cp_name = _COLOR_PRESET_MAP.get(cp_int, f"unknown_{cp_int}")
                        metrics[f"{prefix}.color_preset"] = metric_value(cp_name)
                    except Exception:
                        pass

                    # Sharpness (VCP 0x87)
                    try:
                        sh_raw = monitor.vcp.get_vcp_feature(_VCP_SHARPNESS)
                        sh_int = sh_raw[0] if isinstance(sh_raw, tuple) else int(sh_raw)
                        metrics[f"{prefix}.sharpness"] = metric_value(float(sh_int), unit="%")
                    except Exception:
                        pass

                    # Audio mute (VCP 0x8D) — MCCS: 1=unmuted, 2=muted
                    try:
                        am_raw = monitor.vcp.get_vcp_feature(_VCP_AUDIO_MUTE)
                        am_int = am_raw[0] if isinstance(am_raw, tuple) else int(am_raw)
                        metrics[f"{prefix}.audio_mute"] = metric_value(am_int == 2)
                    except Exception:
                        pass

                    # Display usage hours (VCP 0xC0) — read-only diagnostic
                    try:
                        uh_raw = monitor.vcp.get_vcp_feature(_VCP_USAGE_HOURS)
                        uh_int = uh_raw[0] if isinstance(uh_raw, tuple) else int(uh_raw)
                        metrics[f"{prefix}.usage_hours"] = metric_value(uh_int, unit="h")
                    except Exception:
                        pass

                    # Firmware level (VCP 0xC9) — read-only diagnostic
                    try:
                        fw_raw = monitor.vcp.get_vcp_feature(_VCP_FIRMWARE_LEVEL)
                        fw_int = fw_raw[0] if isinstance(fw_raw, tuple) else int(fw_raw)
                        # Decode as major.minor (high byte.low byte)
                        fw_major = (fw_int >> 8) & 0xFF
                        fw_minor = fw_int & 0xFF
                        metrics[f"{prefix}.firmware_version"] = metric_value(
                            f"{fw_major}.{fw_minor}"
                        )
                    except Exception:
                        pass

            except Exception:
                # Monitor offline (powered off, disconnected, or DDC/CI unavailable).
                # Emit power_state=off so HA entities degrade gracefully instead of
                # becoming "unavailable".
                logger.debug("DDC/CI communication failed for monitor %d — marking offline", i)
                metrics[f"{prefix}.power_state"] = metric_value("off")

        # Emit entries for registry-known monitors not found via DDC/CI.
        # These monitors passed the DN_STARTED devnode check (physically
        # connected) but DDC/CI can't reach them — typically because we're
        # running as LocalSystem with no desktop session.  Report power_state
        # as "on" since the devnode is started (connected and active).
        if self._monitor_ids:
            for j, mid in enumerate(self._monitor_ids):
                if j in matched_registry_indices:
                    continue
                idx = len(monitors) + (j - len(matched_registry_indices))
                prefix = f"display.{idx}"
                if mid.get("model"):
                    metrics[f"{prefix}.model"] = metric_value(mid["model"])
                if mid.get("manufacturer"):
                    metrics[f"{prefix}.manufacturer"] = metric_value(mid["manufacturer"])
                metrics[f"{prefix}.power_state"] = metric_value("on")
                logger.debug(
                    "Monitor '%s' connected (devnode started, DDC/CI unavailable)",
                    mid.get("model", "unknown"),
                )

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute display control commands (directly or via helper)."""
        if not command.startswith("display."):
            raise NotImplementedError

        # Proxy through helper if DDC/CI is not available locally
        if self._use_helper and self._helper_client is not None:
            return await self._helper_client.send_command(command, target, parameters)

        from monitorcontrol import get_monitors

        # Parse display index from target (e.g. "display.0")
        parts = target.split(".")
        display_index = int(parts[1]) if len(parts) > 1 else 0

        if command == "display.set_brightness":
            value = int(parameters["value"])
            await asyncio.to_thread(self._set_brightness_sync, get_monitors, display_index, value)
            return {"status": "completed"}

        if command == "display.set_contrast":
            value = int(parameters["value"])
            await asyncio.to_thread(self._set_contrast_sync, get_monitors, display_index, value)
            return {"status": "completed"}

        if command == "display.set_volume":
            value = int(parameters["value"])
            await asyncio.to_thread(self._set_volume_sync, get_monitors, display_index, value)
            return {"status": "completed"}

        if command == "display.set_input_source":
            source = str(parameters["source"])
            await asyncio.to_thread(
                self._set_input_source_sync, get_monitors, display_index, source
            )
            return {"status": "completed"}

        if command == "display.set_power_state":
            state = str(parameters["state"])
            await asyncio.to_thread(self._set_power_state_sync, get_monitors, display_index, state)
            return {"status": "completed"}

        # Color preset (VCP 0x14) — accepts name or raw int
        if command == "display.set_color_preset":
            preset = str(parameters["preset"])
            # Case-insensitive lookup
            preset_lower_map = {k.lower(): v for k, v in _COLOR_PRESET_TO_VCP.items()}
            if preset.lower() in preset_lower_map:
                value = preset_lower_map[preset.lower()]
            else:
                try:
                    value = int(preset)
                except ValueError:
                    raise ValueError(
                        f"Unknown color preset: {preset!r}. "
                        f"Expected one of: {list(_COLOR_PRESET_TO_VCP)}"
                    ) from None
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, _VCP_COLOR_PRESET, value
            )
            return {"status": "completed"}

        # Sharpness (VCP 0x87) — 0-100
        if command == "display.set_sharpness":
            value = int(parameters["value"])
            if not 0 <= value <= 100:
                raise ValueError(f"Sharpness must be 0-100, got {value}")
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, _VCP_SHARPNESS, value
            )
            return {"status": "completed"}

        # RGB Gain + Black Level (VCP 0x16/18/1A, 0x6C/6E/70) — 0-100
        _rgb_vcp_map = {
            "display.set_red_gain": _VCP_RED_GAIN,
            "display.set_green_gain": _VCP_GREEN_GAIN,
            "display.set_blue_gain": _VCP_BLUE_GAIN,
            "display.set_red_black_level": _VCP_RED_BLACK_LEVEL,
            "display.set_green_black_level": _VCP_GREEN_BLACK_LEVEL,
            "display.set_blue_black_level": _VCP_BLUE_BLACK_LEVEL,
        }
        if command in _rgb_vcp_map:
            value = int(parameters["value"])
            if not 0 <= value <= 100:
                raise ValueError(f"{command} value must be 0-100, got {value}")
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, _rgb_vcp_map[command], value
            )
            return {"status": "completed"}

        # Audio mute (VCP 0x8D) — MCCS: 1=unmuted, 2=muted
        if command == "display.set_audio_mute":
            mute = parameters.get("value", parameters.get("mute", False))
            vcp_val = 2 if mute else 1
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, _VCP_AUDIO_MUTE, vcp_val
            )
            return {"status": "completed"}

        # Factory reset (VCP 0x04) — write-only, no parameters
        if command == "display.factory_reset":
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, _VCP_FACTORY_RESET, 1
            )
            return {"status": "completed"}

        # Factory color reset (VCP 0x08) — write-only, no parameters
        if command == "display.factory_color_reset":
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, _VCP_FACTORY_COLOR_RESET, 1
            )
            return {"status": "completed"}

        # VCP-based toggle commands (Dell proprietary codes)
        vcp_toggle_map = {
            "display.set_auto_brightness": _VCP_AUTO_BRIGHTNESS,
            "display.set_auto_color_temp": _VCP_AUTO_COLOR_TEMP,
            "display.set_kvm": _VCP_KVM_SELECT,
            "display.set_pbp_mode": _VCP_PBP_MODE,
            "display.set_smart_hdr": _VCP_SMART_HDR,
            "display.set_power_nap": _VCP_POWER_NAP,
        }

        if command in vcp_toggle_map:
            vcp_code = vcp_toggle_map[command]
            value = int(parameters.get("value", parameters.get("pc", parameters.get("mode", 0))))
            await asyncio.to_thread(
                self._set_vcp_sync, get_monitors, display_index, vcp_code, value
            )
            return {"status": "completed"}

        raise NotImplementedError(f"Unknown command: {command}")

    @staticmethod
    def _set_vcp_sync(get_monitors: Any, display_index: int, vcp_code: int, value: int) -> None:
        monitors = get_monitors()
        if display_index >= len(monitors):
            raise ValueError(f"Display index {display_index} out of range")
        with monitors[display_index]:
            monitors[display_index].vcp.set_vcp_feature(vcp_code, value)

    @staticmethod
    def _set_brightness_sync(get_monitors: Any, display_index: int, value: int) -> None:
        monitors = get_monitors()
        if display_index >= len(monitors):
            raise ValueError(f"Display index {display_index} out of range (have {len(monitors)})")
        with monitors[display_index]:
            monitors[display_index].set_luminance(value)

    @staticmethod
    def _set_contrast_sync(get_monitors: Any, display_index: int, value: int) -> None:
        monitors = get_monitors()
        if display_index >= len(monitors):
            raise ValueError(f"Display index {display_index} out of range (have {len(monitors)})")
        with monitors[display_index]:
            monitors[display_index].set_contrast(value)

    @staticmethod
    def _set_volume_sync(get_monitors: Any, display_index: int, value: int) -> None:
        if not 0 <= value <= 100:
            raise ValueError(f"Volume must be 0-100, got {value}")
        monitors = get_monitors()
        if display_index >= len(monitors):
            raise ValueError(f"Display index {display_index} out of range (have {len(monitors)})")
        with monitors[display_index]:
            monitors[display_index].vcp.set_vcp_feature(_VCP_VOLUME, value)

    @staticmethod
    def _set_input_source_sync(get_monitors: Any, display_index: int, source_name: str) -> None:
        raw = _resolve_input_source_to_raw(source_name)
        monitors = get_monitors()
        if display_index >= len(monitors):
            raise ValueError(f"Display index {display_index} out of range (have {len(monitors)})")
        with monitors[display_index]:
            monitors[display_index].set_input_source(raw)

    @staticmethod
    def _set_power_state_sync(get_monitors: Any, display_index: int, state: str) -> None:
        state_lower = state.lower()
        if state_lower not in _POWER_STATE_TO_VCP:
            raise ValueError(
                f"Unknown power state: {state!r}. Expected one of: {list(_POWER_STATE_TO_VCP)}"
            )
        raw = _POWER_STATE_TO_VCP[state_lower]
        monitors = get_monitors()
        if display_index >= len(monitors):
            raise ValueError(f"Display index {display_index} out of range (have {len(monitors)})")
        with monitors[display_index]:
            monitors[display_index].vcp.set_vcp_feature(_VCP_POWER_MODE, raw)

    async def teardown(self) -> None:
        self._monitor_ids = None
        self._helper_client = None
        self._use_helper = False


COLLECTOR_CLASS = DDCCICollector
