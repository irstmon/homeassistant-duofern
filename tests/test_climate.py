"""Tests for the DuoFern climate platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import HVACMode, ClimateEntityFeature
from homeassistant.core import HomeAssistant

from custom_components.duofern.climate import (
    DuoFernClimate,
    TEMP_MIN,
    TEMP_MAX_HSA,
    TEMP_MAX_THERMOSTAT,
    TEMP_STEP,
)
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE

# Raumthermostat 0x73
THERMOSTAT_HEX = "731234"
# Heizkörperantrieb 0xE1
HSA_HEX = "E15678"


def _make_climate(hex_code: str) -> tuple[DuoFernClimate, DuoFernDeviceState]:
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    # Explicitly set to None so properties fall through to restored fallback
    device_state.status.measured_temp = None
    device_state.status.desired_temp = None

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    coordinator.async_set_desired_temp = AsyncMock()

    climate = DuoFernClimate(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
    )
    return climate, device_state


# ---------------------------------------------------------------------------
# Temperature ranges
# ---------------------------------------------------------------------------


def test_thermostat_max_temp():
    """Raumthermostat (0x73) has 40°C max."""
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert climate._attr_max_temp == TEMP_MAX_THERMOSTAT


def test_hsa_max_temp():
    """Heizkörperantrieb (0xE1) has 28°C max."""
    climate, _ = _make_climate(HSA_HEX)
    assert climate._attr_max_temp == TEMP_MAX_HSA


def test_min_temp():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert climate._attr_min_temp == TEMP_MIN


def test_temp_step():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert climate._attr_target_temperature_step == TEMP_STEP


# ---------------------------------------------------------------------------
# HVAC modes
# ---------------------------------------------------------------------------


def test_hvac_modes_heat_and_off():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert HVACMode.HEAT in climate._attr_hvac_modes
    assert HVACMode.OFF in climate._attr_hvac_modes


# ---------------------------------------------------------------------------
# Unique ID
# ---------------------------------------------------------------------------


def test_climate_unique_id():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert climate._attr_unique_id == f"duofern_{THERMOSTAT_HEX}"


# ---------------------------------------------------------------------------
# current_temperature / target_temperature
# Use status.measured_temp / status.desired_temp (not readings dict)
# ---------------------------------------------------------------------------


def test_current_temperature_from_status():
    """current_temperature reads from state.status.measured_temp."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.measured_temp = 21.5
    assert climate.current_temperature == 21.5


def test_current_temperature_none_when_not_set():
    """None when measured_temp is None and no restored value."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.measured_temp = None
    climate._restored_measured_temp = None
    assert climate.current_temperature is None


def test_current_temperature_restored_fallback():
    """Falls back to _restored_measured_temp when no live data."""
    climate, device_state = _make_climate(HSA_HEX)
    device_state.status.measured_temp = None
    climate._restored_measured_temp = 19.0
    assert climate.current_temperature == 19.0


def test_target_temperature_from_status():
    """target_temperature reads from state.status.desired_temp."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = 22.0
    assert climate.target_temperature == 22.0


def test_target_temperature_restored_fallback():
    climate, device_state = _make_climate(HSA_HEX)
    device_state.status.desired_temp = None
    climate._restored_desired_temp = 20.5
    assert climate.target_temperature == 20.5


def test_target_temperature_none_when_no_data():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = None
    climate._restored_desired_temp = None
    assert climate.target_temperature is None


# ---------------------------------------------------------------------------
# hvac_mode
# ---------------------------------------------------------------------------


def test_hvac_mode_heat_when_desired_temp_none():
    """Default HVAC mode is HEAT when desired_temp is None."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = None
    assert climate.hvac_mode == HVACMode.HEAT


def test_hvac_mode_off_when_desired_temp_at_min():
    """HVACMode.OFF when desired_temp <= TEMP_MIN."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = TEMP_MIN
    assert climate.hvac_mode == HVACMode.OFF


def test_hvac_mode_heat_when_temp_above_min():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = 20.0
    assert climate.hvac_mode == HVACMode.HEAT


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_climate_available():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.available = True
    assert climate.available is True


def test_climate_unavailable_when_device_offline():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.available = False
    assert climate.available is False


def test_climate_unavailable_when_not_in_data():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    climate.coordinator.data = None
    assert climate.available is False


# ---------------------------------------------------------------------------
# set_temperature — calls coordinator.async_set_desired_temp(device_code, temp)
# ---------------------------------------------------------------------------


