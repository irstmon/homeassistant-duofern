"""Tests for the DuoFern number platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.number import NumberMode
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.duofern.number import (
    DuoFernNumber,
    NUMBER_DESCRIPTIONS,
)
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE

COVER_HEX = "406B2D"


def _make_number(hex_code: str, desc_key: str) -> DuoFernNumber:
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state

    desc = next(d for d in NUMBER_DESCRIPTIONS if d.key == desc_key)
    setattr(coordinator, desc.coordinator_method, AsyncMock())

    return DuoFernNumber(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
        description=desc,
    )


# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------


def test_number_descriptions_not_empty():
    assert len(NUMBER_DESCRIPTIONS) > 0


def test_number_descriptions_have_reading_key():
    for desc in NUMBER_DESCRIPTIONS:
        assert hasattr(desc, "reading_key") and desc.reading_key, \
            f"{desc.key} missing reading_key"


def test_sun_position_description_exists():
    keys = [d.key for d in NUMBER_DESCRIPTIONS]
    assert "sunPosition" in keys


def test_ventilating_position_description_exists():
    keys = [d.key for d in NUMBER_DESCRIPTIONS]
    assert "ventilatingPosition" in keys


# ---------------------------------------------------------------------------
# DuoFernNumber unit tests
# ---------------------------------------------------------------------------


def test_number_unique_id():
    num = _make_number(COVER_HEX, "sunPosition")
    assert COVER_HEX in num._attr_unique_id
    assert "sunPosition" in num._attr_unique_id


def test_number_entity_category_config():
    num = _make_number(COVER_HEX, "sunPosition")
    assert num.entity_category == EntityCategory.CONFIG


def test_number_native_value_from_reading():
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {"sunPosition": 30}

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state
    coordinator.async_set_sun_position = AsyncMock()

    desc = next(d for d in NUMBER_DESCRIPTIONS if d.key == "sunPosition")
    num = DuoFernNumber(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
        description=desc,
    )
    assert num.native_value == 30


def test_number_native_value_none_when_missing():
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].status.readings = {}
    assert num.native_value is None


async def test_number_set_value_calls_coordinator():
    num = _make_number(COVER_HEX, "sunPosition")
    device_id = DuoFernId.from_hex(COVER_HEX)
    await num.async_set_native_value(45.0)
    num.coordinator.async_set_sun_position.assert_called_once_with(device_id, 45.0)


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_number_available_when_device_available():
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].available = True
    assert num.available is True


def test_number_unavailable_when_device_unavailable():
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].available = False
    assert num.available is False


def test_number_unavailable_when_coordinator_data_none():
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data = None
    assert num.available is False


# ---------------------------------------------------------------------------
# native_value — restored fallback
# ---------------------------------------------------------------------------


def test_number_native_value_restored_fallback():
    """When reading is None but _restored_value is set, return restored."""
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].status.readings = {}
    num._restored_value = 42.0
    assert num.native_value == 42.0


def test_number_native_value_none_when_no_reading_and_no_restored():
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].status.readings = {}
    num._restored_value = None
    assert num.native_value is None


def test_number_native_value_live_updates_restored():
    """Live reading keeps _restored_value in sync."""
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].status.readings = {"sunPosition": 55}
    num._restored_value = None
    val = num.native_value
    assert val == 55.0
    assert num._restored_value == 55.0


def test_number_native_value_when_coordinator_data_none():
    """When coordinator.data is None, return _restored_value."""
    num = _make_number(COVER_HEX, "sunPosition")
    num._restored_value = 30.0
    num.coordinator.data = None
    assert num.native_value == 30.0


# ---------------------------------------------------------------------------
# Descriptions — comprehensive check
# ---------------------------------------------------------------------------


def test_stairwell_time_description_exists():
    keys = [d.key for d in NUMBER_DESCRIPTIONS]
    assert "stairwellTime" in keys


def test_intermediate_value_description_exists():
    keys = [d.key for d in NUMBER_DESCRIPTIONS]
    assert "intermediateValue" in keys


def test_sending_interval_description_exists():
    keys = [d.key for d in NUMBER_DESCRIPTIONS]
    assert "sendingInterval" in keys


def test_boost_duration_description_exists():
    keys = [d.key for d in NUMBER_DESCRIPTIONS]
    assert "boostDuration" in keys


def test_number_mode_is_slider():
    num = _make_number(COVER_HEX, "sunPosition")
    assert num._attr_mode == NumberMode.SLIDER


# ---------------------------------------------------------------------------
# native_value — float conversion error branch
# ---------------------------------------------------------------------------


def test_number_native_value_falls_back_when_float_conversion_fails():
    """When readings has a value but float() raises ValueError, return _restored_value."""
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].status.readings = {"sunPosition": "not_a_float"}
    num._restored_value = 25.0
    assert num.native_value == 25.0


def test_number_native_value_none_when_float_fails_and_no_restored():
    """When float() raises and no restored value, return None."""
    num = _make_number(COVER_HEX, "sunPosition")
    num.coordinator.data.devices[COVER_HEX].status.readings = {"sunPosition": "bad"}
    num._restored_value = None
    assert num.native_value is None


# ---------------------------------------------------------------------------
# async_added_to_hass
# ---------------------------------------------------------------------------


async def test_number_added_to_hass_last_state_none():
    """When async_get_last_state returns None, _restored_value stays None."""
    num = _make_number(COVER_HEX, "sunPosition")
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        num.async_get_last_state = AsyncMock(return_value=None)
        await num.async_added_to_hass()
    assert num._restored_value is None


async def test_number_added_to_hass_restores_valid_state():
    """When last_state has a valid float state, _restored_value is set."""
    num = _make_number(COVER_HEX, "sunPosition")
    mock_state = MagicMock()
    mock_state.state = "45.5"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        num.async_get_last_state = AsyncMock(return_value=mock_state)
        await num.async_added_to_hass()
    assert num._restored_value == 45.5


async def test_number_added_to_hass_ignores_unknown_state():
    """When last_state.state == 'unknown', _restored_value stays None."""
    num = _make_number(COVER_HEX, "sunPosition")
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        num.async_get_last_state = AsyncMock(return_value=mock_state)
        await num.async_added_to_hass()
    assert num._restored_value is None


async def test_number_added_to_hass_ignores_unavailable_state():
    """When last_state.state == 'unavailable', _restored_value stays None."""
    num = _make_number(COVER_HEX, "sunPosition")
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        num.async_get_last_state = AsyncMock(return_value=mock_state)
        await num.async_added_to_hass()
    assert num._restored_value is None


async def test_number_added_to_hass_ignores_non_float_state():
    """When last_state.state cannot be converted to float, _restored_value stays None."""
    num = _make_number(COVER_HEX, "sunPosition")
    mock_state = MagicMock()
    mock_state.state = "not_a_number"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        num.async_get_last_state = AsyncMock(return_value=mock_state)
        await num.async_added_to_hass()
    assert num._restored_value is None


# ---------------------------------------------------------------------------
# _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_number_handle_coordinator_update():
    """_handle_coordinator_update calls async_write_ha_state."""
    num = _make_number(COVER_HEX, "sunPosition")
    num.async_write_ha_state = MagicMock()
    num._handle_coordinator_update()
    num.async_write_ha_state.assert_called_once()
