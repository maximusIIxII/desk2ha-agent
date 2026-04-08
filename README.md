# Desk2HA Agent

Multi-vendor desktop telemetry agent for [Home Assistant](https://www.home-assistant.io/).

Collects hardware metrics, peripheral status, and display settings from Windows, Linux, and macOS — and exposes them via HTTP and MQTT for the [Desk2HA HA integration](https://github.com/maximusIIxII/hass-desk2ha).

## Features

- **Cross-platform**: Windows, Linux, macOS
- **3-tier collector model**: Platform (OS) → Generic (DDC/CI, HID, BLE) → Vendor (Dell, HP, ...)
- **Display control**: Brightness, contrast, volume, input source, KVM switch via DDC/CI
- **Dual transport**: HTTP API (OpenAPI v2.0.0) + MQTT with HA Discovery
- **Auto-discovery**: Zeroconf/mDNS (`_desk2ha._tcp.local.`)
- **Self-update**: Version check via GitHub Releases + pip upgrade
- **System tray**: Windows tray icon with status menu

## Collectors

| Tier | Collector | Metrics |
|------|-----------|---------|
| Platform | Windows (WMI + psutil) | CPU, RAM, disk, battery, network, GPU, OS info |
| Platform | Linux (sysfs + psutil) | Same as above |
| Platform | macOS (IOKit + psutil) | Same as above |
| Generic | DDC/CI | Monitor brightness, contrast, volume, input, power, KVM, PBP |
| Generic | USB PD | Charger connected, voltage, charging state |
| Generic | HeadsetControl | Headset battery, sidetone, LED, chatmix |
| Generic | HID Battery | USB peripheral battery levels |
| Generic | BLE Battery | Bluetooth device batteries |
| Vendor | Dell Command Monitor | CPU/GPU/SSD thermals, fan speeds, AC adapter wattage |

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
| GET | `/v1/commands` | Yes | List available commands |
| POST | `/v1/commands` | Yes | Execute a command (e.g. set brightness) |
| GET | `/v1/update/check` | Yes | Check for new agent release |
| POST | `/v1/update/install` | Yes | Install agent update |

## Recommended Vendor Software

The agent works out of the box with basic metrics via standard OS APIs. For **full telemetry** (detailed thermals, fan speeds, battery health, thermal profile control), install the vendor-specific software for your hardware:

### Dell

| Software | What it unlocks | Download |
|----------|----------------|----------|
| **Dell Command \| Monitor** | CPU/GPU/SSD/skin thermals, fan RPM, AC adapter wattage, thermal profile control | [Dell Support](https://www.dell.com/support/kbdoc/en-us/000177080/dell-command-monitor) |
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

### Linux (ThinkPad)

| Module | What it unlocks | How to enable |
|--------|----------------|---------------|
| `thinkpad_acpi` | Fan speed, thermal mode | Usually auto-loaded. Check: `lsmod \| grep thinkpad` |
| `ideapad_acpi` | Performance mode (IdeaPad/Legion) | Usually auto-loaded. Check: `lsmod \| grep ideapad` |

### Cross-Platform

| Software | What it unlocks | Download |
|----------|----------------|----------|
| **HeadsetControl** | Headset battery, sidetone, LED, chatmix (SteelSeries, Corsair, Logitech, HyperX) | [GitHub](https://github.com/Sapd/HeadsetControl/releases) |

> **Note:** All vendor software is optional. The agent gracefully skips collectors when the required software is not installed. You can check which collectors are active via `GET /v1/info`.

## Windows Autostart

The agent needs an interactive desktop session for DDC/CI monitor control. Use the Startup folder (not a Windows Service):

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Desk2HA Agent.vbs
```

## Known Issues

| Issue | Workaround | Status |
|-------|------------|--------|
| **DDC/CI not working as Windows Service** | DDC/CI requires an interactive desktop session (Session 1+). Use Startup folder autostart, not NSSM/Windows Service. | By design (Windows limitation) |
| **Dell Command Monitor v10.x WMI not available** | DCM v10.13 may not register the `root\dcim\sysman` WMI provider automatically. Ensure the `dcstor64` and `dcevt64` services are running. | Investigating |
| **Bluetooth peripherals not detected** | Devices connected via Dell Universal Receiver (Bluetooth/RF) are not yet enumerated. Only direct USB devices are listed. | Planned |
| **Duplicate devices after upgrade** | After upgrading from an older version, orphaned entity registry entries may create duplicate devices. Fix: delete the integration in HA and re-add it. | Known |
| **Logitech Litra G HUB conflict** | If Logitech G HUB is running, it may hold the HID interface and prevent the agent from reading Litra status. | Close G HUB or disable Litra in G HUB |

## Upcoming Features

- **Bluetooth peripheral enumeration**: Detect mouse/keyboard via Dell Universal Receiver and Logitech Bolt
- **Dell Command Monitor v10 support**: Resolve WMI provider registration for DCM v10.x
- **Webcam UVC controls**: Brightness, contrast, white balance, FOV, autofocus
- **Corsair/SteelSeries/Razer plugins**: iCUE SDK, Sonar REST, Synapse integration
- **Product image system**: Vendor-specific device silhouettes and fetched product photos
- **Remote agent installation**: Deploy agent from HA UI via SSH/WinRM
- **Prometheus endpoint**: `/metrics` in Prometheus scrape format
- **Fleet management**: Multi-agent coordination for enterprise environments

## License

Apache-2.0
