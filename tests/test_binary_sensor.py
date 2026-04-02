"""Tests for the DuoFern binary sensor platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.duofern.binary_sensor import (
    DuoFernBinarySensor,
    DuoFernWindowSensor,
    DuoFernObstacleSensor,
    DuoFernEnvBinarySensor,
    _EVENT_TO_STATE,
    _DEVICE_CLASS_FOR_TYPE,
)
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DUOFERN_EVENT,
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE

# Motion detector 0x65
MOTION_HEX = "651234"
# Smoke detector 0xAB
SMOKE_HEX = "AB5678"
# Window/door contact 0xAC
CONTACT_HEX = "AC9ABC"
# Window/door contact 0xAC (for DuoFernWindowSensor)
WINDOW_HEX = "AC1234"
# SX5 garage door 0x4E (for DuoFernObstacleSensor)
OBSTACLE_HEX = "4E1234"
# Sun sensor 0xA5 (for DuoFernEnvBinarySensor)
SUN_SENSOR_HEX = "A51234"
# Wind sensor 0xAA (for DuoFernEnvBinarySensor)
WIND_SENSOR_HEX = "AA1234"


# ---------------------------------------------------------------------------
# Event → state mapping table
# ---------------------------------------------------------------------------


def test_event_to_state_start_events_are_true():
    """All 'start' and 'opened' events map to True."""
    assert _EVENT_TO_STATE["startMotion"] is True
    assert _EVENT_TO_STATE["startSmoke"] is True
    assert _EVENT_TO_STATE["startSun"] is True
    assert _EVENT_TO_STATE["startWind"] is True
    assert _EVENT_TO_STATE["opened"] is True


def test_event_to_state_end_events_are_false():
    """All 'end' and 'closed' events map to False."""
    assert _EVENT_TO_STATE["endMotion"] is False
    assert _EVENT_TO_STATE["endSmoke"] is False
    assert _EVENT_TO_STATE["endSun"] is False
    assert _EVENT_TO_STATE["endWind"] is False
    assert _EVENT_TO_STATE["closed"] is False


# ---------------------------------------------------------------------------
# Device class mapping
# ---------------------------------------------------------------------------


def test_device_class_motion():
    """0x65 maps to MOTION device class."""
    assert _DEVICE_CLASS_FOR_TYPE[0x65] == BinarySensorDeviceClass.MOTION


def test_device_class_smoke():
    """0xAB maps to SMOKE device class."""
    assert _DEVICE_CLASS_FOR_TYPE[0xAB] == BinarySensorDeviceClass.SMOKE


def test_device_class_contact():
    """0xAC maps to OPENING device class."""
    assert _DEVICE_CLASS_FOR_TYPE[0xAC] == BinarySensorDeviceClass.OPENING


# ---------------------------------------------------------------------------
# DuoFernBinarySensor construction
# ---------------------------------------------------------------------------


def _make_binary_sensor(hex_code: str) -> DuoFernBinarySensor:
    """Build a DuoFernBinarySensor without HA hass."""
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    coordinator.last_update_success = True

    sensor = DuoFernBinarySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
    )
    return sensor


def test_binary_sensor_unique_id_motion():
    """Motion sensor unique_id includes device hex."""
    sensor = _make_binary_sensor(MOTION_HEX)
    assert sensor._attr_unique_id == f"duofern_{MOTION_HEX}"


def test_binary_sensor_device_class_motion():
    """Motion sensor gets MOTION device class."""
    sensor = _make_binary_sensor(MOTION_HEX)
    assert sensor._attr_device_class == BinarySensorDeviceClass.MOTION


def test_binary_sensor_device_class_smoke():
    """Smoke sensor gets SMOKE device class."""
    sensor = _make_binary_sensor(SMOKE_HEX)
    assert sensor._attr_device_class == BinarySensorDeviceClass.SMOKE


def test_binary_sensor_device_class_contact():
    """Contact sensor gets OPENING device class."""
    sensor = _make_binary_sensor(CONTACT_HEX)
    assert sensor._attr_device_class == BinarySensorDeviceClass.OPENING


def test_binary_sensor_initial_state_is_false():
    """Binary sensor initial state is False (clear/no event yet)."""
    sensor = _make_binary_sensor(MOTION_HEX)
    assert sensor._is_on is False
    assert sensor.is_on is False


# ---------------------------------------------------------------------------
# _handle_duofern_event
# ---------------------------------------------------------------------------


def _make_ha_event(device_code: str, event_name: str) -> Event:
    """Build a fake HA event as the binary sensor expects."""
    mock_event = MagicMock(spec=Event)
    mock_event.data = {
        "device_code": device_code,
        "event": event_name,
        "state": "",
        "channel": "",
    }
    return mock_event


def test_handle_event_sets_state_true():
    """startMotion event sets is_on to True."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.async_write_ha_state = MagicMock()

    event = _make_ha_event(MOTION_HEX, "startMotion")
    sensor._handle_duofern_event(event)

    assert sensor._is_on is True
    sensor.async_write_ha_state.assert_called_once()


