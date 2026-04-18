"""MQTT transport with Home Assistant Discovery support."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import paho.mqtt.client as mqtt_client

from desk2ha_agent import __version__
from desk2ha_agent.transport.base import Transport

if TYPE_CHECKING:
    from desk2ha_agent.collector.base import DeviceInfoProvider
    from desk2ha_agent.config import MqttConfig
    from desk2ha_agent.state import StateCache

logger = logging.getLogger(__name__)

# Map metric keys to HA MQTT Discovery config.
# Kept from Dell HA: system, thermal, battery, power sensors.
# Removed: Dell-specific peripheral/webcam sensors (KB900, MS900, WB7022).
# Added: generic display, audio, peripheral categories.
_SENSOR_DEFS: dict[str, dict[str, str]] = {
    # --- Thermal ---
    "cpu_package": {
        "name": "CPU Package Temperature",
        "device_class": "temperature",
        "unit_of_measurement": "\u00b0C",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
    },
    "fan.0": {
        "name": "CPU Fan",
        "icon": "mdi:fan",
        "unit_of_measurement": "RPM",
        "state_class": "measurement",
    },
    "fan.gpu": {
        "name": "GPU Fan",
        "icon": "mdi:fan",
        "unit_of_measurement": "RPM",
        "state_class": "measurement",
    },
    "skin": {
        "name": "Skin Temperature",
        "device_class": "temperature",
        "unit_of_measurement": "\u00b0C",
        "state_class": "measurement",
    },
    # --- Battery ---
    "battery.level_percent": {
        "name": "Battery Level",
        "device_class": "battery",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "battery.state": {
        "name": "Battery State",
        "icon": "mdi:battery-charging",
    },
    # --- Power ---
    "power.ac_adapter_watts": {
        "name": "AC Adapter",
        "device_class": "power",
        "unit_of_measurement": "W",
        "state_class": "measurement",
    },
    # --- System metrics (psutil live) ---
    "system.cpu_usage_percent": {
        "name": "CPU Usage",
        "icon": "mdi:cpu-64-bit",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "system.cpu_frequency_mhz": {
        "name": "CPU Frequency",
        "icon": "mdi:speedometer",
        "unit_of_measurement": "MHz",
        "state_class": "measurement",
    },
    "system.ram_usage_percent": {
        "name": "RAM Usage",
        "icon": "mdi:memory",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "system.ram_used_gb": {
        "name": "RAM Used",
        "icon": "mdi:memory",
        "unit_of_measurement": "GB",
        "state_class": "measurement",
    },
    "system.ram_total_gb": {
        "name": "RAM Total",
        "icon": "mdi:memory",
        "unit_of_measurement": "GB",
    },
    "system.swap_usage_percent": {
        "name": "Swap Usage",
        "icon": "mdi:swap-horizontal",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "system.disk_usage_percent": {
        "name": "Disk Usage",
        "icon": "mdi:harddisk",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "system.disk_free_gb": {
        "name": "Disk Free",
        "icon": "mdi:harddisk",
        "unit_of_measurement": "GB",
        "state_class": "measurement",
    },
    "system.net_sent_mb": {
        "name": "Network Sent",
        "icon": "mdi:upload",
        "unit_of_measurement": "MB",
        "state_class": "total_increasing",
    },
    "system.net_recv_mb": {
        "name": "Network Received",
        "icon": "mdi:download",
        "unit_of_measurement": "MB",
        "state_class": "total_increasing",
    },
    "system.uptime_hours": {
        "name": "Uptime",
        "icon": "mdi:clock-outline",
        "unit_of_measurement": "h",
        "state_class": "measurement",
    },
    "system.process_count": {
        "name": "Process Count",
        "icon": "mdi:format-list-numbered",
        "state_class": "measurement",
    },
    # --- System metrics (static / diagnostics) ---
    "system.cpu_model": {
        "name": "CPU Model",
        "icon": "mdi:cpu-64-bit",
    },
    "system.cpu_cores": {
        "name": "CPU Cores",
        "icon": "mdi:cpu-64-bit",
    },
    "system.cpu_threads": {
        "name": "CPU Threads",
        "icon": "mdi:cpu-64-bit",
    },
    "system.gpu_model": {
        "name": "GPU Model",
        "icon": "mdi:expansion-card",
    },
    "system.gpu_vram_gb": {
        "name": "GPU VRAM",
        "icon": "mdi:expansion-card",
        "unit_of_measurement": "GB",
    },
    "system.gpu_driver": {
        "name": "GPU Driver",
        "icon": "mdi:expansion-card",
    },
    "system.screen_resolution": {
        "name": "Screen Resolution",
        "icon": "mdi:monitor",
    },
    "system.os_name": {
        "name": "OS Name",
        "icon": "mdi:monitor",
    },
    "system.os_version": {
        "name": "OS Version",
        "icon": "mdi:monitor",
    },
    "system.os_build": {
        "name": "OS Build",
        "icon": "mdi:monitor",
    },
    "system.bios_version": {
        "name": "BIOS Version",
        "icon": "mdi:chip",
    },
    "system.disk_model": {
        "name": "Disk Model",
        "icon": "mdi:harddisk",
    },
    # --- Generic display sensors ---
    "display.0.brightness_percent": {
        "name": "Display Brightness",
        "icon": "mdi:brightness-6",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "display.0.volume": {
        "name": "Display Volume",
        "icon": "mdi:volume-high",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "display.0.power_state": {
        "name": "Display Power State",
        "icon": "mdi:power",
    },
    "display.0.input_source": {
        "name": "Display Input Source",
        "icon": "mdi:video-input-hdmi",
    },
    # --- Generic audio sensors ---
    "audio.0.volume_percent": {
        "name": "System Volume",
        "icon": "mdi:volume-high",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "audio.0.muted": {
        "name": "System Muted",
        "icon": "mdi:volume-off",
    },
}

# Display control keys — handled by _publish_control_discovery, skip as sensors
_DISPLAY_CONTROL_KEYS = {
    "brightness_percent",
    "contrast_percent",
    "volume",
    "input_source",
    "power_state",
    "kvm_active_pc",
    "pbp_mode",
}


def _auto_name(metric_key: str) -> str:
    """Generate a human-readable name from a metric key."""
    parts = metric_key.split(".")
    if len(parts) >= 2 and parts[0] in ("system", "agent", "power"):
        name_part = ".".join(parts[1:])
    elif len(parts) >= 3 and parts[0] in ("display", "peripheral", "audio"):
        suffix = " ".join(p.replace("_", " ").title() for p in parts[2:])
        return f"{parts[0].title()} {parts[1]} {suffix}"
    else:
        name_part = metric_key
    return name_part.replace("_", " ").replace(".", " ").title()


class MqttTransport(Transport):
    """Publishes metrics to MQTT with HA Discovery payloads."""

    def __init__(
        self,
        config: MqttConfig,
        state: StateCache,
        info_provider: DeviceInfoProvider | None = None,
        scheduler: Any = None,
    ) -> None:
        self._config = config
        self._state = state
        self._info_provider = info_provider
        self._scheduler = scheduler
        self._client: mqtt_client.Client | None = None
        self._connected = False
        self._discovery_published = False
        self._discovered_keys: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Connect to MQTT broker and register state callback."""
        self._loop = asyncio.get_running_loop()

        client = mqtt_client.Client(
            callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=f"desk2ha-{self._get_device_key()}",
        )

        if self._config.username:
            client.username_pw_set(self._config.username, self._config.password)

        if self._config.tls:
            client.tls_set()

        # LWT (Last Will and Testament) for availability
        avail_topic = self._topic("availability")
        client.will_set(avail_topic, payload="offline", qos=1, retain=True)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        try:
            client.connect_async(self._config.broker, self._config.port)
            client.loop_start()
            self._client = client
            logger.info(
                "MQTT transport connecting to %s:%d",
                self._config.broker,
                self._config.port,
            )
        except Exception:
            logger.exception("Failed to start MQTT transport")
            return

        # Register callback for state updates
        self._state.register_callback(self._on_state_update)

    async def stop(self) -> None:
        """Disconnect from MQTT broker."""
        self._state.unregister_callback(self._on_state_update)

        if self._client is not None:
            # Publish offline before disconnecting
            avail_topic = self._topic("availability")
            self._client.publish(avail_topic, payload="offline", qos=1, retain=True)
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("MQTT transport stopped")

    def _get_device_key(self) -> str:
        if self._info_provider is not None:
            key = self._info_provider.get_device_key()
            if key is not None:
                return key
        return "DESK-DEV0001"

    def _topic(self, suffix: str) -> str:
        """Build a topic path under the base topic."""
        return f"{self._config.base_topic}/{self._get_device_key()}/{suffix}"

    def _on_connect(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        flags: Any,
        rc: Any,
        properties: Any = None,
    ) -> None:
        """Called when connected to broker."""
        self._connected = True
        logger.info("MQTT connected to %s:%d", self._config.broker, self._config.port)

        # Publish availability
        client.publish(self._topic("availability"), payload="online", qos=1, retain=True)

        # Subscribe to command topic
        cmd_topic = self._topic("command")
        client.subscribe(cmd_topic, qos=1)
        logger.info("MQTT subscribed to %s", cmd_topic)

        # Subscribe to config topic for runtime configuration
        config_topic = self._topic("config/set")
        client.subscribe(config_topic, qos=1)
        logger.info("MQTT subscribed to %s", config_topic)

        # Discovery is published on first state update (when metrics are available)

    def _on_disconnect(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        flags: Any = None,
        rc: Any = None,
        properties: Any = None,
    ) -> None:
        """Called when disconnected from broker."""
        self._connected = False
        if rc != 0:
            logger.warning("MQTT disconnected unexpectedly (rc=%s), will reconnect", rc)
        else:
            logger.info("MQTT disconnected")

    def _on_state_update(self, metrics: dict[str, Any]) -> None:
        """Called by StateCache when metrics are updated."""
        if not self._connected or self._client is None:
            return

        # Publish discovery for any new metric keys not yet announced.
        # On first update this covers everything; on subsequent updates it
        # catches metrics from slow collectors (BT, USB) that arrive later.
        new_keys = set(metrics.keys()) - self._discovered_keys
        if new_keys:
            self._publish_ha_discovery(metrics, only_keys=new_keys)
            if not self._discovery_published:
                self._publish_control_discovery(metrics)
            self._discovery_published = True
            self._discovered_keys.update(metrics.keys())
            # Re-publish availability — the device key may have changed
            # since initial connect (platform collector sets real key).
            self._client.publish(self._topic("availability"), payload="online", qos=1, retain=True)

        device_key = self._get_device_key()
        state_topic = self._topic("state")

        # Build a flat state payload
        payload: dict[str, Any] = {"device_key": device_key, "timestamp": time.time()}
        for key, metric in metrics.items():
            payload[key] = metric

        try:
            self._client.publish(
                state_topic,
                payload=json.dumps(payload),
                qos=0,
                retain=True,
            )
        except Exception:
            logger.debug("Failed to publish MQTT state", exc_info=True)

    def _build_device_block(self) -> dict[str, Any]:
        """Build the MQTT discovery device block (multi-vendor, no Dell defaults)."""
        device_key = self._get_device_key()
        block: dict[str, Any] = {
            "identifiers": [f"desk2ha_{device_key}"],
            "name": f"Desk2HA {device_key}",
            "sw_version": __version__,
        }

        if self._info_provider is not None:
            hw = self._info_provider.get_hardware()
            if hw is not None:
                manufacturer = hw.get("manufacturer")
                if manufacturer:
                    block["manufacturer"] = manufacturer
                model = hw.get("model")
                if model:
                    block["model"] = model
                serial = hw.get("serial_number")
                if serial:
                    block["serial_number"] = serial

        return block

    def _publish_ha_discovery(
        self,
        metrics: dict[str, Any],
        only_keys: set[str] | None = None,
    ) -> None:
        """Publish HA MQTT Discovery for metrics actually present in state."""
        if self._client is None:
            return

        device_key = self._get_device_key()
        prefix = self._config.ha_discovery_prefix
        avail_topic = self._topic("availability")
        state_topic = self._topic("state")
        device_block = self._build_device_block()
        count = 0

        exclude = self._config.discovery_exclude_prefixes

        for metric_key in metrics:
            if only_keys is not None and metric_key not in only_keys:
                continue
            # Skip prefixes handled by the HTTP custom component (sub-devices)
            if exclude and any(metric_key.startswith(p) for p in exclude):
                continue
            # Skip display control keys (handled by _publish_control_discovery)
            suffix = metric_key.rsplit(".", 1)[-1]
            if suffix in _DISPLAY_CONTROL_KEYS:
                continue

            sensor_def = _SENSOR_DEFS.get(metric_key)
            name = sensor_def["name"] if sensor_def else _auto_name(metric_key)
            object_id = f"desk2ha_{device_key}_{metric_key}".replace(".", "_")
            config_topic = f"{prefix}/sensor/{object_id}/config"

            config_payload: dict[str, Any] = {
                "name": name,
                "unique_id": object_id,
                "state_topic": state_topic,
                "value_template": (f"{{{{ value_json['{metric_key}']['value'] }}}}"),
                "availability_topic": avail_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device_block,
            }

            if sensor_def:
                for field in ("device_class", "unit_of_measurement", "state_class", "icon"):
                    if field in sensor_def:
                        config_payload[field] = sensor_def[field]

            try:
                self._client.publish(
                    config_topic,
                    payload=json.dumps(config_payload),
                    qos=1,
                    retain=True,
                )
                count += 1
            except Exception:
                logger.debug("Failed to publish discovery for %s", metric_key, exc_info=True)

        logger.info(
            "Published HA MQTT Discovery for %d sensors on device %s",
            count,
            device_key,
        )

    def _publish_control_discovery(self, metrics: dict[str, Any]) -> None:
        """Publish HA MQTT Discovery for display control entities found in metrics."""
        if self._client is None:
            return

        # Only publish if display metrics exist
        has_display = any(k.startswith("display.") for k in metrics)
        if not has_display:
            return

        device_key = self._get_device_key()
        prefix = self._config.ha_discovery_prefix
        avail_topic = self._topic("availability")
        state_topic = self._topic("state")
        cmd_topic = self._topic("command")
        device_block = self._build_device_block()

        # Number: display brightness
        brightness_id = f"desk2ha_{device_key}_display_0_brightness"
        self._client.publish(
            f"{prefix}/number/{brightness_id}/config",
            payload=json.dumps(
                {
                    "name": "Brightness",
                    "unique_id": brightness_id,
                    "command_topic": cmd_topic,
                    "command_template": json.dumps(
                        {
                            "command": "display.set_brightness",
                            "target": "display.0",
                            "parameters": {"brightness": "{{ value | int }}"},
                        }
                    ),
                    "state_topic": state_topic,
                    "value_template": (
                        "{{ value_json['display.0.brightness_percent']['value'] | default(0) }}"
                    ),
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "unit_of_measurement": "%",
                    "icon": "mdi:brightness-6",
                    "availability_topic": avail_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "device": device_block,
                }
            ),
            qos=1,
            retain=True,
        )

        # Select: display input source
        input_id = f"desk2ha_{device_key}_display_0_input"
        options = ["DP1", "DP2", "HDMI1", "HDMI2", "USBC1", "USBC2"]
        self._client.publish(
            f"{prefix}/select/{input_id}/config",
            payload=json.dumps(
                {
                    "name": "Input Source",
                    "unique_id": input_id,
                    "command_topic": cmd_topic,
                    "command_template": json.dumps(
                        {
                            "command": "display.set_input_source",
                            "target": "display.0",
                            "parameters": {"input_source": "{{ value }}"},
                        }
                    ),
                    "state_topic": state_topic,
                    "value_template": (
                        "{{ value_json['display.0.input_source']['value'] | default('unknown') }}"
                    ),
                    "options": options,
                    "icon": "mdi:video-input-hdmi",
                    "availability_topic": avail_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "device": device_block,
                }
            ),
            qos=1,
            retain=True,
        )

        # Number: display volume
        volume_id = f"desk2ha_{device_key}_display_0_volume"
        self._client.publish(
            f"{prefix}/number/{volume_id}/config",
            payload=json.dumps(
                {
                    "name": "Volume",
                    "unique_id": volume_id,
                    "command_topic": cmd_topic,
                    "command_template": json.dumps(
                        {
                            "command": "display.set_volume",
                            "target": "display.0",
                            "parameters": {"volume": "{{ value | int }}"},
                        }
                    ),
                    "state_topic": state_topic,
                    "value_template": (
                        "{{ value_json['display.0.volume']['value'] | default(0) }}"
                    ),
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "unit_of_measurement": "%",
                    "icon": "mdi:volume-high",
                    "availability_topic": avail_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "device": device_block,
                }
            ),
            qos=1,
            retain=True,
        )

        # Select: display power state
        power_id = f"desk2ha_{device_key}_display_0_power_state"
        self._client.publish(
            f"{prefix}/select/{power_id}/config",
            payload=json.dumps(
                {
                    "name": "Power State",
                    "unique_id": power_id,
                    "command_topic": cmd_topic,
                    "command_template": json.dumps(
                        {
                            "command": "display.set_power_state",
                            "target": "display.0",
                            "parameters": {"power_state": "{{ value }}"},
                        }
                    ),
                    "state_topic": state_topic,
                    "value_template": (
                        "{{ value_json['display.0.power_state']['value'] | default('unknown') }}"
                    ),
                    "options": ["on", "standby", "off"],
                    "icon": "mdi:power",
                    "availability_topic": avail_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                    "device": device_block,
                }
            ),
            qos=1,
            retain=True,
        )

        logger.info("Published HA MQTT Discovery for display control entities")

    def _on_message(
        self,
        client: mqtt_client.Client,
        userdata: Any,
        msg: mqtt_client.MQTTMessage,
    ) -> None:
        """Handle incoming MQTT messages (command + config topics)."""
        config_topic = self._topic("config/set")
        if msg.topic == config_topic:
            self._handle_config_message(msg)
            return

        cmd_topic = self._topic("command")
        if msg.topic != cmd_topic:
            return

        try:
            payload = json.loads(msg.payload.decode())
            command = payload.get("command", "")
            target = payload.get("target", "")
            parameters = payload.get("parameters", {})

            if not command:
                logger.warning("MQTT command missing 'command' field")
                return

            logger.info("MQTT command received: %s target=%s", command, target)

            # Agent-level commands handled directly (not routed to collectors)
            if command in (
                "system.lock",
                "system.sleep",
                "system.shutdown",
                "system.hibernate",
                "system.kvm_diagnose",
                "remote.wake_on_lan",
            ):
                if self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._execute_agent_command(command, parameters),
                        self._loop,
                    )
                return

            if self._loop and self._scheduler:
                asyncio.run_coroutine_threadsafe(
                    self._execute_command(command, target, parameters),
                    self._loop,
                )
        except (json.JSONDecodeError, KeyError):
            logger.warning("Invalid command payload on %s", msg.topic)

    def _handle_config_message(self, msg: mqtt_client.MQTTMessage) -> None:
        """Handle config topic messages for runtime configuration.

        Expected payload: {"intervals": {"network": 10, "ddcci": 60}}
        Publishes current config to config/state after applying changes.
        """
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid config payload on %s", msg.topic)
            return

        changed = False

        # Update collector intervals
        intervals = payload.get("intervals")
        if isinstance(intervals, dict) and self._scheduler:
            for name, interval in intervals.items():
                if (
                    isinstance(interval, int | float)
                    and interval >= 1
                    and self._scheduler.update_interval(name, float(interval))
                ):
                    changed = True

        if changed:
            logger.info("Config updated via MQTT")
            # Publish current config state
            self._publish_config_state()

    def _publish_config_state(self) -> None:
        """Publish current runtime config to config/state topic."""
        if self._client is None or not self._connected:
            return
        state: dict[str, Any] = {}
        if self._scheduler:
            state["intervals"] = dict(self._scheduler._intervals)
            state["collectors"] = [c.meta.name for c in self._scheduler.collectors]
        try:
            self._client.publish(
                self._topic("config/state"),
                payload=json.dumps(state),
                qos=1,
                retain=True,
            )
        except Exception:
            logger.debug("Failed to publish config state", exc_info=True)

    async def _execute_agent_command(self, command: str, parameters: dict[str, Any]) -> None:
        """Handle agent-level commands (not routed to collectors)."""
        from desk2ha_agent.lifecycle import system_actions

        try:
            if command == "remote.wake_on_lan":
                mac = parameters.get("mac", "")
                if mac:
                    await system_actions.wake_on_lan(mac)
            elif command == "system.lock":
                await system_actions.lock_screen()
            elif command == "system.sleep":
                await system_actions.sleep_system()
            elif command == "system.shutdown":
                await system_actions.shutdown_system(parameters.get("delay", 0))
            elif command == "system.hibernate":
                await system_actions.hibernate_system()
            elif command == "system.kvm_diagnose":
                from desk2ha_agent.lifecycle.kvm_diagnose import kvm_diagnose

                await kvm_diagnose()
        except Exception:
            logger.exception("Agent command %s failed", command)

    async def _execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> None:
        """Route MQTT command to the appropriate collector."""
        if self._scheduler is None:
            return

        for collector in self._scheduler.collectors:
            try:
                result = await collector.execute_command(command, target, parameters)
                logger.info("MQTT command %s completed: %s", command, result)
                return
            except NotImplementedError:
                continue
            except Exception:
                logger.exception("MQTT command %s failed", command)
                return

        logger.warning("No collector handles MQTT command: %s", command)
