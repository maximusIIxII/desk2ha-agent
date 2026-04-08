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

## Windows Autostart

The agent needs an interactive desktop session for DDC/CI monitor control. Use the Startup folder (not a Windows Service):

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Desk2HA Agent.vbs
```

## License

Apache-2.0