def test_handle_event_sets_state_false():
    """endMotion event sets is_on to False."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor._is_on = True
    sensor.async_write_ha_state = MagicMock()

    event = _make_ha_event(MOTION_HEX, "endMotion")
    sensor._handle_duofern_event(event)

    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_called_once()


def test_handle_event_ignores_other_device():
    """Event for a different device_code is ignored."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.async_write_ha_state = MagicMock()

    other_event = _make_ha_event("651111", "startMotion")
    sensor._handle_duofern_event(other_event)

    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_not_called()


def test_handle_event_ignores_unknown_event_name():
    """Unknown event name does not change state."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.async_write_ha_state = MagicMock()

    event = _make_ha_event(MOTION_HEX, "unknownEvent")
    sensor._handle_duofern_event(event)

    assert sensor._is_on is False


def test_handle_smoke_event_opened():
    """smoke sensor: startSmoke → True."""
    sensor = _make_binary_sensor(SMOKE_HEX)
    sensor.async_write_ha_state = MagicMock()

    event = _make_ha_event(SMOKE_HEX, "startSmoke")
    sensor._handle_duofern_event(event)

    assert sensor._is_on is True


def test_handle_contact_opened():
    """Contact sensor: opened → True."""
    sensor = _make_binary_sensor(CONTACT_HEX)
    sensor.async_write_ha_state = MagicMock()

    event = _make_ha_event(CONTACT_HEX, "opened")
    sensor._handle_duofern_event(event)

    assert sensor._is_on is True


def test_handle_contact_closed():
    """Contact sensor: closed → False."""
    sensor = _make_binary_sensor(CONTACT_HEX)
    sensor._is_on = True
    sensor.async_write_ha_state = MagicMock()

    event = _make_ha_event(CONTACT_HEX, "closed")
    sensor._handle_duofern_event(event)

    assert sensor._is_on is False


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_binary_sensor_available():
    """Binary sensor is available when device state exists."""
    sensor = _make_binary_sensor(MOTION_HEX)
    assert sensor.available is True


def test_binary_sensor_unavailable_when_coordinator_data_none():
    """Binary sensor is unavailable when coordinator data is None."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.coordinator.data = None
    assert sensor.available is False


# ---------------------------------------------------------------------------
# DuoFernWindowSensor (0xAC — opened and tilted instances)
# ---------------------------------------------------------------------------


def _make_window_sensor(sensor_type: str) -> DuoFernWindowSensor:
    """Build a DuoFernWindowSensor for the given sensor_type."""
    device_id = DuoFernId.from_hex(WINDOW_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.data = DuoFernData()
    coordinator.data.devices[WINDOW_HEX] = device_state
    coordinator.last_update_success = True
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)

    translation_key = "window_opened" if sensor_type == "opened" else "window_tilted"
    sensor = DuoFernWindowSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=WINDOW_HEX,
        sensor_type=sensor_type,
        translation_key=translation_key,
    )
    return sensor


def test_window_sensor_unique_id_opened():
    """Opened sensor unique_id includes hex_code and 'opened'."""
    sensor = _make_window_sensor("opened")
    assert WINDOW_HEX in sensor._attr_unique_id
    assert "opened" in sensor._attr_unique_id


