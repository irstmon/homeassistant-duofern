"""Tests for the DuoFern sensor platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId
from custom_components.duofern.sensor import (
    SENSOR_DESCRIPTIONS,
    DuoFernSensorDescription,
    DuoFernSensor,
    DuoFernBatterySensor,
    DuoFernLastSeenSensor,
    DuoFernValveSensor,
    DuoFernBoostStartSensor,
)
from custom_components.duofern.const import DOMAIN

from .conftest import MOCK_SYSTEM_CODE

WEATHER_HEX = "691234"
COVER_HEX = "406B2D"
HSA_HEX = "E11234"  # Heizkörperantrieb 0xE1 → valve + boost sensors


# ---------------------------------------------------------------------------
# Sensor descriptions
# ---------------------------------------------------------------------------


def test_sensor_descriptions_not_empty():
    assert len(SENSOR_DESCRIPTIONS) > 0


def test_sensor_descriptions_have_reading_key():
    for desc in SENSOR_DESCRIPTIONS:
        assert desc.reading_key, f"{desc.key} missing reading_key"


def test_brightness_description():
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    assert desc.device_class == SensorDeviceClass.ILLUMINANCE
    assert desc.state_class == SensorStateClass.MEASUREMENT
    assert desc.native_unit_of_measurement == "lx"


def test_temperature_description():
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "temperature")
    assert desc.device_class == SensorDeviceClass.TEMPERATURE


def test_wind_description():
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "wind")
    assert desc.device_class == SensorDeviceClass.WIND_SPEED


# ---------------------------------------------------------------------------
# DuoFernSensor
# ---------------------------------------------------------------------------


def _make_sensor_coordinator(hex_code=WEATHER_HEX):
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    return coordinator, device_state


def test_sensor_unique_id():
    coordinator, device_state = _make_sensor_coordinator()
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WEATHER_HEX,
        description=desc,
    )
    assert WEATHER_HEX in sensor._attr_unique_id
    assert "brightness" in sensor._attr_unique_id


def test_sensor_native_value_none_when_no_reading():
    coordinator, device_state = _make_sensor_coordinator()
    device_state.status.readings = {}
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WEATHER_HEX,
        description=desc,
    )
    assert sensor.native_value is None


def test_sensor_native_value_from_readings():
    coordinator, device_state = _make_sensor_coordinator()
    device_state.status.readings = {"brightness": 12345}
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WEATHER_HEX,
        description=desc,
    )
    assert sensor.native_value == 12345


def test_sensor_available_when_reading_present():
    """DuoFernSensor.available requires the reading_key to be in readings."""
    coordinator, device_state = _make_sensor_coordinator()
    device_state.status.readings = {"brightness": 5000}
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WEATHER_HEX,
        description=desc,
    )
    assert sensor.available is True


def test_sensor_unavailable_when_reading_missing():
    """available is False when reading_key not yet in readings."""
    coordinator, device_state = _make_sensor_coordinator()
    device_state.status.readings = {}
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WEATHER_HEX,
        description=desc,
    )
    assert sensor.available is False


def test_sensor_unavailable_when_coordinator_data_none():
    coordinator, device_state = _make_sensor_coordinator()
    coordinator.data = None
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "brightness")
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WEATHER_HEX,
        description=desc,
    )
    assert sensor.available is False


# ---------------------------------------------------------------------------
# DuoFernBatterySensor
# ---------------------------------------------------------------------------


def test_battery_sensor_unique_id():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernBatterySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert COVER_HEX in sensor._attr_unique_id
    assert "battery" in sensor._attr_unique_id


def test_battery_sensor_entity_category_diagnostic():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernBatterySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_battery_sensor_native_value_from_state():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.battery_percent = 75
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernBatterySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert sensor.native_value == 75


def test_battery_sensor_native_value_none_when_not_set():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.battery_percent = None
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernBatterySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    # No battery_percent, no readings["batteryPercent"], no restored value
    assert sensor.native_value is None


def test_battery_sensor_available_when_device_present():
    """DuoFernBatterySensor.available = _device_state is not None."""
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernBatterySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert sensor.available is True


# ---------------------------------------------------------------------------
# DuoFernLastSeenSensor
# ---------------------------------------------------------------------------


def test_last_seen_sensor_unique_id():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernLastSeenSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert COVER_HEX in sensor._attr_unique_id
    assert "last_seen" in sensor._attr_unique_id


def test_last_seen_sensor_device_class_timestamp():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernLastSeenSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert sensor._attr_device_class == SensorDeviceClass.TIMESTAMP


def test_last_seen_sensor_returns_none_when_not_seen():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.last_seen = None
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state

    sensor = DuoFernLastSeenSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
    )
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# DuoFernValveSensor
# ---------------------------------------------------------------------------


def _make_hsa_coordinator(hex_code=HSA_HEX):
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.available = True

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    return coordinator, device_state


def test_valve_sensor_unique_id():
    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert HSA_HEX in sensor._attr_unique_id
    assert "valve_position" in sensor._attr_unique_id


def test_valve_sensor_available_when_device_present():
    coordinator, device_state = _make_hsa_coordinator()
    device_state.available = True
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.available is True


def test_valve_sensor_unavailable_when_device_unavailable():
    coordinator, device_state = _make_hsa_coordinator()
    device_state.available = False
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.available is False


def test_valve_sensor_native_value_from_reading():
    coordinator, device_state = _make_hsa_coordinator()
    device_state.status.readings = {"valvePosition": 42}
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.native_value == 42.0


def test_valve_sensor_native_value_none_when_no_reading():
    """Returns None (restored_value=None) when valvePosition not in readings."""
    coordinator, device_state = _make_hsa_coordinator()
    device_state.status.readings = {}
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# DuoFernBoostStartSensor
# ---------------------------------------------------------------------------


def test_boost_start_sensor_unique_id():
    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert HSA_HEX in sensor._attr_unique_id
    assert "boost_started" in sensor._attr_unique_id


def test_boost_start_sensor_device_class_timestamp():
    from homeassistant.components.sensor import SensorDeviceClass

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor._attr_device_class == SensorDeviceClass.TIMESTAMP


def test_boost_start_sensor_entity_category_diagnostic():
    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_boost_start_sensor_available_when_device_present():
    coordinator, device_state = _make_hsa_coordinator()
    device_state.available = True
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.available is True


def test_boost_start_sensor_available_false_when_unavailable():
    coordinator, device_state = _make_hsa_coordinator()
    device_state.available = False
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.available is False


def test_boost_start_sensor_native_value_none_when_no_boost():
    """Returns None (restored_value=None) when boost_start is None."""
    coordinator, device_state = _make_hsa_coordinator()
    device_state.boost_start = None
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.native_value is None


def test_boost_start_sensor_native_value_from_state():
    """native_value returns state.boost_start when set."""
    from datetime import datetime, timezone

    coordinator, device_state = _make_hsa_coordinator()
    ts = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    device_state.boost_start = ts
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.native_value == ts


def test_boost_start_sensor_naive_ts_gets_timezone():
    """Timezone-naive boost_start is returned with DEFAULT_TIME_ZONE attached."""
    from datetime import datetime

    coordinator, device_state = _make_hsa_coordinator()
    naive_ts = datetime(2025, 1, 15, 10, 30, 0)  # no tzinfo
    device_state.boost_start = naive_ts
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    result = sensor.native_value
    assert result is not None
    assert result.tzinfo is not None


def test_boost_start_sensor_unavailable_when_data_none():
    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    coordinator.data = None
    assert sensor.available is False


# ---------------------------------------------------------------------------
# DuoFernValveSensor — additional coverage
# ---------------------------------------------------------------------------


def test_valve_sensor_native_value_syncs_restored():
    """Reading a live valve position keeps _restored_value in sync."""
    coordinator, device_state = _make_hsa_coordinator()
    device_state.status.readings = {"valvePosition": 55}
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    sensor._restored_value = None
    val = sensor.native_value
    assert val == 55.0
    assert sensor._restored_value == 55.0


def test_valve_sensor_unavailable_when_data_none():
    coordinator, device_state = _make_hsa_coordinator()
    coordinator.data = None
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    assert sensor.available is False


def test_valve_sensor_restored_fallback():
    """When valvePosition absent, return _restored_value."""
    coordinator, device_state = _make_hsa_coordinator()
    device_state.status.readings = {}
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    sensor._restored_value = 30.0
    assert sensor.native_value == 30.0


# ---------------------------------------------------------------------------
# DuoFernSensor — additional coverage
# ---------------------------------------------------------------------------


def _make_duofern_sensor(hex_code=WEATHER_HEX, key="brightness"):
    coordinator, device_state = _make_sensor_coordinator(hex_code)
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
    sensor = DuoFernSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
        description=desc,
    )
    return sensor, coordinator, device_state


def test_sensor_native_value_none_when_data_none():
    sensor, coordinator, _ = _make_duofern_sensor()
    coordinator.data = None
    assert sensor.native_value is None


def test_sensor_native_value_none_when_value_non_numeric():
    sensor, _, device_state = _make_duofern_sensor()
    device_state.status.readings = {"brightness": "not-a-number"}
    assert sensor.native_value is None


def test_sensor_unavailable_when_device_unavailable():
    sensor, _, device_state = _make_duofern_sensor()
    device_state.status.readings = {"brightness": 5000}
    device_state.available = False
    assert sensor.available is False


def test_sensor_unavailable_when_last_update_failed():
    sensor, coordinator, device_state = _make_duofern_sensor()
    device_state.status.readings = {"brightness": 5000}
    device_state.available = True
    coordinator.last_update_success = False
    assert sensor.available is False


def test_sensor_extra_state_attributes_empty_when_no_data():
    sensor, coordinator, _ = _make_duofern_sensor()
    coordinator.data = None
    assert sensor.extra_state_attributes == {}


def test_sensor_extra_state_attributes_is_raining():
    sensor, _, device_state = _make_duofern_sensor()
    device_state.status.readings = {"brightness": 5000, "isRaining": True}
    device_state.battery_state = None
    device_state.battery_percent = None
    device_state.last_seen = None
    attrs = sensor.extra_state_attributes
    assert attrs.get("is_raining") is True


def test_sensor_extra_state_attributes_battery():
    sensor, _, device_state = _make_duofern_sensor()
    device_state.status.readings = {}
    device_state.battery_state = "ok"
    device_state.battery_percent = 80
    device_state.last_seen = None
    attrs = sensor.extra_state_attributes
    assert attrs.get("battery_state") == "ok"
    assert attrs.get("battery_level") == 80


def test_sensor_device_info_has_identifier():
    sensor, _, device_state = _make_duofern_sensor()
    device_state.status.version = None
    info = sensor.device_info
    assert (DOMAIN, WEATHER_HEX) in info["identifiers"]


def test_sensor_device_info_sw_version():
    sensor, _, device_state = _make_duofern_sensor()
    device_state.status.version = "3.0"
    info = sensor.device_info
    assert info.get("sw_version") == "3.0"


# ---------------------------------------------------------------------------
# DuoFernBatterySensor — additional coverage
# ---------------------------------------------------------------------------


def _make_battery_sensor(hex_code=COVER_HEX):
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.status.version = None
    device_state.battery_percent = None
    device_state.battery_state = None

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state

    sensor = DuoFernBatterySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
    )
    return sensor, coordinator, device_state


def test_battery_sensor_native_value_from_readings():
    """Source 2: batteryPercent from status readings (e.g. 0xE1 format 29)."""
    sensor, _, device_state = _make_battery_sensor()
    device_state.battery_percent = None
    device_state.status.readings = {"batteryPercent": 60}
    assert sensor.native_value == 60


def test_battery_sensor_native_value_restored():
    """Source 3: fall back to _restored_value when no live data."""
    sensor, _, device_state = _make_battery_sensor()
    device_state.battery_percent = None
    device_state.status.readings = {}
    sensor._restored_value = 45
    assert sensor.native_value == 45


def test_battery_sensor_native_value_restored_when_data_none():
    sensor, coordinator, _ = _make_battery_sensor()
    coordinator.data = None
    sensor._restored_value = 30
    assert sensor.native_value == 30


def test_battery_sensor_available_false_when_data_none():
    sensor, coordinator, _ = _make_battery_sensor()
    coordinator.data = None
    assert sensor.available is False


def test_battery_sensor_extra_state_attributes_with_battery_state():
    sensor, _, device_state = _make_battery_sensor()
    device_state.battery_state = "low"
    assert sensor.extra_state_attributes == {"battery_state": "low"}


def test_battery_sensor_extra_state_attributes_empty_when_no_state():
    sensor, _, device_state = _make_battery_sensor()
    device_state.battery_state = None
    assert sensor.extra_state_attributes == {}


def test_battery_sensor_extra_state_attributes_empty_when_data_none():
    sensor, coordinator, _ = _make_battery_sensor()
    coordinator.data = None
    # _device_state returns None → state is None → return {}
    assert sensor.extra_state_attributes == {}


# ---------------------------------------------------------------------------
# DuoFernLastSeenSensor — native_value with actual timestamps
# ---------------------------------------------------------------------------


def _make_last_seen_sensor(hex_code=COVER_HEX):
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.last_seen = None

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state

    sensor = DuoFernLastSeenSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
    )
    return sensor, coordinator, device_state


def test_last_seen_sensor_native_value_with_valid_iso_string():
    """last_seen stored as ISO 8601 string → returns datetime."""
    from datetime import datetime, timezone

    sensor, _, device_state = _make_last_seen_sensor()
    device_state.last_seen = "2025-03-15T12:00:00+00:00"
    result = sensor.native_value
    assert result is not None
    assert result.tzinfo is not None


def test_last_seen_sensor_native_value_naive_iso_gets_timezone():
    """ISO string without timezone → returns datetime with DEFAULT_TIME_ZONE."""
    sensor, _, device_state = _make_last_seen_sensor()
    device_state.last_seen = "2025-03-15T12:00:00"  # no tzinfo
    result = sensor.native_value
    assert result is not None
    assert result.tzinfo is not None


def test_last_seen_sensor_native_value_invalid_returns_restored():
    """Invalid ISO string → falls back to _restored_value."""
    from datetime import datetime, timezone

    sensor, _, device_state = _make_last_seen_sensor()
    device_state.last_seen = "not-a-date"
    sensor._restored_value = None
    assert sensor.native_value is None


def test_last_seen_sensor_available_false_when_data_none():
    sensor, coordinator, _ = _make_last_seen_sensor()
    coordinator.data = None
    assert sensor.available is False


def test_last_seen_sensor_device_info_has_identifier():
    sensor, _, _ = _make_last_seen_sensor()
    info = sensor.device_info
    assert (DOMAIN, COVER_HEX) in info["identifiers"]


# ---------------------------------------------------------------------------
# DuoFernSensor — _handle_coordinator_update (firmware version)
# ---------------------------------------------------------------------------


def test_sensor_handle_coordinator_update_updates_firmware():
    """_handle_coordinator_update updates device registry when fw version changes."""
    sensor, _, device_state = _make_duofern_sensor()
    sensor.async_write_ha_state = MagicMock()

    device_state.status.version = "3.0"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "2.0"
    mock_device.id = "device-id-sensor"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-sensor", sw_version="3.0"
    )
    sensor.async_write_ha_state.assert_called_once()


def test_sensor_handle_coordinator_update_skips_when_no_version():
    """_handle_coordinator_update skips registry when state.status.version is None."""
    sensor, _, device_state = _make_duofern_sensor()
    sensor.async_write_ha_state = MagicMock()

    device_state.status.version = None
    device_state.available = True
    sensor.hass = MagicMock()

    mock_registry = MagicMock()
    with patch(
        "custom_components.duofern.sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    sensor.async_write_ha_state.assert_called_once()


def test_sensor_handle_coordinator_update_no_update_when_version_unchanged():
    """_handle_coordinator_update skips registry update when version already matches."""
    sensor, _, device_state = _make_duofern_sensor()
    sensor.async_write_ha_state = MagicMock()

    device_state.status.version = "3.0"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "3.0"  # same version
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_update_device.assert_not_called()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernBatterySensor — _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_battery_sensor_handle_coordinator_update_clears_restored_on_live_data():
    """When live battery_percent arrives, _restored_value is cleared."""
    sensor, _, device_state = _make_battery_sensor()
    sensor.async_write_ha_state = MagicMock()
    sensor._restored_value = 50  # previously restored

    device_state.battery_percent = 75  # live data now available
    sensor._handle_coordinator_update()

    assert sensor._restored_value is None
    sensor.async_write_ha_state.assert_called_once()


def test_battery_sensor_handle_coordinator_update_clears_restored_on_reading():
    """When batteryPercent arrives in readings, _restored_value is cleared."""
    sensor, _, device_state = _make_battery_sensor()
    sensor.async_write_ha_state = MagicMock()
    sensor._restored_value = 50

    device_state.battery_percent = None
    device_state.status.readings = {"batteryPercent": 80}
    sensor._handle_coordinator_update()

    assert sensor._restored_value is None
    sensor.async_write_ha_state.assert_called_once()


def test_battery_sensor_handle_coordinator_update_keeps_restored_when_no_live_data():
    """When no live battery data, _restored_value is NOT cleared."""
    sensor, _, device_state = _make_battery_sensor()
    sensor.async_write_ha_state = MagicMock()
    sensor._restored_value = 50

    device_state.battery_percent = None
    device_state.status.readings = {}
    sensor._handle_coordinator_update()

    assert sensor._restored_value == 50
    sensor.async_write_ha_state.assert_called_once()


def test_battery_sensor_handle_coordinator_update_when_data_none():
    """When coordinator.data is None, _restored_value is NOT cleared."""
    sensor, coordinator, _ = _make_battery_sensor()
    sensor.async_write_ha_state = MagicMock()
    sensor._restored_value = 50
    coordinator.data = None

    sensor._handle_coordinator_update()

    assert sensor._restored_value == 50
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernValveSensor — _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_valve_sensor_handle_coordinator_update():
    """DuoFernValveSensor._handle_coordinator_update calls async_write_ha_state."""
    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_coordinator_update()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernLastSeenSensor — _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_last_seen_sensor_handle_coordinator_update():
    """DuoFernLastSeenSensor._handle_coordinator_update calls async_write_ha_state."""
    sensor, _, _ = _make_last_seen_sensor()
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_coordinator_update()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernBoostStartSensor — _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_boost_start_sensor_handle_coordinator_update():
    """DuoFernBoostStartSensor._handle_coordinator_update calls async_write_ha_state."""
    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    sensor.async_write_ha_state = MagicMock()
    sensor._handle_coordinator_update()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernBatterySensor — async_added_to_hass
# ---------------------------------------------------------------------------


async def test_battery_sensor_added_to_hass_restores_valid_value():
    """Valid numeric state → _restored_value is set as int."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_battery_sensor()
    mock_state = MagicMock()
    mock_state.state = "75"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value == 75


