"""Logitech HID++ vendor collector.

Reads battery, DPI, and keyboard backlight from wireless Logitech peripherals
connected via Unifying, Bolt, or direct BLE receivers using the HID++ protocol.

HID++ 1.0: Long messages (20 bytes), register-based (older devices)
HID++ 2.0: Feature-based with feature index table (newer devices)

Supports cross-platform enumeration via hidapi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar

from desk2ha_agent.collector.base import (
    Collector,
    CollectorMeta,
    CollectorTier,
    Platform,
    metric_value,
)

logger = logging.getLogger(__name__)

_LOGITECH_VID = 0x046D

# HID++ usage pages for Logitech receivers
_HIDPP_SHORT_USAGE_PAGE = 0xFF00  # 7-byte reports
_HIDPP_LONG_USAGE_PAGE = 0xFF00  # 20-byte reports
_HIDPP_USAGE_PAGES = {0xFF00, 0x0001}  # Vendor + generic desktop

# HID++ report IDs
_REPORT_SHORT = 0x10  # 7 bytes (HID++ 1.0 short)
_REPORT_LONG = 0x11  # 20 bytes (HID++ 2.0 long)

# HID++ 1.0 registers
_REG_BATTERY_STATUS = 0x07
_REG_BATTERY_VOLTAGE = 0x0D

# HID++ 2.0 feature IDs (need to be looked up via IRoot 0x0000)
_FEAT_IROOT = 0x0000  # Feature index root
_FEAT_BATTERY_UNIFIED = 0x1000  # Unified Battery
_FEAT_BATTERY_VOLTAGE = 0x1001  # Battery Voltage
_FEAT_ADJUSTABLE_DPI = 0x2201  # Adjustable DPI
_FEAT_BACKLIGHT2 = 0x1982  # Backlight 2
_FEAT_DEVICE_NAME = 0x0005  # Device Name
_FEAT_DEVICE_TYPE = 0x0003  # Device Type and Name (FW info)
_FEAT_SMART_SHIFT = 0x2110  # SmartShift (scroll wheel mode)
_FEAT_HIRES_WHEEL = 0x2121  # Hi-Res Wheel
_FEAT_THUMB_WHEEL = 0x2150  # Thumb Wheel
_FEAT_CHANGE_HOST = 0x1814  # Change Host (multi-device)
_FEAT_WIRELESS_STATUS = 0x1D4B  # Wireless Device Status
_FEAT_COLOR_LED = 0x8070  # Color LED Effects

# All known features for dynamic discovery
_KNOWN_FEATURES: dict[int, str] = {
    _FEAT_BATTERY_UNIFIED: "battery_unified",
    _FEAT_BATTERY_VOLTAGE: "battery_voltage",
    _FEAT_ADJUSTABLE_DPI: "adjustable_dpi",
    _FEAT_BACKLIGHT2: "backlight2",
    _FEAT_SMART_SHIFT: "smart_shift",
    _FEAT_HIRES_WHEEL: "hires_wheel",
    _FEAT_THUMB_WHEEL: "thumb_wheel",
    _FEAT_CHANGE_HOST: "change_host",
    _FEAT_WIRELESS_STATUS: "wireless_status",
    _FEAT_COLOR_LED: "color_led",
}

# Device types (from HID++ 2.0 deviceType feature)
_DEVICE_TYPE_MAP = {
    0: "keyboard",
    1: "remote_control",
    2: "numpad",
    3: "mouse",
    4: "touchpad",
    5: "trackball",
    6: "presenter",
    7: "receiver",
    8: "headset",
}


def _build_hidpp_short(device_idx: int, sub_id: int, reg: int, p0: int = 0) -> bytes:
    """Build a 7-byte HID++ 1.0 short report."""
    return bytes([_REPORT_SHORT, device_idx, sub_id, reg, p0, 0x00, 0x00])


def _build_hidpp_long(device_idx: int, feat_idx: int, func_id: int, *params: int) -> bytes:
    """Build a 20-byte HID++ 2.0 long report."""
    sw_id = 0x01  # Software ID
    data = [_REPORT_LONG, device_idx, feat_idx, (func_id << 4) | sw_id]
    data.extend(params)
    data.extend([0x00] * (20 - len(data)))
    return bytes(data)


class _HidPPDevice:
    """Represents a single HID++ device behind a receiver or direct connection."""

    def __init__(self, hid_path: bytes, device_idx: int, name: str) -> None:
        self.hid_path = hid_path
        self.device_idx = device_idx
        self.name = name
        self.device_type: str = "unknown"
        self.protocol_version: tuple[int, int] = (0, 0)
        # Feature index cache: feature_id -> index (HID++ 2.0)
        self._feature_cache: dict[int, int] = {}
        self._last_battery: dict[str, Any] = {}
        # Discovered features: name -> feature_index
        self.features: dict[str, int] = {}

    def get_feature_index(self, h: Any, feature_id: int) -> int | None:
        """Look up a feature index via IRoot (0x0000)."""
        if feature_id in self._feature_cache:
            return self._feature_cache[feature_id]

        try:
            # IRoot.getFeatureID: feature_index=0x00, function=0
            hi = (feature_id >> 8) & 0xFF
            lo = feature_id & 0xFF
            msg = _build_hidpp_long(self.device_idx, 0x00, 0, hi, lo)
            h.write(msg)
            time.sleep(0.05)

            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 5:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == 0x00:
                    idx = resp[4]
                    if idx == 0:
                        return None  # Feature not supported
                    self._feature_cache[feature_id] = idx
                    return idx
            return None
        except Exception:
            return None

    def read_battery_unified(self, h: Any) -> dict[str, Any] | None:
        """Read battery via Unified Battery feature (0x1000)."""
        idx = self.get_feature_index(h, _FEAT_BATTERY_UNIFIED)
        if idx is None:
            return None

        try:
            # getBatteryStatus: function 0
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)

            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 8:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    level = resp[4]
                    # resp[5] = flags (bit0=discharging, bit1=charging, bit2=external)
                    flags = resp[5]
                    status = "discharging"
                    if flags & 0x02:
                        status = "charging"
                    elif flags & 0x04:
                        status = "external"
                    return {"level": level, "status": status}
            return None
        except Exception:
            return None

    def read_dpi(self, h: Any) -> int | None:
        """Read current DPI via Adjustable DPI feature (0x2201)."""
        idx = self.get_feature_index(h, _FEAT_ADJUSTABLE_DPI)
        if idx is None:
            return None

        try:
            # getSensorDPI: function 1, sensor 0
            msg = _build_hidpp_long(self.device_idx, idx, 1, 0)
            h.write(msg)
            time.sleep(0.05)

            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 7:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    dpi = (resp[4] << 8) | resp[5]
                    return dpi
            return None
        except Exception:
            return None

    def read_backlight(self, h: Any) -> int | None:
        """Read backlight level via Backlight2 feature (0x1982)."""
        idx = self.get_feature_index(h, _FEAT_BACKLIGHT2)
        if idx is None:
            return None

        try:
            # getBacklightConfig: function 0
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)

            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 6:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    # resp[4] = backlight mode, resp[5] = level (0-100 or similar)
                    return resp[5]
            return None
        except Exception:
            return None

    def discover_features(self, h: Any) -> None:
        """Probe all known HID++ 2.0 features and cache which are available."""
        for feat_id, feat_name in _KNOWN_FEATURES.items():
            idx = self.get_feature_index(h, feat_id)
            if idx is not None:
                self.features[feat_name] = idx

    def read_smart_shift(self, h: Any) -> dict[str, Any] | None:
        """Read SmartShift configuration (0x2110)."""
        idx = self.features.get("smart_shift")
        if idx is None:
            idx = self.get_feature_index(h, _FEAT_SMART_SHIFT)
        if idx is None:
            return None
        try:
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)
            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 7:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    # resp[4]=mode (1=ratchet, 2=freespin), resp[5]=threshold
                    mode = "freespin" if resp[4] == 2 else "ratchet"
                    threshold = resp[5]
                    return {"mode": mode, "threshold": threshold}
            return None
        except Exception:
            return None

    def read_hires_wheel(self, h: Any) -> dict[str, Any] | None:
        """Read Hi-Res Wheel configuration (0x2121)."""
        idx = self.features.get("hires_wheel")
        if idx is None:
            idx = self.get_feature_index(h, _FEAT_HIRES_WHEEL)
        if idx is None:
            return None
        try:
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)
            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 6:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    # resp[4] bit0=hires enabled, bit1=invert
                    hires = bool(resp[4] & 0x01)
                    invert = bool(resp[4] & 0x02)
                    return {"hires": hires, "invert": invert}
            return None
        except Exception:
            return None

    def read_thumb_wheel(self, h: Any) -> dict[str, Any] | None:
        """Read Thumb Wheel configuration (0x2150)."""
        idx = self.features.get("thumb_wheel")
        if idx is None:
            idx = self.get_feature_index(h, _FEAT_THUMB_WHEEL)
        if idx is None:
            return None
        try:
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)
            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 6:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    invert = bool(resp[4] & 0x01)
                    return {"invert": invert}
            return None
        except Exception:
            return None

    def read_change_host(self, h: Any) -> dict[str, Any] | None:
        """Read Change Host info (0x1814) — active host index."""
        idx = self.features.get("change_host")
        if idx is None:
            idx = self.get_feature_index(h, _FEAT_CHANGE_HOST)
        if idx is None:
            return None
        try:
            # getHostInfo: function 0
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)
            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 6:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    num_hosts = resp[4]
                    current_host = resp[5]
                    return {"num_hosts": num_hosts, "current_host": current_host}
            return None
        except Exception:
            return None

    def read_wireless_status(self, h: Any) -> dict[str, Any] | None:
        """Read Wireless Device Status (0x1D4B)."""
        idx = self.features.get("wireless_status")
        if idx is None:
            idx = self.get_feature_index(h, _FEAT_WIRELESS_STATUS)
        if idx is None:
            return None
        try:
            msg = _build_hidpp_long(self.device_idx, idx, 0)
            h.write(msg)
            time.sleep(0.05)
            for _ in range(30):
                resp = h.read(20)
                if not resp or len(resp) < 6:
                    continue
                if resp[0] == _REPORT_LONG and resp[2] == idx:
                    # resp[4] = reconnection status, resp[5] = link quality
                    link_quality = resp[5]
                    return {"link_quality": link_quality}
            return None
        except Exception:
            return None


class LogitechHidPPCollector(Collector):
    """Enumerate and read Logitech HID++ wireless peripherals."""

    meta: ClassVar[CollectorMeta] = CollectorMeta(
        name="logitech_hidpp",
        tier=CollectorTier.VENDOR,
        platforms={Platform.WINDOWS, Platform.LINUX, Platform.MACOS},
        capabilities={"peripheral", "control"},
        description="Logitech HID++ wireless peripherals (battery, DPI, backlight)",
        requires_hardware="Logitech wireless receiver (Unifying/Bolt/Nano)",
        optional_dependencies=["hidapi"],
    )

    def __init__(self) -> None:
        self._receivers: list[dict[str, Any]] = []
        self._devices: list[_HidPPDevice] = []

    async def probe(self) -> bool:
        try:
            import hid

            all_devs = await asyncio.to_thread(hid.enumerate, _LOGITECH_VID)
            # Find Logitech receivers (usage_page 0xFF00 or HID++ capable)
            self._receivers = []
            seen_paths: set[bytes] = set()
            for dev in all_devs:
                path = dev.get("path", b"")
                if path in seen_paths:
                    continue
                # Look for vendor-specific usage page (HID++ long reports)
                if dev.get("usage_page") == 0xFF00 and dev.get("usage") in (1, 2):
                    self._receivers.append(dev)
                    seen_paths.add(path)

            if not self._receivers:
                # Also try any Logitech device with output_report_length >= 20
                for dev in all_devs:
                    path = dev.get("path", b"")
                    if path in seen_paths:
                        continue
                    product = (dev.get("product_string") or "").lower()
                    if any(k in product for k in ("bolt", "unifying", "nano", "lightspeed")):
                        self._receivers.append(dev)
                        seen_paths.add(path)

            return len(self._receivers) > 0
        except ImportError:
            return False
        except Exception:
            logger.debug("HID++ probe failed", exc_info=True)
            return False

    async def setup(self) -> None:
        logger.info("Logitech HID++: found %d receiver(s)", len(self._receivers))
        # Enumerate paired devices on each receiver
        await asyncio.to_thread(self._enumerate_devices)

    def _enumerate_devices(self) -> None:
        """Enumerate paired devices on each receiver."""
        import hid

        for recv in self._receivers:
            try:
                h = hid.device()
                h.open_path(recv["path"])
                h.set_nonblocking(True)

                # Flush pending data
                while h.read(20):
                    pass

                # Try device indices 1-6 (Unifying supports 6 paired devices)
                for dev_idx in range(1, 7):
                    try:
                        # Ping device: send HID++ 1.0 short message
                        # Sub-ID 0x00 = IRoot, Reg = 0x00
                        ping = _build_hidpp_short(dev_idx, 0x00, 0x00)
                        h.write(ping)
                        time.sleep(0.05)

                        # Read response
                        got_response = False
                        for _ in range(10):
                            resp = h.read(20)
                            if not resp:
                                continue
                            # Error response means no device
                            if resp[0] in (_REPORT_SHORT, _REPORT_LONG) and resp[2] == 0x8F:
                                break
                            if resp[0] in (_REPORT_SHORT, _REPORT_LONG):
                                got_response = True
                                break

                        if got_response:
                            product = recv.get("product_string", "Logitech Device")
                            device = _HidPPDevice(recv["path"], dev_idx, product)
                            device.discover_features(h)
                            self._devices.append(device)
                            logger.info(
                                "HID++ device found: idx=%d on %s, features=%s",
                                dev_idx,
                                product,
                                list(device.features.keys()),
                            )
                    except Exception:
                        continue

                h.close()
            except Exception:
                logger.debug("Failed to enumerate HID++ receiver", exc_info=True)

        # Also treat direct-connect Logitech devices (device_idx=0xFF)
        if not self._devices and self._receivers:
            for recv in self._receivers:
                product = recv.get("product_string", "Logitech Device")
                device = _HidPPDevice(recv["path"], 0xFF, product)
                self._devices.append(device)

        logger.info("HID++ enumeration complete: %d device(s)", len(self._devices))

    async def collect(self) -> dict[str, Any]:
        if not self._devices:
            return {}
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict[str, Any]:
        import hid

        metrics: dict[str, Any] = {}

        # Group devices by HID path to avoid opening same receiver multiple times
        by_path: dict[bytes, list[_HidPPDevice]] = {}
        for dev in self._devices:
            by_path.setdefault(dev.hid_path, []).append(dev)

        for hid_path, devices in by_path.items():
            try:
                h = hid.device()
                h.open_path(hid_path)
                h.set_nonblocking(True)

                # Flush
                while h.read(20):
                    pass

                for dev in devices:
                    prefix = f"peripheral.hidpp_{dev.device_idx}"
                    metrics[f"{prefix}.model"] = metric_value(dev.name)
                    metrics[f"{prefix}.manufacturer"] = metric_value("Logitech")

                    # Battery
                    battery = dev.read_battery_unified(h)
                    if battery:
                        metrics[f"{prefix}.battery_level"] = metric_value(
                            float(battery["level"]), unit="%"
                        )
                        metrics[f"{prefix}.battery_state"] = metric_value(battery["status"])
                        dev._last_battery = battery

                    # DPI (mice only)
                    dpi = dev.read_dpi(h)
                    if dpi is not None and dpi > 0:
                        metrics[f"{prefix}.dpi"] = metric_value(float(dpi), unit="DPI")
                        dev.device_type = "mouse"

                    # Backlight (keyboards)
                    backlight = dev.read_backlight(h)
                    if backlight is not None:
                        metrics[f"{prefix}.backlight_level"] = metric_value(
                            float(backlight), unit="%"
                        )
                        if dev.device_type == "unknown":
                            dev.device_type = "keyboard"

                    # SmartShift (MX Master scroll wheel)
                    smartshift = dev.read_smart_shift(h)
                    if smartshift:
                        metrics[f"{prefix}.smartshift_mode"] = metric_value(smartshift["mode"])
                        metrics[f"{prefix}.smartshift_threshold"] = metric_value(
                            float(smartshift["threshold"])
                        )

                    # Hi-Res Wheel
                    hires = dev.read_hires_wheel(h)
                    if hires:
                        metrics[f"{prefix}.hires_wheel"] = metric_value(hires["hires"])
                        metrics[f"{prefix}.hires_wheel_invert"] = metric_value(hires["invert"])

                    # Thumb Wheel
                    thumb = dev.read_thumb_wheel(h)
                    if thumb:
                        metrics[f"{prefix}.thumb_wheel_invert"] = metric_value(thumb["invert"])

                    # Change Host (multi-device switching)
                    host_info = dev.read_change_host(h)
                    if host_info:
                        metrics[f"{prefix}.active_host"] = metric_value(
                            float(host_info["current_host"])
                        )
                        metrics[f"{prefix}.num_hosts"] = metric_value(
                            float(host_info["num_hosts"])
                        )

                    # Wireless Status
                    wireless = dev.read_wireless_status(h)
                    if wireless:
                        metrics[f"{prefix}.link_quality"] = metric_value(
                            float(wireless["link_quality"]), unit="%"
                        )

                    if dev.device_type != "unknown":
                        metrics[f"{prefix}.device_type"] = metric_value(dev.device_type)

                h.close()
            except Exception:
                logger.debug("HID++ collection failed for receiver", exc_info=True)

        return metrics

    async def execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if command == "peripheral.set_dpi":
            return await asyncio.to_thread(self._set_dpi, target, parameters)
        if command == "peripheral.set_backlight":
            return await asyncio.to_thread(self._set_backlight, target, parameters)
        if command == "peripheral.set_smartshift":
            return await asyncio.to_thread(self._set_smartshift, target, parameters)
        if command == "peripheral.switch_host":
            return await asyncio.to_thread(self._switch_host, target, parameters)
        raise NotImplementedError

    def _find_device(self, target: str) -> _HidPPDevice | None:
        """Find device by target (e.g. 'peripheral.hidpp_1')."""
        for dev in self._devices:
            if f"peripheral.hidpp_{dev.device_idx}" == target:
                return dev
        return None

    def _set_dpi(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dev = self._find_device(target)
        if dev is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        dpi = int(parameters.get("value", parameters.get("dpi", 800)))
        if dpi < 100 or dpi > 25600:
            return {"status": "failed", "message": "DPI must be 100-25600"}

        try:
            h = hid.device()
            h.open_path(dev.hid_path)
            h.set_nonblocking(True)
            while h.read(20):
                pass

            idx = dev.get_feature_index(h, _FEAT_ADJUSTABLE_DPI)
            if idx is None:
                h.close()
                return {"status": "failed", "message": "DPI feature not supported"}

            # setSensorDPI: function 2, sensor 0, DPI as uint16 BE
            hi = (dpi >> 8) & 0xFF
            lo = dpi & 0xFF
            msg = _build_hidpp_long(dev.device_idx, idx, 2, 0, hi, lo)
            h.write(msg)
            time.sleep(0.05)

            h.close()
            return {"status": "completed", "dpi": dpi}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    def _set_backlight(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dev = self._find_device(target)
        if dev is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        level = int(parameters.get("value", parameters.get("level", 50)))
        if level < 0 or level > 100:
            return {"status": "failed", "message": "Level must be 0-100"}

        try:
            h = hid.device()
            h.open_path(dev.hid_path)
            h.set_nonblocking(True)
            while h.read(20):
                pass

            idx = dev.get_feature_index(h, _FEAT_BACKLIGHT2)
            if idx is None:
                h.close()
                return {"status": "failed", "message": "Backlight feature not supported"}

            # setBacklightConfig: function 1, level
            msg = _build_hidpp_long(dev.device_idx, idx, 1, level)
            h.write(msg)
            time.sleep(0.05)

            h.close()
            return {"status": "completed", "level": level}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    def _set_smartshift(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dev = self._find_device(target)
        if dev is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        mode = parameters.get("mode", "ratchet")
        threshold = int(parameters.get("threshold", 10))
        mode_byte = 2 if mode == "freespin" else 1
        threshold = max(0, min(255, threshold))

        try:
            h = hid.device()
            h.open_path(dev.hid_path)
            h.set_nonblocking(True)
            while h.read(20):
                pass

            idx = dev.get_feature_index(h, _FEAT_SMART_SHIFT)
            if idx is None:
                h.close()
                return {"status": "failed", "message": "SmartShift not supported"}

            # setSmartShift: function 1, mode, threshold
            msg = _build_hidpp_long(dev.device_idx, idx, 1, mode_byte, threshold)
            h.write(msg)
            time.sleep(0.05)

            h.close()
            return {"status": "completed", "mode": mode, "threshold": threshold}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    def _switch_host(self, target: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import hid

        dev = self._find_device(target)
        if dev is None:
            return {"status": "failed", "message": f"Device not found: {target}"}

        host_index = int(parameters.get("host_index", parameters.get("value", 0)))

        try:
            h = hid.device()
            h.open_path(dev.hid_path)
            h.set_nonblocking(True)
            while h.read(20):
                pass

            idx = dev.get_feature_index(h, _FEAT_CHANGE_HOST)
            if idx is None:
                h.close()
                return {"status": "failed", "message": "Change Host not supported"}

            # setCurrentHost: function 1, host_index
            msg = _build_hidpp_long(dev.device_idx, idx, 1, host_index)
            h.write(msg)
            time.sleep(0.05)

            h.close()
            return {"status": "completed", "host_index": host_index}
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}

    async def teardown(self) -> None:
        self._devices.clear()
        self._receivers.clear()


COLLECTOR_CLASS = LogitechHidPPCollector