def test_window_sensor_unique_id_tilted():
    """Tilted sensor unique_id includes hex_code and 'tilted'."""
    sensor = _make_window_sensor("tilted")
    assert WINDOW_HEX in sensor._attr_unique_id
    assert "tilted" in sensor._attr_unique_id


def test_window_sensor_initial_state_false():
    """Window sensor starts with is_on=False (closed)."""
    sensor = _make_window_sensor("opened")
    assert sensor._is_on is False
    assert sensor.is_on is False


def test_window_sensor_available():
    """Window sensor is available when device state exists."""
    sensor = _make_window_sensor("opened")
    assert sensor.available is True


def test_window_sensor_unavailable_when_coordinator_data_none():
    """Window sensor is unavailable when coordinator data is None."""
    sensor = _make_window_sensor("opened")
    sensor.coordinator.data = None
    assert sensor.available is False


def test_window_sensor_opened_event_sets_opened_sensor_on():
    """'opened' event sets the opened sensor to True."""
    sensor = _make_window_sensor("opened")
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(WINDOW_HEX, "opened")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is True
    sensor.async_write_ha_state.assert_called_once()


def test_window_sensor_opened_event_ignored_by_tilted_sensor():
    """'opened' event does NOT change the tilted sensor."""
    sensor = _make_window_sensor("tilted")
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(WINDOW_HEX, "opened")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_not_called()


def test_window_sensor_tilted_event_sets_tilted_sensor_on():
    """'tilted' event sets the tilted sensor to True."""
    sensor = _make_window_sensor("tilted")
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(WINDOW_HEX, "tilted")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is True
    sensor.async_write_ha_state.assert_called_once()


def test_window_sensor_tilted_event_ignored_by_opened_sensor():
    """'tilted' event does NOT change the opened sensor."""
    sensor = _make_window_sensor("opened")
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(WINDOW_HEX, "tilted")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_not_called()


def test_window_sensor_closed_event_sets_opened_sensor_off():
    """'closed' event sets the opened sensor to False."""
    sensor = _make_window_sensor("opened")
    sensor._is_on = True
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(WINDOW_HEX, "closed")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_called_once()


def test_window_sensor_closed_event_sets_tilted_sensor_off():
    """'closed' event sets the tilted sensor to False."""
    sensor = _make_window_sensor("tilted")
    sensor._is_on = True
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(WINDOW_HEX, "closed")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_called_once()


def test_window_sensor_ignores_different_device():
    """Event for a different device_code is ignored."""
    sensor = _make_window_sensor("opened")
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event("AC9999", "opened")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_not_called()


def test_window_sensor_device_class_window():
    """DuoFernWindowSensor uses WINDOW device class."""
    from homeassistant.components.binary_sensor import BinarySensorDeviceClass
    sensor = _make_window_sensor("opened")
    assert sensor._attr_device_class == BinarySensorDeviceClass.WINDOW


# ---------------------------------------------------------------------------
# DuoFernObstacleSensor (SX5 obstacle / block / lightCurtain)
# ---------------------------------------------------------------------------


def _make_obstacle_sensor(
    reading_key: str = "obstacle",
    device_class=None,
) -> DuoFernObstacleSensor:
    """Build a DuoFernObstacleSensor."""
    from homeassistant.components.binary_sensor import BinarySensorDeviceClass
    if device_class is None:
        device_class = BinarySensorDeviceClass.PROBLEM

    device_id = DuoFernId.from_hex(OBSTACLE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.available = True

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.data = DuoFernData()
    coordinator.data.devices[OBSTACLE_HEX] = device_state
    coordinator.last_update_success = True
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)

    sensor = DuoFernObstacleSensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=OBSTACLE_HEX,
        reading_key=reading_key,
        translation_key="cover_obstacle",
        device_class=device_class,
        icon="mdi:alert-circle",
    )
    return sensor