async def test_set_temperature_calls_coordinator():
    """async_set_temperature calls coordinator.async_set_desired_temp(device_code, temp)."""
    climate, _ = _make_climate(THERMOSTAT_HEX)
    device_id = DuoFernId.from_hex(THERMOSTAT_HEX)
    await climate.async_set_temperature(temperature=21.0)
    climate.coordinator.async_set_desired_temp.assert_called_once_with(
        device_id, 21.0
    )


async def test_set_temperature_clamps_to_min():
    """Temperatures below TEMP_MIN are clamped to TEMP_MIN."""
    climate, _ = _make_climate(THERMOSTAT_HEX)
    device_id = DuoFernId.from_hex(THERMOSTAT_HEX)
    await climate.async_set_temperature(temperature=1.0)
    climate.coordinator.async_set_desired_temp.assert_called_once_with(
        device_id, TEMP_MIN
    )


# ---------------------------------------------------------------------------
# supported_features
# ---------------------------------------------------------------------------


def test_climate_supports_target_temperature():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert ClimateEntityFeature.TARGET_TEMPERATURE in climate._attr_supported_features


def test_climate_supports_turn_on_off():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    assert ClimateEntityFeature.TURN_ON in climate._attr_supported_features
    assert ClimateEntityFeature.TURN_OFF in climate._attr_supported_features


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


def test_extra_state_attributes_empty_when_no_data():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    climate.coordinator.data = None
    assert climate.extra_state_attributes == {}


def test_extra_state_attributes_includes_readings():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.readings = {"manualMode": "on", "desired-temp": 21.0}
    attrs = climate.extra_state_attributes
    assert "manualMode" in attrs
    # desired-temp is in _SKIP_AS_ATTRIBUTE → excluded
    assert "desired-temp" not in attrs


def test_extra_state_attributes_includes_firmware_version():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.readings = {}
    device_state.status.version = "2.5"
    attrs = climate.extra_state_attributes
    assert attrs.get("firmware_version") == "2.5"


def test_extra_state_attributes_includes_battery():
    climate, device_state = _make_climate(HSA_HEX)
    device_state.status.readings = {}
    device_state.status.version = None
    device_state.battery_state = "low"
    device_state.battery_percent = 15
    attrs = climate.extra_state_attributes
    assert attrs.get("battery_state") == "low"
    assert attrs.get("battery_level") == 15


def test_extra_state_attributes_no_battery_when_none():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.readings = {}
    device_state.status.version = None
    device_state.battery_state = None
    device_state.battery_percent = None
    attrs = climate.extra_state_attributes
    assert "battery_state" not in attrs
    assert "battery_level" not in attrs


# ---------------------------------------------------------------------------
# async_set_hvac_mode
# ---------------------------------------------------------------------------


async def test_set_hvac_mode_off_sets_temp_to_min():
    """HVACMode.OFF sends desired-temp = TEMP_MIN."""
    from custom_components.duofern.climate import TEMP_MIN

    climate, _ = _make_climate(THERMOSTAT_HEX)
    device_id = DuoFernId.from_hex(THERMOSTAT_HEX)
    await climate.async_set_hvac_mode(HVACMode.OFF)
    climate.coordinator.async_set_desired_temp.assert_called_once_with(
        device_id, TEMP_MIN
    )


async def test_set_hvac_mode_heat_when_currently_off_sends_20():
    """HVACMode.HEAT when desired_temp <= TEMP_MIN → sends 20.0°C."""
    from custom_components.duofern.climate import TEMP_MIN

    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = TEMP_MIN  # currently at minimum = OFF
    device_id = DuoFernId.from_hex(THERMOSTAT_HEX)
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    climate.coordinator.async_set_desired_temp.assert_called_once_with(
        device_id, 20.0
    )


async def test_set_hvac_mode_heat_when_already_heating_does_nothing():
    """HVACMode.HEAT when desired_temp > TEMP_MIN → no command sent."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = 21.0  # already heating
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    climate.coordinator.async_set_desired_temp.assert_not_called()


async def test_set_hvac_mode_heat_when_desired_temp_none_does_nothing():
    """HVACMode.HEAT when desired_temp is None → sends 20°C (current <= TEMP_MIN path)."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.desired_temp = None  # no live data
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    # current=None → None <= TEMP_MIN is False in Python → no command sent
    climate.coordinator.async_set_desired_temp.assert_not_called()


# ---------------------------------------------------------------------------
# set_temperature — edge cases
# ---------------------------------------------------------------------------


async def test_set_temperature_no_op_when_temp_kwarg_missing():
    """async_set_temperature does nothing when 'temperature' kwarg absent."""
    climate, _ = _make_climate(THERMOSTAT_HEX)
    await climate.async_set_temperature()
    climate.coordinator.async_set_desired_temp.assert_not_called()


