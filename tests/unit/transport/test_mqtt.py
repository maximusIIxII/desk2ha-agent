"""Tests for MQTT transport."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from desk2ha_agent.transport.mqtt import MqttTransport, _auto_name


def test_auto_name_system_metrics():
    assert _auto_name("system.cpu_usage_percent") == "Cpu Usage Percent"
    assert _auto_name("system.ram_used_gb") == "Ram Used Gb"


def test_auto_name_display_metrics():
    assert _auto_name("display.0.brightness_percent") == "Display 0 Brightness Percent"


def test_auto_name_agent_metrics():
    assert _auto_name("agent.version") == "Version"
    assert _auto_name("agent.uptime") == "Uptime"


def test_auto_name_peripheral():
    result = _auto_name("peripheral.litra_0.brightness_lumen")
    assert "Peripheral" in result
    assert "litra_0" in result


def test_auto_name_unknown():
    assert _auto_name("custom_metric") == "Custom Metric"


@pytest.fixture
def mqtt_config():
    cfg = MagicMock()
    cfg.broker = "localhost"
    cfg.port = 1883
    cfg.username = ""
    cfg.password = ""
    cfg.tls = False
    cfg.base_topic = "desk2ha"
    cfg.ha_discovery_prefix = "homeassistant"
    return cfg


@pytest.fixture
def mqtt_transport(mqtt_config):
    state = MagicMock()
    info = MagicMock()
    info.get_device_key.return_value = "TEST-001"
    info.get_hardware.return_value = {
        "manufacturer": "Dell Inc.",
        "model": "Precision 5770",
        "serial_number": "TEST-001",
    }
    return MqttTransport(config=mqtt_config, state=state, info_provider=info)


def test_topic_building(mqtt_transport):
    assert mqtt_transport._topic("state") == "desk2ha/TEST-001/state"
    assert mqtt_transport._topic("availability") == "desk2ha/TEST-001/availability"
    assert mqtt_transport._topic("command") == "desk2ha/TEST-001/command"


def test_device_block(mqtt_transport):
    block = mqtt_transport._build_device_block()
    assert block["identifiers"] == ["desk2ha_TEST-001"]
    assert block["manufacturer"] == "Dell Inc."
    assert block["model"] == "Precision 5770"
    assert block["serial_number"] == "TEST-001"


def test_device_block_no_provider(mqtt_config):
    state = MagicMock()
    t = MqttTransport(config=mqtt_config, state=state, info_provider=None)
    block = t._build_device_block()
    assert "desk2ha_DESK-DEV0001" in block["identifiers"][0]
    assert "manufacturer" not in block


def test_on_state_update_not_connected(mqtt_transport):
    mqtt_transport._connected = False
    mqtt_transport._client = MagicMock()
    # Should not publish anything
    mqtt_transport._on_state_update({"test": {"value": 1}})
    mqtt_transport._client.publish.assert_not_called()


def test_on_state_update_publishes(mqtt_transport):
    client = MagicMock()
    mqtt_transport._client = client
    mqtt_transport._connected = True
    mqtt_transport._discovery_published = True

    metrics = {"system.cpu_usage_percent": {"value": 42.0, "timestamp": 1.0}}
    mqtt_transport._on_state_update(metrics)

    client.publish.assert_called_once()
    call_args = client.publish.call_args
    kwargs = call_args[1]
    assert kwargs["qos"] == 0
    assert kwargs["retain"] is True
    payload = json.loads(kwargs["payload"])
    assert payload["system.cpu_usage_percent"]["value"] == 42.0


def test_on_message_valid_command(mqtt_transport):
    mqtt_transport._connected = True
    mqtt_transport._client = MagicMock()
    mqtt_transport._loop = MagicMock()
    mqtt_transport._scheduler = MagicMock()

    msg = MagicMock()
    msg.topic = "desk2ha/TEST-001/command"
    msg.payload = json.dumps(
        {
            "command": "display.set_brightness",
            "target": "display.0",
            "parameters": {"brightness": 80},
        }
    ).encode()

    with patch("desk2ha_agent.transport.mqtt.asyncio") as mock_asyncio:
        mqtt_transport._on_message(mqtt_transport._client, None, msg)
        mock_asyncio.run_coroutine_threadsafe.assert_called_once()


def test_on_message_invalid_json(mqtt_transport):
    mqtt_transport._connected = True
    mqtt_transport._client = MagicMock()

    msg = MagicMock()
    msg.topic = "desk2ha/TEST-001/command"
    msg.payload = b"not json"

    # Should not raise
    mqtt_transport._on_message(mqtt_transport._client, None, msg)


def test_on_message_wrong_topic(mqtt_transport):
    mqtt_transport._loop = MagicMock()
    mqtt_transport._scheduler = MagicMock()

    msg = MagicMock()
    msg.topic = "desk2ha/OTHER/command"
    msg.payload = json.dumps({"command": "test"}).encode()

    with patch("desk2ha_agent.transport.mqtt.asyncio") as mock_asyncio:
        mqtt_transport._on_message(mqtt_transport._client, None, msg)
        mock_asyncio.run_coroutine_threadsafe.assert_not_called()
