"""Tests for Dell Command | Monitor vendor collector."""

from __future__ import annotations

from unittest.mock import MagicMock

from desk2ha_agent.collector.vendor.dell_dcm import (
    DellDcmCollector,
    _normalize_sensor_name,
)


def test_dell_dcm_meta():
    assert DellDcmCollector.meta.name == "dell_dcm"
    assert DellDcmCollector.meta.tier == "vendor"
    assert "thermals" in DellDcmCollector.meta.capabilities
    assert "power" in DellDcmCollector.meta.capabilities
    assert DellDcmCollector.meta.requires_software == "Dell Command | Monitor"


def test_normalize_sensor_name():
    assert _normalize_sensor_name("CPU") == "cpu_package"
    assert _normalize_sensor_name("CPU Package") == "cpu_package"
    assert _normalize_sensor_name("CPU Core") == "cpu_core_max"
    assert _normalize_sensor_name("Ambient") == "ambient"
    assert _normalize_sensor_name("Memory") == "memory"
    assert _normalize_sensor_name("SSD") == "ssd"
    assert _normalize_sensor_name("GPU") == "gpu"
    assert _normalize_sensor_name("PCH") == "pch"
    assert _normalize_sensor_name("Battery") == "battery_temp"
    assert _normalize_sensor_name("Skin") == "skin"
    assert _normalize_sensor_name("Charger") == "charger"
    # Unknown sensor → slugified
    assert _normalize_sensor_name("Some New Sensor") == "some_new_sensor"


def test_collect_thermals():
    c = DellDcmCollector()
    mock_conn = MagicMock()

    sensor = MagicMock()
    sensor.ElementName = "Temperature Sensor:CPU"
    sensor.CurrentReading = 59
    sensor.UnitModifier = -1
    mock_conn.query.return_value = [sensor]

    metrics: dict = {}
    c._collect_thermals(mock_conn, metrics, 0.0)

    assert "cpu_package" in metrics
    assert metrics["cpu_package"]["value"] == 59.0
    assert metrics["cpu_package"]["unit"] == "Cel"


def test_collect_thermals_filters_outliers():
    c = DellDcmCollector()
    mock_conn = MagicMock()

    # Temperature too high (> 200)
    sensor = MagicMock()
    sensor.ElementName = "Temperature Sensor:CPU"
    sensor.CurrentReading = 999
    sensor.UnitModifier = -1
    mock_conn.query.return_value = [sensor]

    metrics: dict = {}
    c._collect_thermals(mock_conn, metrics, 0.0)
    assert len(metrics) == 0


def test_collect_fans():
    c = DellDcmCollector()
    mock_conn = MagicMock()

    cpu_fan = MagicMock()
    cpu_fan.ElementName = "Fan Speed Sensor:CPU Fan"
    cpu_fan.CurrentReading = 1788

    gpu_fan = MagicMock()
    gpu_fan.ElementName = "Fan Speed Sensor:Video Fan"
    gpu_fan.CurrentReading = 1785

    mock_conn.query.return_value = [cpu_fan, gpu_fan]

    metrics: dict = {}
    c._collect_fans(mock_conn, metrics, 0.0)

    assert metrics["fan.cpu"]["value"] == 1788.0
    assert metrics["fan.gpu"]["value"] == 1785.0


def test_collect_fans_processor_name():
    """Processor Fan (real DCM name) falls through to index-based key."""
    c = DellDcmCollector()
    mock_conn = MagicMock()

    fan = MagicMock()
    fan.ElementName = "Fan Speed Sensor:Processor Fan"
    fan.CurrentReading = 1788
    mock_conn.query.return_value = [fan]

    metrics: dict = {}
    c._collect_fans(mock_conn, metrics, 0.0)

    # "Processor" matches "processor" pattern → fan.cpu
    assert metrics["fan.cpu"]["value"] == 1788.0


def test_collect_power():
    c = DellDcmCollector()
    mock_conn = MagicMock()

    ps = MagicMock()
    ps.TotalOutputPower = 130

    src = MagicMock()
    src.PowerState = 2  # AC

    def side_effect(query):
        if "PowerSupply" in query:
            return [ps]
        if "PowerSource" in query:
            return [src]
        return []

    mock_conn.query.side_effect = side_effect

    metrics: dict = {}
    c._collect_power(mock_conn, metrics, 0.0)

    assert metrics["power.ac_adapter_watts"]["value"] == 130.0
    assert metrics["power.source"]["value"] == "ac"


def test_collect_power_battery_source():
    c = DellDcmCollector()
    mock_conn = MagicMock()

    src = MagicMock()
    src.PowerState = 1  # Battery

    def side_effect(query):
        if "PowerSupply" in query:
            return []
        if "PowerSource" in query:
            return [src]
        return []

    mock_conn.query.side_effect = side_effect

    metrics: dict = {}
    c._collect_power(mock_conn, metrics, 0.0)

    assert metrics["power.source"]["value"] == "battery"


# ---------- Dock telemetry (FK-16) ----------


def test_collect_dock():
    """Dock collection should emit dock.0.* metrics from WMI objects."""
    c = DellDcmCollector()
    mock_conn = MagicMock()

    dock = MagicMock()
    dock.Model = "WD22TB4"
    dock.FirmwareVersion = "1.0.15.1"
    dock.SerialNumber = "ABCD1234"
    dock.ConnectionType = "Thunderbolt"

    mock_conn.query.return_value = [dock]

    metrics: dict = {}
    c._collect_dock(mock_conn, metrics, 0.0)

    assert metrics["dock.0.model"]["value"] == "WD22TB4"
    assert metrics["dock.0.firmware"]["value"] == "1.0.15.1"
    assert metrics["dock.0.serial"]["value"] == "ABCD1234"
    assert metrics["dock.0.connection_type"]["value"] == "Thunderbolt"
    assert metrics["dock.0.connected"]["value"] is True


def test_collect_dock_no_docks():
    """Empty dock query should not crash."""
    c = DellDcmCollector()
    mock_conn = MagicMock()
    mock_conn.query.return_value = []

    metrics: dict = {}
    c._collect_dock(mock_conn, metrics, 0.0)

    assert not any(k.startswith("dock.") for k in metrics)


def test_collect_dock_wmi_exception():
    """WMI exception in dock query should not propagate."""
    c = DellDcmCollector()
    mock_conn = MagicMock()
    mock_conn.query.side_effect = Exception("WMI not available")

    metrics: dict = {}
    c._collect_dock(mock_conn, metrics, 0.0)
    assert not any(k.startswith("dock.") for k in metrics)


def test_collect_dock_partial_attributes():
    """Dock with missing attributes should still emit available ones."""
    c = DellDcmCollector()
    mock_conn = MagicMock()

    dock = MagicMock()
    dock.Model = "WD19TBS"
    dock.FirmwareVersion = None
    dock.SerialNumber = None
    dock.ConnectionType = None
    dock.ElementName = None

    mock_conn.query.return_value = [dock]

    metrics: dict = {}
    c._collect_dock(mock_conn, metrics, 0.0)

    assert metrics["dock.0.model"]["value"] == "WD19TBS"
    assert metrics["dock.0.connected"]["value"] is True
    assert "dock.0.firmware" not in metrics