async def test_set_temperature_clamps_to_max():
    """Temperatures above max are clamped to max."""
    from custom_components.duofern.climate import TEMP_MAX_THERMOSTAT

    climate, _ = _make_climate(THERMOSTAT_HEX)
    device_id = DuoFernId.from_hex(THERMOSTAT_HEX)
    await climate.async_set_temperature(temperature=100.0)
    climate.coordinator.async_set_desired_temp.assert_called_once_with(
        device_id, TEMP_MAX_THERMOSTAT
    )


# ---------------------------------------------------------------------------
# device_info
# ---------------------------------------------------------------------------


def test_device_info_contains_domain():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.version = None
    info = climate.device_info
    assert info is not None
    assert (DOMAIN, THERMOSTAT_HEX) in info["identifiers"]


def test_device_info_sw_version_from_state():
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    device_state.status.version = "1.2"
    info = climate.device_info
    assert info.get("sw_version") == "1.2"


def test_device_info_sw_version_none_when_no_data():
    climate, _ = _make_climate(THERMOSTAT_HEX)
    climate.coordinator.data = None
    info = climate.device_info
    assert info.get("sw_version") is None


# ---------------------------------------------------------------------------
# async_added_to_hass — state restoration
# ---------------------------------------------------------------------------


async def test_climate_added_to_hass_restores_desired_temp():
    """Restores desired temperature from last state attributes."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    climate, _ = _make_climate(HSA_HEX)
    mock_state = MagicMock()
    mock_state.attributes = {"temperature": "21.5", "current_temperature": None}
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        climate.async_get_last_state = AsyncMock(return_value=mock_state)
        await climate.async_added_to_hass()
    assert climate._restored_desired_temp == 21.5


async def test_climate_added_to_hass_restores_measured_temp():
    """Restores measured temperature from last state attributes."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    climate, _ = _make_climate(HSA_HEX)
    mock_state = MagicMock()
    mock_state.attributes = {"temperature": None, "current_temperature": "19.0"}
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        climate.async_get_last_state = AsyncMock(return_value=mock_state)
        await climate.async_added_to_hass()
    assert climate._restored_measured_temp == 19.0


async def test_climate_added_to_hass_no_restore_when_last_state_none():
    """last_state is None → restored values stay None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    climate, _ = _make_climate(HSA_HEX)
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        climate.async_get_last_state = AsyncMock(return_value=None)
        await climate.async_added_to_hass()
    assert climate._restored_desired_temp is None
    assert climate._restored_measured_temp is None


async def test_climate_added_to_hass_ignores_invalid_temperature():
    """Non-float temperature attribute → ValueError swallowed, restored stays None."""
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    climate, _ = _make_climate(HSA_HEX)
    mock_state = MagicMock()
    mock_state.attributes = {"temperature": "not-a-float", "current_temperature": "also-bad"}
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        climate.async_get_last_state = AsyncMock(return_value=mock_state)
        await climate.async_added_to_hass()
    assert climate._restored_desired_temp is None
    assert climate._restored_measured_temp is None


# ---------------------------------------------------------------------------
# _handle_coordinator_update — firmware version update
# ---------------------------------------------------------------------------


def test_climate_handle_coordinator_update_updates_firmware():
    """_handle_coordinator_update updates device registry when fw version changes."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    climate.async_write_ha_state = MagicMock()
    device_state.status.version = "2.0"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-climate"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device
    climate.hass = MagicMock()

    with patch(
        "custom_components.duofern.climate.dr.async_get",
        return_value=mock_registry,
    ):
        climate._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-climate", sw_version="2.0"
    )
    climate.async_write_ha_state.assert_called_once()


def test_climate_handle_coordinator_update_skips_when_version_unchanged():
    """_handle_coordinator_update skips registry update when version already matches."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    climate.async_write_ha_state = MagicMock()
    device_state.status.version = "2.0"

    mock_device = MagicMock()
    mock_device.sw_version = "2.0"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device
    climate.hass = MagicMock()

    with patch(
        "custom_components.duofern.climate.dr.async_get",
        return_value=mock_registry,
    ):
        climate._handle_coordinator_update()

    mock_registry.async_update_device.assert_not_called()
    climate.async_write_ha_state.assert_called_once()


def test_climate_handle_coordinator_update_skips_when_no_version():
    """_handle_coordinator_update skips registry when state.status.version is None."""
    climate, device_state = _make_climate(THERMOSTAT_HEX)
    climate.async_write_ha_state = MagicMock()
    device_state.status.version = None
    climate.hass = MagicMock()

    mock_registry = MagicMock()
    with patch(
        "custom_components.duofern.climate.dr.async_get",
        return_value=mock_registry,
    ):
        climate._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    climate.async_write_ha_state.assert_called_once()