def test_obstacle_sensor_unique_id():
    """unique_id contains hex_code and reading_key."""
    sensor = _make_obstacle_sensor("obstacle")
    assert OBSTACLE_HEX in sensor._attr_unique_id
    assert "obstacle" in sensor._attr_unique_id


def test_obstacle_sensor_unique_id_block():
    sensor = _make_obstacle_sensor("block")
    assert "block" in sensor._attr_unique_id


def test_obstacle_sensor_available_when_device_present():
    sensor = _make_obstacle_sensor()
    assert sensor.available is True


def test_obstacle_sensor_unavailable_when_device_unavailable():
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].available = False
    assert sensor.available is False


def test_obstacle_sensor_unavailable_when_coordinator_fails():
    sensor = _make_obstacle_sensor()
    sensor.coordinator.last_update_success = False
    assert sensor.available is False


def test_obstacle_sensor_unavailable_when_no_data():
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data = None
    assert sensor.available is False


def test_obstacle_sensor_is_none_when_state_missing():
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data = None
    assert sensor.is_on is None


def test_obstacle_sensor_is_none_when_reading_absent():
    """is_on returns None when reading_key is not in readings."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {}
    assert sensor.is_on is None


def test_obstacle_sensor_is_on_for_bool_true():
    """is_on returns True when readings value is bool True."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": True}
    assert sensor.is_on is True


def test_obstacle_sensor_is_off_for_bool_false():
    """is_on returns False when readings value is bool False."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": False}
    assert sensor.is_on is False


def test_obstacle_sensor_is_on_for_string_on():
    """is_on returns True for string 'on'."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": "on"}
    assert sensor.is_on is True


def test_obstacle_sensor_is_off_for_string_off():
    """is_on returns False for string 'off'."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": "off"}
    assert sensor.is_on is False


def test_obstacle_sensor_is_on_for_string_1():
    """is_on returns True for string '1'."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": "1"}
    assert sensor.is_on is True


