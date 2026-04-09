# Changelog

All notable changes to the Desk2HA Agent will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/) with emoji categories.

## [0.5.1] - 2026-04-09

### 🐛 Bug fixes
- **Litra HID reads restored**: HID polling confirmed safe — reads do NOT wake the Litra. Previous false positive was caused by HA Light entity state restore. Brightness/color temp reads still skipped when light is off (reduces HID traffic).

## [0.5.0] - 2026-04-09

### ✨ New features
- **Bluetooth Peripheral Collector**: enumerate paired BLE + Classic devices on Windows (WinRT) and Linux/macOS (bleak), read GATT battery levels, auto-classify device types (keyboard, mouse, headset, earbuds)
- **SteelSeries Sonar REST Bridge**: read volume/mute per channel + chat-mix from SteelSeries GG Sonar app via local REST API with auto-discovery of random port
- **Corsair iCUE Battery**: read wireless device battery levels via official `cuesdk` (CDPI_BatteryLevel), graceful fallback to HID-only mode

### 🔧 Improvements
- Network collector filters loopback, virtual adapters, and interfaces with zero traffic

## [0.4.1] - 2026-04-09

### 🐛 Bug fixes
- DDC/CI `execute_command` now rejects non-display commands (was crashing on Litra commands)
- USB Enum skips wireless receivers handled by `wireless_receiver` collector

## [0.4.0] - 2026-04-09

### ✨ New features
- **UVC Webcam Controls**: resolution, FPS, hue, gain, gamma, focus, pan, tilt, backlight compensation, auto_exposure + 14 new set commands
- **Product Images Tier 2**: Vendor-specific SVG silhouettes for Dell (Precision, Latitude, OptiPlex, UltraSharp), HP (EliteBook, ZBook), Lenovo (ThinkPad, ThinkStation), Apple (MacBook)
- **Wireless Receiver Detection**: Dell Universal, Logitech Bolt/Unifying/Lightspeed/Nano, Jabra Link 380/390, SteelSeries, Corsair Slipstream, Razer HyperSpeed via HID enumeration
- **Corsair iCUE Plugin**: HS80, Void, K70, K100, Dark Core peripheral detection
- **SteelSeries Plugin**: Arctis Nova 7/Pro, Rival, Aerox, Apex peripheral detection
- **Razer Plugin**: DeathAdder, Viper, Huntsman, BlackWidow, Kraken peripheral detection

### 🔧 Improvements
- `/v1/image` endpoint upgraded to Tier 2 vendor matching with Tier 1 fallback
- Ruff lint per-file-ignores extended to all `images/*.py` files

## [0.3.0] - 2026-04-09

### ✨ New features
- **Elevated Helper Process**: Separate `desk2ha-helper` binary runs with admin privileges, serves DCM WMI metrics via localhost HTTP on port 9694
- **PyPI Trusted Publishing**: Release workflow publishes to PyPI via OIDC (no token needed)
- **`desk2ha-helper` CLI**: Entry point with admin check, signal handling, log rotation

### 🔧 Improvements
- **Dell DCM Collector**: Dual-mode — tries direct WMI if admin, falls back to helper client
- **DCM Sensor Mapping**: NB → northbridge, OTHER → misc, "Processor Fan" → fan.cpu
- **DCM Thermal Key Map**: Specific patterns before generic ones (cpu core before cpu)
- **CI hardened**: Tests required (removed `|| true`), lint covers `tests/`, Python 3.13 added to matrix
- **Test coverage**: 38 → 105 tests (+67)
  - Network, USB PD, USB Devices, Litra, System Actions, DCM, MQTT Transport, Helper (server, client, registry)

### 🐛 Bug fixes
- Lint issues in existing tests (unused imports, lambda expressions, formatting)

## [0.2.1] - 2026-04-08

### ✨ New features
- **Logitech Litra Glow/Beam**: Power, brightness (20-250 lm), color temperature (2700-6500K) via USB HID
- **USB Device Enumeration**: Connected peripherals with VID/PID and friendly name lookup (16 known devices)
- **Network Collector**: WiFi RSSI/signal/SSID, Ethernet speed
- **System Actions**: Lock screen, sleep, shutdown, hibernate commands
- **Product Images Tier 1**: 8 generic SVG device icons (notebook, desktop, monitor, keyboard, mouse, headset, dock, workstation)
- **Agent Metrics**: agent.version, agent.uptime reported as metrics
- **Dynamic MQTT Discovery**: Only publishes discovery for metrics actually present

### 🐛 Bug fixes
- Network metrics no longer appear under thermals category
- Generic USB devices filtered from enumeration
- Litra HID reads use proper flush and timing
- Litra collector only uses correct HID interface (0xFF43)
- Manufacturer prefix removed from model names

## [0.2.0] - 2026-04-08

### ✨ New features
- **HP WMI Vendor Plugin**: BIOS settings, thermal profile (Windows)
- **Lenovo WMI Vendor Plugin**: Thermal mode, battery thresholds (Windows + Linux sysfs)
- **Network Collector**: WiFi RSSI, Ethernet speed, SSID
- **6 DDC/CI VCP Toggle Commands**: Auto brightness, auto color temp, etc.
- **Dell Thermal Profile Command**: Set thermal profile via DCM WMI
- **agent.restart + agent.update commands**
- **38 unit tests**

### 🔧 Improvements
- Dynamic MQTT Discovery (only present metrics)
- Comprehensive README with vendor software links

## [0.1.1] - 2026-04-08

### ✨ New features
- **Zeroconf/mDNS Advertisement**: `_desk2ha._tcp.local.`
- **Tray Icon**: Windows system tray with pystray
- **MQTT Command Routing**: Subscribe + route to collectors
- **CLI Entry Point**: `desk2ha-agent` command via pyproject.toml

### 🐛 Bug fixes
- Command wiring for display controls (HTTP + MQTT)

## [0.1.0] - 2026-04-08

### ✨ New features
- **Initial release**
- Platform Collectors: Windows (WMI + psutil), Linux (sysfs + psutil), macOS (IOKit + psutil)
- Generic Collectors: DDC/CI, HID Battery, BLE Battery, UVC Webcam, HeadsetControl, USB PD
- Dell Command Monitor Vendor Plugin
- Plugin Registry with auto-discovery (probe/setup lifecycle)
- TOML Config Loader (Pydantic-validated, DESK2HA_* env vars)
- State Cache (asyncio-safe, callback-based) + Scheduler with per-collector intervals
- HTTP Transport (aiohttp, Bearer Auth, OpenAPI v2.0.0)
- MQTT Transport (paho-mqtt, HA Discovery, LWT Availability)
- Agent Lifecycle: self-update, config API, service restart
