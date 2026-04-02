"""Tests for the DuoFern select platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.duofern.select import (
    DuoFernSelect,
    SELECT_DESCRIPTIONS,
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


def _make_select(hex_code: str, desc_key: str) -> DuoFernSelect:
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state

    desc = next(d for d in SELECT_DESCRIPTIONS if d.key == desc_key)
    setattr(coordinator, desc.coordinator_method, AsyncMock())

    return DuoFernSelect(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
        description=desc,
    )


# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------


def test_select_descriptions_not_empty():
    assert len(SELECT_DESCRIPTIONS) > 0


def test_select_descriptions_have_options():
    for desc in SELECT_DESCRIPTIONS:
        assert desc.options, f"{desc.key} has no options"


def test_motor_dead_time_description_exists():
    keys = [d.key for d in SELECT_DESCRIPTIONS]
    assert "motorDeadTime" in keys


# ---------------------------------------------------------------------------
# DuoFernSelect
# ---------------------------------------------------------------------------


def test_select_unique_id():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    assert COVER_HEX in sel._attr_unique_id
    assert desc_key in sel._attr_unique_id


def test_select_entity_category_config():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    assert sel.entity_category == EntityCategory.CONFIG


def test_select_current_option_from_reading():
    desc = SELECT_DESCRIPTIONS[0]
    valid_option = desc.options[0]

    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {desc.reading_key: valid_option}

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_HEX] = device_state
    setattr(coordinator, desc.coordinator_method, AsyncMock())

    sel = DuoFernSelect(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=COVER_HEX,
        description=desc,
    )
    assert sel.current_option == valid_option


def test_select_current_option_none_when_missing():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    assert sel.current_option is None


async def test_select_option_calls_coordinator():
    desc = SELECT_DESCRIPTIONS[0]  # motorDeadTime → async_set_motor_dead_time
    sel = _make_select(COVER_HEX, desc.key)
    option = desc.options[0]
    device_id = DuoFernId.from_hex(COVER_HEX)
    await sel.async_select_option(option)
    coordinator_method = getattr(sel.coordinator, desc.coordinator_method)
    coordinator_method.assert_called_once_with(device_id, option)


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_select_available_when_device_available():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.last_update_success = True
    sel.coordinator.data.devices[COVER_HEX].available = True
    assert sel.available is True


def test_select_unavailable_when_last_update_failed():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.last_update_success = False
    assert sel.available is False


def test_select_unavailable_when_device_unavailable():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.last_update_success = True
    sel.coordinator.data.devices[COVER_HEX].available = False
    assert sel.available is False


def test_select_unavailable_when_coordinator_data_none():
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.data = None
    assert sel.available is False


# ---------------------------------------------------------------------------
# current_option — restored fallback
# ---------------------------------------------------------------------------


def test_select_current_option_restored_fallback():
    """Returns _restored_option when reading is None."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.data.devices[COVER_HEX].status.readings = {}
    sel._restored_option = "off"
    assert sel.current_option == "off"


def test_select_current_option_live_updates_restored():
    """Live reading keeps _restored_option in sync."""
    desc = SELECT_DESCRIPTIONS[0]
    device_id = DuoFernId.from_hex(COVER_HEX)
    device_state = _make_select(COVER_HEX, desc.key).coordinator.data.devices[COVER_HEX]
    device_state.status.readings = {desc.reading_key: "short"}

    sel = _make_select(COVER_HEX, desc.key)
    sel.coordinator.data.devices[COVER_HEX].status.readings = {desc.reading_key: "short"}
    sel._restored_option = None
    val = sel.current_option
    assert val == "short"
    assert sel._restored_option == "short"


# ---------------------------------------------------------------------------
# Descriptions — all keys present
# ---------------------------------------------------------------------------


def test_wind_direction_description_exists():
    keys = [d.key for d in SELECT_DESCRIPTIONS]
    assert "windDirection" in keys


def test_rain_direction_description_exists():
    keys = [d.key for d in SELECT_DESCRIPTIONS]
    assert "rainDirection" in keys


def test_automatic_closing_description_exists():
    keys = [d.key for d in SELECT_DESCRIPTIONS]
    assert "automaticClosing" in keys


def test_open_speed_description_exists():
    keys = [d.key for d in SELECT_DESCRIPTIONS]
    assert "openSpeed" in keys


def test_interval_description_exists():
    keys = [d.key for d in SELECT_DESCRIPTIONS]
    assert "interval" in keys


# ---------------------------------------------------------------------------
# current_option — coordinator.data is None
# ---------------------------------------------------------------------------


def test_select_current_option_none_when_coordinator_data_none():
    """current_option returns _restored_option (None) when coordinator.data is None."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.data = None
    sel._restored_option = None
    assert sel.current_option is None


def test_select_current_option_restored_when_coordinator_data_none():
    """current_option returns _restored_option when coordinator.data is None."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.coordinator.data = None
    sel._restored_option = "short"
    assert sel.current_option == "short"


# ---------------------------------------------------------------------------
# async_added_to_hass
# ---------------------------------------------------------------------------


async def test_select_added_to_hass_last_state_none():
    """When async_get_last_state returns None, _restored_option stays None."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sel.async_get_last_state = AsyncMock(return_value=None)
        await sel.async_added_to_hass()
    assert sel._restored_option is None


async def test_select_added_to_hass_restores_valid_state():
    """When last_state has a valid option state, _restored_option is set."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    mock_state = MagicMock()
    mock_state.state = "short"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sel.async_get_last_state = AsyncMock(return_value=mock_state)
        await sel.async_added_to_hass()
    assert sel._restored_option == "short"


async def test_select_added_to_hass_ignores_unknown_state():
    """When last_state.state == 'unknown', _restored_option stays None."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sel.async_get_last_state = AsyncMock(return_value=mock_state)
        await sel.async_added_to_hass()
    assert sel._restored_option is None


async def test_select_added_to_hass_ignores_unavailable_state():
    """When last_state.state == 'unavailable', _restored_option stays None."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sel.async_get_last_state = AsyncMock(return_value=mock_state)
        await sel.async_added_to_hass()
    assert sel._restored_option is None


# ---------------------------------------------------------------------------
# _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_select_handle_coordinator_update():
    """_handle_coordinator_update calls async_write_ha_state."""
    desc_key = SELECT_DESCRIPTIONS[0].key
    sel = _make_select(COVER_HEX, desc_key)
    sel.async_write_ha_state = MagicMock()
    sel._handle_coordinator_update()
    sel.async_write_ha_state.assert_called_once()
