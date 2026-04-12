# Desk2HA Agent

[![GitHub Release](https://img.shields.io/github/v/release/maximusIIxII/desk2ha-agent)](https://github.com/maximusIIxII/desk2ha-agent/releases)
[![PyPI](https://img.shields.io/pypi/v/desk2ha-agent)](https://pypi.org/project/desk2ha-agent/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)
[![CI](https://github.com/maximusIIxII/desk2ha-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/maximusIIxII/desk2ha-agent/actions/workflows/ci.yml)

Multi-vendor desktop telemetry agent for [Home Assistant](https://www.home-assistant.io/).

Collects hardware metrics, peripheral status, and display settings from Windows, Linux, and macOS — and exposes them via HTTP and MQTT for the [Desk2HA HA integration](https://github.com/maximusIIxII/hass-desk2ha).

## Features

- **Cross-platform**: Windows, Linux, macOS
- **3-tier collector model**: Platform (OS) → Generic (DDC/CI, HID, BLE, Bluetooth, UVC) → Vendor (Dell, HP, Lenovo, Logitech, Corsair, SteelSeries, Razer)
- **Display control**: Brightness, contrast, volume, input source, color preset, sharpness, RGB gain (R/G/B), black level (R/G/B), audio mute, KVM switch, PBP mode, auto brightness, auto color temp, smart HDR, power nap, factory reset via DDC/CI
- **Webcam control**: Brightness, contrast, saturation, sharpness, gain, gamma, white balance, focus, exposure, zoom, pan, tilt, backlight compensation, autofocus, auto WB, auto exposure via UVC
- **Litra control**: Power, brightness, color temperature for Logitech Litra Glow/Beam
- **Wireless receivers**: Dell Universal, Logitech Bolt/Unifying/Lightspeed, Jabra Link, Corsair Slipstream, Razer HyperSpeed
- **Dual transport**: HTTP API (OpenAPI v2.0.0) + MQTT with HA Discovery
- **Auto-discovery**: Zeroconf/mDNS (`_desk2ha._tcp.local.`)
- **Self-update**: Version check via GitHub Releases + pip upgrade
- **Elevated helper**: Separate process for admin-only metrics (Dell DCM WMI)
- **Vendor images**: Tier 1 generic + Tier 2 vendor-specific SVG device silhouettes
- **System tray**: Windows tray icon with status menu

## Collectors

| Tier | Collector | Metrics |
|------|-----------|---------|
| Platform | Windows (WMI + psutil) | CPU, RAM, disk, battery, network, GPU, OS info |
| Platform | Linux (sysfs + psutil) | Same as above |
| Platform | macOS (IOKit + psutil) | Same as above |
| Generic | DDC/CI | Monitor brightness, contrast, volume, input, power, color preset, sharpness, RGB gain, black level, audio mute, KVM, PBP, auto brightness, smart HDR, power nap, usage hours, firmware version, factory reset |
| Generic | UVC Webcam | Brightness, contrast, saturation, sharpness, gain, gamma, white balance, focus, exposure, zoom, pan, tilt, backlight compensation, autofocus, auto WB, auto exposure, resolution, FPS |
| Generic | USB PD | Charger connected, voltage, charging state |
| Generic | HeadsetControl | Headset battery, sidetone level, LED toggle, chat mix, set sidetone/LED/chatmix commands |
| Generic | HID Battery | USB peripheral battery levels |
| Generic | Bluetooth Peripheral | Paired BLE + Classic devices, GATT battery levels, device type classification |
| Generic | Network | WiFi RSSI/signal/SSID, Ethernet speed |
| Generic | USB Devices | Connected peripherals with VID/PID and friendly names |
| Generic | Wireless Receiver | Dell Universal, Logitech Bolt/Unifying, Jabra Link, paired device count |
| Vendor | Dell Command Monitor | CPU/GPU/SSD/skin thermals, fan speeds, AC adapter wattage (via elevated helper) |
| Vendor | HP WMI | BIOS settings, thermal profile (Windows) |
| Vendor | Lenovo WMI | Thermal mode, battery thresholds (Windows + Linux sysfs) |
| Vendor | Logitech Litra | Power, brightness (20-250 lm), color temp (2700-6500K) |
| Vendor | Corsair iCUE | HS80, Void, K70, K100, Dark Core detection + battery via cuesdk |
| Vendor | SteelSeries | Arctis Nova 7/Pro, Rival, Aerox, Apex detection |
| Vendor | SteelSeries Sonar | Per-channel volume/mute, chat-mix via GG Sonar REST API (Windows) |
| Vendor | Razer | DeathAdder, Viper, Huntsman, BlackWidow, Kraken detection |

## Installation

```bash
pip install desk2ha-agent

# Windows extras (WMI, tray icon):
pip install desk2ha-agent[windows]
```

## Quick Start

1. Create a config file (`desk2ha-agent.toml`):

```toml
[http]
enabled = true
bind = "0.0.0.0"
port = 9693
auth_token = "YOUR_RANDOM_TOKEN"
```

2. Run the agent:

```bash
desk2ha-agent --config desk2ha-agent.toml
```

3. In Home Assistant, add the [Desk2HA integration](https://github.com/maximusIIxII/hass-desk2ha) and point it to `http://<agent-ip>:9693`.

## Elevated Helper

Some metrics (e.g. Dell Command Monitor WMI) require admin privileges. The elevated helper runs as a separate process with admin rights and serves metrics via localhost HTTP:

```bash
# Start manually:
desk2ha-helper --port 9694

# Or install as Windows service (run as Administrator):
powershell -File scripts/install-helper-service.ps1
```

The agent automatically queries the helper at `http://127.0.0.1:9694` if it's running. If not, DCM metrics are simply skipped.

## Configuration

See [`examples/full-config.toml`](examples/full-config.toml) for all options.

| Section | Key Options |
|---------|-------------|
| `[http]` | `bind`, `port`, `auth_token` |
| `[mqtt]` | `broker`, `port`, `username`, `password_env`, `base_topic` |
| `[collectors]` | `disabled`, `intervals` (per-collector poll rate) |
| `[logging]` | `level` (DEBUG/INFO/WARNING) |

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/health` | No | Health check |
| GET | `/v1/info` | Yes | Device identity + collector status |
| GET | `/v1/metrics` | Yes | All collected metrics |
| GET | `/v1/image/{device_key}` | Yes | Device product image (SVG) |
| GET | `/v1/commands` | Yes | List available commands |
| POST | `/v1/commands` | Yes | Execute a command (e.g. set brightness) |
| GET | `/v1/update/check` | Yes | Check for new agent release |
| POST | `/v1/update/install` | Yes | Install agent update |

## Recommended Vendor Software

The agent works out of the box with basic metrics via standard OS APIs. For **full telemetry** (detailed thermals, fan speeds, battery health, thermal profile control), install the vendor-specific software for your hardware:

### Dell

| Software | What it unlocks | Download |
|----------|----------------|----------|
| **Dell Command \| Monitor** | CPU/GPU/SSD/skin thermals, fan RPM, AC adapter wattage, thermal profile control. Requires the [elevated helper](#elevated-helper) for WMI access. | [Dell Support](https://www.dell.com/support/kbdoc/en-us/000177080/dell-command-monitor) |
| **Dell Peripheral Manager** | Webcam settings, keyboard backlight, mouse DPI for Dell peripherals | [Dell Support](https://www.dell.com/support/kbdoc/en-us/000201446/dell-peripheral-manager) |

### HP

| Software | What it unlocks | Download |
|----------|----------------|----------|
| **HP System Event Utility** | BIOS settings, thermal profile, fan control | [HP Support](https://support.hp.com/drivers) (search your model) |
| **HP Notifications** | Battery health, power delivery info | Included with HP Support Assistant |

### Lenovo

| Software | What it unlocks | Download |
|----------|----------------|----------|
| **Lenovo Vantage** | Thermal mode, battery thresholds, keyboard backlight | [Microsoft Store](https://apps.microsoft.com/detail/9WZDNCRFJ4MV) |
| **Lenovo System Interface Foundation** | WMI access for BIOS settings, fan speed | [Lenovo Support](https://support.lenovo.com/solutions/ht503475) |

### Logitech

| Software | What it unlocks | Notes |
|----------|----------------|-------|
| **Logitech Litra Glow/Beam** | Power, brightness, color temperature control via HID | No extra software needed — agent communicates directly via USB HID. Close G HUB if it blocks the HID interface. |

### Linux (ThinkPad)

| Module | What it unlocks | How to enable |
|--------|----------------|---------------|
| `thinkpad_acpi` | Fan speed, thermal mode | Usually auto-loaded. Check: `lsmod \| grep thinkpad` |
| `ideapad_acpi` | Performance mode (IdeaPad/Legion) | Usually auto-loaded. Check: `lsmod \| grep ideapad` |

### Cross-Platform

| Software | What it unlocks | Download |
|----------|----------------|----------|
| **HeadsetControl** | Headset battery, sidetone, LED, chatmix (SteelSeries, Corsair, Logitech, HyperX) | [GitHub](https://github.com/Sapd/HeadsetControl/releases) |
| **OpenCV (opencv-python)** | UVC webcam controls (brightness, contrast, white balance, focus, zoom) | `pip install opencv-python` |

> **Note:** All vendor software is optional. The agent gracefully skips collectors when the required software is not installed. You can check which collectors are active via `GET /v1/info`.

## Windows Autostart

The agent needs an interactive desktop session for DDC/CI monitor control. Use the Startup folder (not a Windows Service):

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Desk2HA Agent.vbs
```

The elevated helper can run as a Windows Service (Session 0 is fine for WMI):

```powershell
# Run as Administrator:
powershell -File scripts/install-helper-service.ps1
```

## Known Issues

| Issue | Workaround | Status |
|-------|------------|--------|
| **DDC/CI not working as Windows Service** | DDC/CI requires an interactive desktop session (Session 1+). Use Startup folder autostart, not NSSM/Windows Service. | By design (Windows limitation) |
| **Dell Command Monitor needs admin** | DCM WMI namespace requires elevated privileges. Use the [elevated helper](#elevated-helper) service. | Solved (v0.3.0+) |
| **Logitech Litra G HUB conflict** | If Logitech G HUB is running, it may hold the HID interface and prevent the agent from reading Litra status. | Close G HUB or disable Litra in G HUB |

## Upcoming Features

- **Prometheus endpoint**: `/metrics` in Prometheus scrape format
- **SteelSeries/Razer battery**: Battery levels via HID for wireless peripherals
- **macOS Bluetooth**: CoreBluetooth support for paired device enumeration
- **Logitech HID++**: Wireless peripheral metrics via HID++ protocol
- **USB PD Dock Monitoring**: Thunderbolt/USB4 dock-specific metrics

## License

Apache-2.0