async def test_battery_sensor_added_to_hass_no_restore_when_last_state_none():
    """last_state is None → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_battery_sensor()
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_battery_sensor_added_to_hass_ignores_unknown_state():
    """'unknown' state → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_battery_sensor()
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_battery_sensor_added_to_hass_ignores_non_numeric_state():
    """Non-numeric state string → ValueError swallowed, _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_battery_sensor()
    mock_state = MagicMock()
    mock_state.state = "not-a-number"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


def test_battery_sensor_native_value_bad_reading_falls_back_to_restored():
    """readings['batteryPercent'] not int-convertible → fall back to _restored_value."""
    sensor, _, device_state = _make_battery_sensor()
    device_state.battery_percent = None
    device_state.status.readings = {"batteryPercent": "bad"}
    sensor._restored_value = 42
    assert sensor.native_value == 42


# ---------------------------------------------------------------------------
# DuoFernValveSensor — async_added_to_hass
# ---------------------------------------------------------------------------


async def test_valve_sensor_added_to_hass_restores_valid_float():
    """Valid float state → _restored_value is set."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    mock_state = MagicMock()
    mock_state.state = "55.5"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value == 55.5


async def test_valve_sensor_added_to_hass_no_restore_when_last_state_none():
    """last_state is None → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_valve_sensor_added_to_hass_ignores_unknown():
    """'unknown' state → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_valve_sensor_added_to_hass_ignores_non_float():
    """Non-float state → ValueError swallowed, _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernValveSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    mock_state = MagicMock()
    mock_state.state = "notafloat"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


# ---------------------------------------------------------------------------
# DuoFernBoostStartSensor — async_added_to_hass
# ---------------------------------------------------------------------------


async def test_boost_start_sensor_added_to_hass_restores_valid_ts():
    """Valid ISO timestamp → _restored_value is a datetime."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    mock_state = MagicMock()
    mock_state.state = "2025-03-15T10:00:00+00:00"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is not None