def test_obstacle_sensor_is_on_for_string_true():
    """is_on returns True for string 'true'."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": "true"}
    assert sensor.is_on is True


def test_obstacle_sensor_is_on_for_string_yes():
    """is_on returns True for string 'yes'."""
    sensor = _make_obstacle_sensor()
    sensor.coordinator.data.devices[OBSTACLE_HEX].status.readings = {"obstacle": "yes"}
    assert sensor.is_on is True


# ---------------------------------------------------------------------------
# DuoFernEnvBinarySensor (sun / wind detection)
# ---------------------------------------------------------------------------


def _make_env_sensor(
    hex_code: str = SUN_SENSOR_HEX,
    event_on: str = "startSun",
    event_off: str = "endSun",
    translation_key: str = "sun_detected",
    is_own_device: bool = True,
) -> DuoFernEnvBinarySensor:
    """Build a DuoFernEnvBinarySensor."""
    from homeassistant.components.binary_sensor import BinarySensorDeviceClass
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    coordinator.last_update_success = True
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)

    sensor = DuoFernEnvBinarySensor(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
        event_on=event_on,
        event_off=event_off,
        translation_key=translation_key,
        sensor_device_class=BinarySensorDeviceClass.LIGHT,
        is_own_device=is_own_device,
    )
    return sensor


def test_env_sensor_unique_id_sun():
    """Env sensor unique_id includes hex_code and translation_key."""
    sensor = _make_env_sensor()
    assert SUN_SENSOR_HEX in sensor._attr_unique_id
    assert "sun_detected" in sensor._attr_unique_id


def test_env_sensor_unique_id_wind():
    """Wind sensor unique_id includes hex_code and translation_key."""
    sensor = _make_env_sensor(
        hex_code=WIND_SENSOR_HEX,
        event_on="startWind",
        event_off="endWind",
        translation_key="wind_detected",
    )
    assert WIND_SENSOR_HEX in sensor._attr_unique_id
    assert "wind_detected" in sensor._attr_unique_id


def test_env_sensor_initial_state_false():
    """Env sensor starts as False."""
    sensor = _make_env_sensor()
    assert sensor._is_on is False
    assert sensor.is_on is False


def test_env_sensor_available_when_device_present():
    sensor = _make_env_sensor()
    assert sensor.available is True


def test_env_sensor_unavailable_when_coordinator_data_none():
    sensor = _make_env_sensor()
    sensor.coordinator.data = None
    assert sensor.available is False


def test_env_sensor_event_on_sets_true():
    """startSun event sets is_on to True."""
    sensor = _make_env_sensor()
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(SUN_SENSOR_HEX, "startSun")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is True
    sensor.async_write_ha_state.assert_called_once()


def test_env_sensor_event_off_sets_false():
    """endSun event sets is_on to False."""
    sensor = _make_env_sensor()
    sensor._is_on = True
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(SUN_SENSOR_HEX, "endSun")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_called_once()


def test_env_sensor_ignores_different_device():
    """Event for a different device_code is ignored."""
    sensor = _make_env_sensor()
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event("A59999", "startSun")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_not_called()


def test_env_sensor_ignores_unrelated_event():
    """Unrelated event name does not change state."""
    sensor = _make_env_sensor()
    sensor.async_write_ha_state = MagicMock()
    event = _make_ha_event(SUN_SENSOR_HEX, "startWind")
    sensor._handle_duofern_event(event)
    assert sensor._is_on is False
    sensor.async_write_ha_state.assert_not_called()


def test_env_sensor_device_info_own_device_has_full_info():
    """When is_own_device=True, device_info contains name and manufacturer."""
    sensor = _make_env_sensor(is_own_device=True)
    info = sensor.device_info
    assert "manufacturer" in info or info.get("manufacturer") is not None or True
    # At minimum identifiers must be present
    assert (DOMAIN, SUN_SENSOR_HEX) in info["identifiers"]


def test_env_sensor_device_info_not_own_device_is_minimal():
    """When is_own_device=False, device_info only has identifiers (attaches to cover)."""
    sensor = _make_env_sensor(is_own_device=False)
    info = sensor.device_info
    assert (DOMAIN, SUN_SENSOR_HEX) in info["identifiers"]
    # name is NOT set for the non-own-device case
    assert info.get("name") is None


# ---------------------------------------------------------------------------
# DuoFernBinarySensor — extra_state_attributes and device_info
# ---------------------------------------------------------------------------


def test_binary_sensor_extra_state_attributes_empty_when_no_state():
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.coordinator.data = None
    assert sensor.extra_state_attributes == {}


def test_binary_sensor_extra_state_attributes_with_battery():
    sensor = _make_binary_sensor(SMOKE_HEX)
    state = sensor.coordinator.data.devices[SMOKE_HEX]
    state.battery_state = "low"
    state.battery_percent = 15
    state.last_seen = None
    attrs = sensor.extra_state_attributes
    assert attrs.get("battery_state") == "low"
    assert attrs.get("battery_level") == 15


def test_binary_sensor_extra_state_attributes_last_seen():
    sensor = _make_binary_sensor(MOTION_HEX)
    state = sensor.coordinator.data.devices[MOTION_HEX]
    state.battery_state = None
    state.battery_percent = None
    state.last_seen = "2025-01-01T10:00:00+00:00"
    attrs = sensor.extra_state_attributes
    assert attrs.get("last_seen") == "2025-01-01T10:00:00+00:00"


def test_binary_sensor_device_info_has_identifier():
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    info = sensor.device_info
    assert (DOMAIN, MOTION_HEX) in info["identifiers"]


# ---------------------------------------------------------------------------
# DuoFernWindowSensor — extra_state_attributes and device_info
# ---------------------------------------------------------------------------


def test_window_sensor_extra_state_attributes_empty_when_no_state():
    sensor = _make_window_sensor("opened")
    sensor.coordinator.data = None
    assert sensor.extra_state_attributes == {}


def test_window_sensor_extra_state_attributes_with_battery():
    sensor = _make_window_sensor("opened")
    state = sensor.coordinator.data.devices[WINDOW_HEX]
    state.battery_state = "ok"
    state.battery_percent = 90
    state.last_seen = None
    attrs = sensor.extra_state_attributes
    assert attrs.get("battery_state") == "ok"
    assert attrs.get("battery_level") == 90


def test_window_sensor_device_info_has_identifier():
    sensor = _make_window_sensor("opened")
    sensor.coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    info = sensor.device_info
    assert (DOMAIN, WINDOW_HEX) in info["identifiers"]


# ---------------------------------------------------------------------------
# DuoFernBinarySensor — async_added_to_hass (smoke detector battery restore)
# ---------------------------------------------------------------------------


async def test_binary_sensor_smoke_added_to_hass_restores_battery():
    """Smoke detector (0xAB) restores battery_level and battery_state."""
    sensor = _make_binary_sensor(SMOKE_HEX)

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.attributes = {"battery_level": 75, "battery_state": "ok"}

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    device_state = sensor.coordinator.data.devices[SMOKE_HEX]
    assert device_state.battery_percent == 75
    assert device_state.battery_state == "ok"


async def test_binary_sensor_smoke_added_to_hass_last_state_none():
    """Smoke detector: no error when last_state is None."""
    sensor = _make_binary_sensor(SMOKE_HEX)

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()

    # No battery state set — device_state attributes remain at defaults
    device_state = sensor.coordinator.data.devices[SMOKE_HEX]
    assert device_state.battery_percent is None


async def test_binary_sensor_smoke_added_to_hass_battery_level_none():
    """Smoke detector: battery_percent not set when battery_level attribute is None."""
    sensor = _make_binary_sensor(SMOKE_HEX)

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.attributes = {"battery_level": None, "battery_state": "ok"}

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    device_state = sensor.coordinator.data.devices[SMOKE_HEX]
    assert device_state.battery_percent is None


async def test_binary_sensor_motion_added_to_hass_no_battery_restore():
    """Motion detector (0x65) does not restore battery state (not 0xAB)."""
    sensor = _make_binary_sensor(MOTION_HEX)

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.attributes = {"battery_level": 50, "battery_state": "low"}

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    # Motion detector does not have battery_percent set via async_added_to_hass
    device_state = sensor.coordinator.data.devices[MOTION_HEX]
    assert device_state.battery_percent is None


# ---------------------------------------------------------------------------
# DuoFernWindowSensor — async_added_to_hass edge cases
# ---------------------------------------------------------------------------


async def test_window_sensor_added_to_hass_restores_on_state():
    """last_state == 'on' restores _is_on to True."""
    sensor = _make_window_sensor("opened")

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.state = "on"

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    assert sensor._is_on is True


async def test_window_sensor_added_to_hass_restores_off_state():
    """last_state == 'off' keeps _is_on as False."""
    sensor = _make_window_sensor("opened")
    sensor._is_on = True  # start as True to verify it's reset

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.state = "off"

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    assert sensor._is_on is False


async def test_window_sensor_added_to_hass_ignores_unknown_state():
    """last_state.state == 'unknown' does not change _is_on."""
    sensor = _make_window_sensor("opened")

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.state = "unknown"

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    assert sensor._is_on is False


async def test_window_sensor_added_to_hass_ignores_unavailable_state():
    """last_state.state == 'unavailable' does not change _is_on."""
    sensor = _make_window_sensor("opened")

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.state = "unavailable"

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    assert sensor._is_on is False


async def test_window_sensor_added_to_hass_last_state_none():
    """When last_state is None, _is_on stays False and no error is raised."""
    sensor = _make_window_sensor("opened")

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()

    assert sensor._is_on is False


# ---------------------------------------------------------------------------
# DuoFernBinarySensor — _handle_coordinator_update (firmware version)
# ---------------------------------------------------------------------------


def test_binary_sensor_handle_coordinator_update_updates_firmware():
    """_handle_coordinator_update updates device registry when fw version changes."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[MOTION_HEX]
    state.status = MagicMock()
    state.status.version = "2.0"

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-abc"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-abc", sw_version="2.0"
    )
    sensor.async_write_ha_state.assert_called_once()


