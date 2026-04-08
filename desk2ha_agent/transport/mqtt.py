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

        # Publish discovery on first connect
        if not self._discovery_published:
            self._publish_ha_discovery()
            self._publish_control_discovery()
            self._discovery_published = True

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

    def _publish_ha_discovery(self) -> None:
        """Publish HA MQTT Discovery config messages for all known sensors."""
        if self._client is None:
            return

        device_key = self._get_device_key()
        prefix = self._config.ha_discovery_prefix
        avail_topic = self._topic("availability")
        state_topic = self._topic("state")
        device_block = self._build_device_block()

        for metric_key, sensor_def in _SENSOR_DEFS.items():
            object_id = f"desk2ha_{device_key}_{metric_key}".replace(".", "_")
            config_topic = f"{prefix}/sensor/{object_id}/config"

            config_payload: dict[str, Any] = {
                "name": sensor_def["name"],
                "unique_id": object_id,
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json['{metric_key}']['value'] }}}}",
                "availability_topic": avail_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device_block,
            }

            # Add optional fields
            for opt_field in (
                "device_class",
                "unit_of_measurement",
                "state_class",
                "icon",
            ):
                if opt_field in sensor_def:
                    config_payload[opt_field] = sensor_def[opt_field]

            try:
                self._client.publish(
                    config_topic,
                    payload=json.dumps(config_payload),
                    qos=1,
                    retain=True,
                )
                logger.debug("Published discovery for %s", metric_key)
            except Exception:
                logger.debug("Failed to publish discovery for %s", metric_key, exc_info=True)

        logger.info(
            "Published HA MQTT Discovery for %d sensors on device %s",
            len(_SENSOR_DEFS),
            device_key,
        )

    def _publish_control_discovery(self) -> None:
        """Publish HA MQTT Discovery for generic display control entities."""
        if self._client is None:
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
        """Handle incoming MQTT messages (command topic)."""
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

            if self._loop and self._scheduler:
                asyncio.run_coroutine_threadsafe(
                    self._execute_command(command, target, parameters),
                    self._loop,
                )
        except (json.JSONDecodeError, KeyError):
            logger.warning("Invalid command payload on %s", msg.topic)

    async def _execute_command(
        self, command: str, target: str, parameters: dict[str, Any]
    ) -> None:
        """Route MQTT command to the appropriate collector."""
        if self._scheduler is None:
            return

        for collector in self._scheduler.collectors:
            try:
                result = await collector.execute_command(
                    command, target, parameters
                )
                logger.info("MQTT command %s completed: %s", command, result)
                return
            except NotImplementedError:
                continue
            except Exception:
                logger.exception("MQTT command %s failed", command)
                return

        logger.warning("No collector handles MQTT command: %s", command)
