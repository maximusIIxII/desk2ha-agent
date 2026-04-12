"""TOML config loader and validation."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator


class HttpConfig(BaseModel):
    """HTTP transport configuration."""

    enabled: bool = True
    bind: str = "127.0.0.1"
    port: int = 9693
    auth_token: str | None = None
    auth_token_env: str = "DESK2HA_HTTP_TOKEN"

    @model_validator(mode="after")
    def _resolve_token(self) -> HttpConfig:
        if self.auth_token is None:
            self.auth_token = os.environ.get(self.auth_token_env)
        if self.enabled and not self.auth_token:
            msg = (
                "HTTP transport enabled but no auth_token set. "
                "Set auth_token in config or DESK2HA_HTTP_TOKEN env var."
            )
            raise ValueError(msg)
        return self


class MqttConfig(BaseModel):
    """MQTT transport configuration."""

    enabled: bool = False
    broker: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    password_env: str = "DESK2HA_MQTT_PASS"
    base_topic: str = "desk2ha"
    tls: bool = False
    ha_discovery_prefix: str = "homeassistant"

    @model_validator(mode="after")
    def _resolve_password(self) -> MqttConfig:
        if self.password is None and self.password_env:
            self.password = os.environ.get(self.password_env)
        return self


class BleBatteryConfig(BaseModel):
    """BLE battery collector config."""

    enabled: bool = False
    scan_duration: int = 5
    filter_known_only: bool = True


class HelperConfig(BaseModel):
    """Elevated helper configuration."""

    secret: str | None = None
    secret_env: str = "DESK2HA_HELPER_SECRET"
    port: int = 9694
    host: str = "127.0.0.1"

    @model_validator(mode="after")
    def _resolve_secret(self) -> HelperConfig:
        if self.secret is None:
            self.secret = os.environ.get(self.secret_env)
        return self


class CollectorsConfig(BaseModel):
    """Collector configuration."""

    disabled: list[str] = []
    intervals: dict[str, int] = {}
    ble_battery: BleBatteryConfig = BleBatteryConfig()


class ProvisioningConfig(BaseModel):
    """Phone-home provisioning (auto-removed after first connect)."""

    phone_home_url: str = ""
    phone_home_token: str = ""


class AgentSection(BaseModel):
    """Top-level [agent] section."""

    device_name: str | Literal["auto"] = "auto"


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    file_max_bytes: int = 5 * 1024 * 1024
    file_backup_count: int = 3


class AgentConfig(BaseModel):
    """Root configuration model."""

    agent: AgentSection = AgentSection()
    http: HttpConfig = HttpConfig(enabled=False)
    mqtt: MqttConfig = MqttConfig()
    helper: HelperConfig = HelperConfig()
    collectors: CollectorsConfig = CollectorsConfig()
    logging: LoggingConfig = LoggingConfig()
    provisioning: ProvisioningConfig = ProvisioningConfig()


def load_config(path: Path) -> AgentConfig:
    """Load and validate a TOML configuration file."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return AgentConfig.model_validate(raw)
