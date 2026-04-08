# Desk2HA Agent

Multi-vendor desktop telemetry agent for [Home Assistant](https://www.home-assistant.io/).

Collects hardware and peripheral metrics from Windows, Linux, and macOS endpoints
and exposes them via HTTP API and MQTT for the
[Desk2HA integration](https://github.com/maximusIIxII/hass-desk2ha).

## Features

- **Cross-platform**: Windows, Linux, macOS
- **Multi-vendor**: Dell, HP, Lenovo, Logitech, Corsair, SteelSeries
- **Multi-protocol**: DDC/CI monitors, BLE/HID peripherals, USB-C docks
- **Extensible**: Plugin system for vendor-specific collectors

## Installation

```bash
pip install desk2ha-agent
```

## Quick Start

```bash
python -m desk2ha_agent
```

## Documentation

See the [Desk2HA integration](https://github.com/maximusIIxII/hass-desk2ha) for
Home Assistant setup instructions.

## License

Apache-2.0