async def test_boost_start_sensor_added_to_hass_no_restore_when_last_state_none():
    """last_state is None → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_boost_start_sensor_added_to_hass_ignores_unknown():
    """'unknown' state → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_boost_start_sensor_added_to_hass_invalid_ts_leaves_none():
    """Invalid timestamp → dt_util.parse_datetime returns None, _restored_value is None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    coordinator, device_state = _make_hsa_coordinator()
    sensor = DuoFernBoostStartSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
    )
    mock_state = MagicMock()
    mock_state.state = "not-a-datetime"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


# ---------------------------------------------------------------------------
# DuoFernLastSeenSensor — async_added_to_hass
# ---------------------------------------------------------------------------


async def test_last_seen_sensor_added_to_hass_restores_valid_ts():
    """Valid ISO timestamp → _restored_value is a datetime."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_last_seen_sensor()
    mock_state = MagicMock()
    mock_state.state = "2025-03-15T10:00:00+00:00"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is not None


async def test_last_seen_sensor_added_to_hass_no_restore_when_last_state_none():
    """last_state is None → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_last_seen_sensor()
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None


async def test_last_seen_sensor_added_to_hass_ignores_unknown():
    """'unknown' state → _restored_value stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    sensor, _, _ = _make_last_seen_sensor()
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()
    assert sensor._restored_value is None