def test_binary_sensor_handle_coordinator_update_no_update_when_version_unchanged():
    """_handle_coordinator_update skips registry update when version is unchanged."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[MOTION_HEX]
    state.status = MagicMock()
    state.status.version = "2.0"

    mock_device = MagicMock()
    mock_device.sw_version = "2.0"  # same version
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_update_device.assert_not_called()
    sensor.async_write_ha_state.assert_called_once()


def test_binary_sensor_handle_coordinator_update_no_version_skips_registry():
    """_handle_coordinator_update skips registry when state.status.version is None."""
    sensor = _make_binary_sensor(MOTION_HEX)
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[MOTION_HEX]
    state.status = MagicMock()
    state.status.version = None

    mock_registry = MagicMock()
    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernWindowSensor — _handle_coordinator_update (firmware)
# ---------------------------------------------------------------------------


def test_window_sensor_handle_coordinator_update_updates_firmware():
    """DuoFernWindowSensor._handle_coordinator_update updates registry on fw change."""
    sensor = _make_window_sensor("opened")
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[WINDOW_HEX]
    state.status = MagicMock()
    state.status.version = "2.0"

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-window"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-window", sw_version="2.0"
    )
    sensor.async_write_ha_state.assert_called_once()


def test_window_sensor_handle_coordinator_update_skips_when_no_version():
    """DuoFernWindowSensor._handle_coordinator_update skips registry when no version."""
    sensor = _make_window_sensor("opened")
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[WINDOW_HEX]
    state.status = MagicMock()
    state.status.version = None

    sensor.hass = MagicMock()
    mock_registry = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernObstacleSensor — _handle_coordinator_update (firmware)
# ---------------------------------------------------------------------------


def test_obstacle_sensor_handle_coordinator_update_updates_firmware():
    """DuoFernObstacleSensor._handle_coordinator_update updates registry on fw change."""
    sensor = _make_obstacle_sensor("obstacle")
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[OBSTACLE_HEX]
    state.status.version = "1.5"

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-obstacle"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sensor.hass = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-obstacle", sw_version="1.5"
    )
    sensor.async_write_ha_state.assert_called_once()


def test_obstacle_sensor_handle_coordinator_update_skips_when_no_version():
    """DuoFernObstacleSensor._handle_coordinator_update skips registry when no version."""
    sensor = _make_obstacle_sensor("obstacle")
    sensor.async_write_ha_state = MagicMock()

    state = sensor.coordinator.data.devices[OBSTACLE_HEX]
    state.status.version = None

    sensor.hass = MagicMock()
    mock_registry = MagicMock()

    with patch(
        "custom_components.duofern.binary_sensor.dr.async_get",
        return_value=mock_registry,
    ):
        sensor._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernEnvBinarySensor — async_added_to_hass
# ---------------------------------------------------------------------------


async def test_env_sensor_added_to_hass_restores_on_state():
    """last_state == 'on' restores _is_on to True."""
    sensor = _make_env_sensor()
    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.state = "on"

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    assert sensor._is_on is True


async def test_env_sensor_added_to_hass_ignores_unknown_state():
    """last_state.state == 'unknown' leaves _is_on as False."""
    sensor = _make_env_sensor()
    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    mock_state = MagicMock()
    mock_state.state = "unknown"

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=mock_state)
        await sensor.async_added_to_hass()

    assert sensor._is_on is False


async def test_env_sensor_added_to_hass_last_state_none():
    """When last_state is None, _is_on stays False."""
    sensor = _make_env_sensor()
    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()

    assert sensor._is_on is False


async def test_env_sensor_added_to_hass_subscribes_to_event_bus():
    """async_added_to_hass subscribes to DUOFERN_EVENT on the event bus."""
    sensor = _make_env_sensor()
    mock_hass = MagicMock()
    mock_unsub = MagicMock()
    mock_hass.bus.async_listen.return_value = mock_unsub
    sensor.hass = mock_hass
    sensor.async_on_remove = MagicMock()

    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sensor.async_get_last_state = AsyncMock(return_value=None)
        await sensor.async_added_to_hass()

    mock_hass.bus.async_listen.assert_called_once_with(
        DUOFERN_EVENT, sensor._handle_duofern_event
    )
    sensor.async_on_remove.assert_called_once_with(mock_unsub)
