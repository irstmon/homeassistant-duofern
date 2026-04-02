"""Tests for the DuoFern button platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.duofern.button import (
    DuoFernPairButton,
    DuoFernUnpairButton,
    DuoFernStopPairUnpairButton,
    DuoFernStatusButton,
    DuoFernDuskButton,
    DuoFernDawnButton,
    DuoFernToggleButton,
    DuoFernResetSettingsButton,
    DuoFernResetFullButton,
    DuoFernRemotePairButton,
    DuoFernRemoteUnpairButton,
    DuoFernRemoteStopButton,
    DuoFernActTempLimitButton,
    DuoFernGetStatusButton,
    DuoFernGetWeatherButton,
    DuoFernGetTimeButton,
    DuoFernGetConfigButton,
    DuoFernSetTimeButton,
    DuoFernWriteConfigButton,
    DuoFernPairByCodeButton,
)
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE, MOCK_DEVICE_CODE_COVER

COVER_HEX = MOCK_DEVICE_CODE_COVER


def _make_coordinator(pairing=False, unpairing=False):
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    data = DuoFernData()
    data.pairing_active = pairing
    data.unpairing_active = unpairing
    coordinator.data = data
    coordinator.async_start_pairing = AsyncMock()
    coordinator.async_start_unpairing = AsyncMock()
    coordinator.async_stop_pairing = AsyncMock()
    coordinator.async_stop_unpairing = AsyncMock()
    coordinator.async_request_all_status = AsyncMock()
    coordinator.async_cover_dusk = AsyncMock()
    coordinator.async_cover_dawn = AsyncMock()
    coordinator.async_cover_toggle = AsyncMock()
    coordinator.async_reset = AsyncMock()
    coordinator.async_remote_pair = AsyncMock()
    coordinator.async_remote_unpair = AsyncMock()
    coordinator.async_remote_stop = AsyncMock()
    coordinator.async_set_act_temp_limit = AsyncMock()
    coordinator.async_get_status_device = AsyncMock()
    coordinator.async_get_weather = AsyncMock()
    coordinator.async_get_time = AsyncMock()
    coordinator.async_get_weather_config = AsyncMock()
    coordinator.async_set_time = AsyncMock()
    coordinator.async_write_weather_config = AsyncMock()
    coordinator.async_pair_device_by_code = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# DuoFernPairButton
# ---------------------------------------------------------------------------


def test_pair_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernPairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn._attr_unique_id == f"duofern_{MOCK_SYSTEM_CODE}_pair"


def test_pair_button_available_when_idle():
    coordinator = _make_coordinator(pairing=False, unpairing=False)
    btn = DuoFernPairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is True


def test_pair_button_unavailable_when_pairing():
    coordinator = _make_coordinator(pairing=True)
    btn = DuoFernPairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is False


def test_pair_button_unavailable_when_unpairing():
    coordinator = _make_coordinator(unpairing=True)
    btn = DuoFernPairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is False


async def test_pair_button_press_starts_pairing():
    coordinator = _make_coordinator()
    btn = DuoFernPairButton(coordinator, MOCK_SYSTEM_CODE)
    await btn.async_press()
    coordinator.async_start_pairing.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernUnpairButton
# ---------------------------------------------------------------------------


def test_unpair_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn._attr_unique_id == f"duofern_{MOCK_SYSTEM_CODE}_unpair"


def test_unpair_button_available_when_idle():
    coordinator = _make_coordinator()
    btn = DuoFernUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is True


def test_unpair_button_unavailable_when_active():
    coordinator = _make_coordinator(pairing=True)
    btn = DuoFernUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is False


async def test_unpair_button_press_starts_unpairing():
    coordinator = _make_coordinator()
    btn = DuoFernUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    await btn.async_press()
    coordinator.async_start_unpairing.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernStopPairUnpairButton
# ---------------------------------------------------------------------------


def test_stop_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernStopPairUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn._attr_unique_id == f"duofern_{MOCK_SYSTEM_CODE}_stop_pair_unpair"


def test_stop_button_unavailable_when_idle():
    coordinator = _make_coordinator(pairing=False, unpairing=False)
    btn = DuoFernStopPairUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is False


def test_stop_button_available_when_pairing():
    coordinator = _make_coordinator(pairing=True)
    btn = DuoFernStopPairUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is True


def test_stop_button_available_when_unpairing():
    coordinator = _make_coordinator(unpairing=True)
    btn = DuoFernStopPairUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is True


async def test_stop_button_press_stops_pairing():
    coordinator = _make_coordinator(pairing=True)
    btn = DuoFernStopPairUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    await btn.async_press()
    coordinator.async_stop_pairing.assert_called_once()


async def test_stop_button_press_stops_unpairing():
    coordinator = _make_coordinator(unpairing=True)
    btn = DuoFernStopPairUnpairButton(coordinator, MOCK_SYSTEM_CODE)
    await btn.async_press()
    coordinator.async_stop_unpairing.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernStatusButton
# ---------------------------------------------------------------------------


def test_status_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernStatusButton(coordinator, MOCK_SYSTEM_CODE)
    assert MOCK_SYSTEM_CODE in btn._attr_unique_id
    assert "status" in btn._attr_unique_id


async def test_status_button_press_broadcasts():
    coordinator = _make_coordinator()
    btn = DuoFernStatusButton(coordinator, MOCK_SYSTEM_CODE)
    await btn.async_press()
    coordinator.async_request_all_status.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernDuskButton / DuoFernDawnButton
# Buttons take DuoFernId as device_code and call coordinator.async_cover_dusk/dawn
# ---------------------------------------------------------------------------


def test_dusk_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernDuskButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "dusk" in btn._attr_unique_id


def test_dawn_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernDawnButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "dawn" in btn._attr_unique_id


async def test_dusk_button_press_calls_coordinator():
    """async_press calls coordinator.async_cover_dusk(device_code) with DuoFernId."""
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernDuskButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_cover_dusk.assert_called_once_with(device_code)


async def test_dawn_button_press_calls_coordinator():
    """async_press calls coordinator.async_cover_dawn(device_code) with DuoFernId."""
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernDawnButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_cover_dawn.assert_called_once_with(device_code)


# ---------------------------------------------------------------------------
# DuoFernToggleButton
# ---------------------------------------------------------------------------


def test_toggle_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernToggleButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "toggle" in btn._attr_unique_id


async def test_toggle_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernToggleButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_cover_toggle.assert_called_once_with(device_code)


# ---------------------------------------------------------------------------
# DuoFernResetSettingsButton / DuoFernResetFullButton
# ---------------------------------------------------------------------------


def test_reset_settings_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernResetSettingsButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "reset_settings" in btn._attr_unique_id


def test_reset_settings_button_entity_category_config():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernResetSettingsButton(coordinator, device_code)
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_reset_settings_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernResetSettingsButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_reset.assert_called_once_with(device_code, "settings")


def test_reset_full_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernResetFullButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "reset_full" in btn._attr_unique_id


def test_reset_full_button_entity_category_config():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernResetFullButton(coordinator, device_code)
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_reset_full_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernResetFullButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_reset.assert_called_once_with(device_code, "full")


# ---------------------------------------------------------------------------
# DuoFernRemotePairButton / DuoFernRemoteUnpairButton / DuoFernRemoteStopButton
# ---------------------------------------------------------------------------


def test_remote_pair_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemotePairButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "remote_pair" in btn._attr_unique_id


def test_remote_pair_button_entity_category_config():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemotePairButton(coordinator, device_code)
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_remote_pair_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemotePairButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_remote_pair.assert_called_once_with(device_code)


def test_remote_unpair_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemoteUnpairButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "remote_unpair" in btn._attr_unique_id


def test_remote_unpair_button_entity_category_config():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemoteUnpairButton(coordinator, device_code)
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_remote_unpair_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemoteUnpairButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_remote_unpair.assert_called_once_with(device_code)


def test_remote_stop_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemoteStopButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "remote_stop" in btn._attr_unique_id


def test_remote_stop_button_entity_category_config():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemoteStopButton(coordinator, device_code)
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_remote_stop_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernRemoteStopButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_remote_stop.assert_called_once_with(device_code)


# ---------------------------------------------------------------------------
# DuoFernActTempLimitButton (zones 1–4)
# ---------------------------------------------------------------------------

# 0x73 Raumthermostat
THERMOSTAT_HEX = "731234"


def test_act_temp_limit_button_unique_id_zone1():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(THERMOSTAT_HEX)
    btn = DuoFernActTempLimitButton(coordinator, device_code, zone=1)
    assert THERMOSTAT_HEX in btn._attr_unique_id
    assert "act_temp_limit_1" in btn._attr_unique_id


def test_act_temp_limit_button_unique_id_zone4():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(THERMOSTAT_HEX)
    btn = DuoFernActTempLimitButton(coordinator, device_code, zone=4)
    assert "act_temp_limit_4" in btn._attr_unique_id


def test_act_temp_limit_button_entity_category_config():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(THERMOSTAT_HEX)
    btn = DuoFernActTempLimitButton(coordinator, device_code, zone=1)
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_act_temp_limit_button_press_zone1():
    """Zone 1 press calls async_set_act_temp_limit(device_code, '1')."""
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(THERMOSTAT_HEX)
    btn = DuoFernActTempLimitButton(coordinator, device_code, zone=1)
    await btn.async_press()
    coordinator.async_set_act_temp_limit.assert_called_once_with(device_code, "1")


async def test_act_temp_limit_button_press_zone3():
    """Zone 3 press calls async_set_act_temp_limit(device_code, '3')."""
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(THERMOSTAT_HEX)
    btn = DuoFernActTempLimitButton(coordinator, device_code, zone=3)
    await btn.async_press()
    coordinator.async_set_act_temp_limit.assert_called_once_with(device_code, "3")


# ---------------------------------------------------------------------------
# DuoFernGetStatusButton
# ---------------------------------------------------------------------------


def test_get_status_button_unique_id():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernGetStatusButton(coordinator, device_code)
    assert COVER_HEX in btn._attr_unique_id
    assert "get_status" in btn._attr_unique_id


def test_get_status_button_entity_category_diagnostic():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernGetStatusButton(coordinator, device_code)
    assert btn._attr_entity_category == EntityCategory.DIAGNOSTIC


async def test_get_status_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    device_code = DuoFernId.from_hex(COVER_HEX)
    btn = DuoFernGetStatusButton(coordinator, device_code)
    await btn.async_press()
    coordinator.async_get_status_device.assert_called_once_with(device_code)


# ---------------------------------------------------------------------------
# DuoFernGetWeatherButton / DuoFernGetTimeButton / DuoFernGetConfigButton
# DuoFernSetTimeButton / DuoFernWriteConfigButton
# ---------------------------------------------------------------------------

# 0x69 Umweltsensor channel "00"
WEATHER_STATION_HEX = "691234"


def _weather_device_code() -> DuoFernId:
    return DuoFernId.from_hex(WEATHER_STATION_HEX)


def test_get_weather_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernGetWeatherButton(coordinator, _weather_device_code())
    assert WEATHER_STATION_HEX in btn._attr_unique_id
    assert "get_weather" in btn._attr_unique_id


def test_get_weather_button_entity_category_diagnostic():
    coordinator = _make_coordinator()
    btn = DuoFernGetWeatherButton(coordinator, _weather_device_code())
    assert btn._attr_entity_category == EntityCategory.DIAGNOSTIC


async def test_get_weather_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    dc = _weather_device_code()
    btn = DuoFernGetWeatherButton(coordinator, dc)
    await btn.async_press()
    coordinator.async_get_weather.assert_called_once_with(dc)


def test_get_time_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernGetTimeButton(coordinator, _weather_device_code())
    assert "get_time" in btn._attr_unique_id


def test_get_time_button_entity_category_diagnostic():
    coordinator = _make_coordinator()
    btn = DuoFernGetTimeButton(coordinator, _weather_device_code())
    assert btn._attr_entity_category == EntityCategory.DIAGNOSTIC


async def test_get_time_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    dc = _weather_device_code()
    btn = DuoFernGetTimeButton(coordinator, dc)
    await btn.async_press()
    coordinator.async_get_time.assert_called_once_with(dc)


def test_get_config_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernGetConfigButton(coordinator, _weather_device_code())
    assert "get_config" in btn._attr_unique_id


def test_get_config_button_entity_category_diagnostic():
    coordinator = _make_coordinator()
    btn = DuoFernGetConfigButton(coordinator, _weather_device_code())
    assert btn._attr_entity_category == EntityCategory.DIAGNOSTIC


async def test_get_config_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    dc = _weather_device_code()
    btn = DuoFernGetConfigButton(coordinator, dc)
    await btn.async_press()
    coordinator.async_get_weather_config.assert_called_once_with(dc)


def test_set_time_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernSetTimeButton(coordinator, _weather_device_code())
    assert "set_time" in btn._attr_unique_id


async def test_set_time_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    dc = _weather_device_code()
    btn = DuoFernSetTimeButton(coordinator, dc)
    await btn.async_press()
    coordinator.async_set_time.assert_called_once_with(dc)


def test_write_config_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernWriteConfigButton(coordinator, _weather_device_code())
    assert "write_config" in btn._attr_unique_id


def test_write_config_button_entity_category_config():
    coordinator = _make_coordinator()
    btn = DuoFernWriteConfigButton(coordinator, _weather_device_code())
    assert btn._attr_entity_category == EntityCategory.CONFIG


async def test_write_config_button_press_calls_coordinator():
    coordinator = _make_coordinator()
    dc = _weather_device_code()
    btn = DuoFernWriteConfigButton(coordinator, dc)
    await btn.async_press()
    coordinator.async_write_weather_config.assert_called_once_with(dc)


# ---------------------------------------------------------------------------
# DuoFernPairByCodeButton
# ---------------------------------------------------------------------------


def test_pair_by_code_button_unique_id():
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)
    assert MOCK_SYSTEM_CODE in btn._attr_unique_id
    assert "pair_by_code" in btn._attr_unique_id


def test_pair_by_code_button_entity_category_config():
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn._attr_entity_category == EntityCategory.CONFIG


def test_pair_by_code_button_available_when_connected():
    coordinator = _make_coordinator()
    coordinator.last_update_success = True
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is True


def test_pair_by_code_button_unavailable_when_not_connected():
    coordinator = _make_coordinator()
    coordinator.last_update_success = False
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)
    assert btn.available is False


async def test_pair_by_code_button_raises_when_no_text_entity():
    """Raises HomeAssistantError when text entity is not found (no code)."""
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)

    mock_hass = MagicMock()
    btn.hass = mock_hass

    with patch(
        "custom_components.duofern.button.er.async_get"
    ) as mock_er:
        mock_reg = MagicMock()
        mock_reg.async_get_entity_id.return_value = None
        mock_er.return_value = mock_reg

        with pytest.raises(HomeAssistantError):
            await btn.async_press()


async def test_pair_by_code_button_raises_when_code_too_short():
    """Raises HomeAssistantError when code is not 6 hex chars."""
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)

    mock_hass = MagicMock()
    mock_state = MagicMock()
    mock_state.state = "12AB"  # only 4 chars
    mock_hass.states.get.return_value = mock_state
    btn.hass = mock_hass

    entity_id = "text.duofern_pair_code"
    with patch(
        "custom_components.duofern.button.er.async_get"
    ) as mock_er:
        mock_reg = MagicMock()
        mock_reg.async_get_entity_id.return_value = entity_id
        mock_er.return_value = mock_reg

        with pytest.raises(HomeAssistantError):
            await btn.async_press()


async def test_pair_by_code_button_raises_when_code_not_hex():
    """Raises HomeAssistantError when code contains non-hex characters."""
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)

    mock_hass = MagicMock()
    mock_state = MagicMock()
    mock_state.state = "ZZZZZZ"  # 6 chars but not hex
    mock_hass.states.get.return_value = mock_state
    btn.hass = mock_hass

    entity_id = "text.duofern_pair_code"
    with patch(
        "custom_components.duofern.button.er.async_get"
    ) as mock_er:
        mock_reg = MagicMock()
        mock_reg.async_get_entity_id.return_value = entity_id
        mock_er.return_value = mock_reg

        with pytest.raises(HomeAssistantError):
            await btn.async_press()


async def test_pair_by_code_button_raises_when_state_is_none():
    """Raises HomeAssistantError when text entity exists but has no state."""
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)

    mock_hass = MagicMock()
    mock_hass.states.get.return_value = None  # entity found but no state object
    btn.hass = mock_hass

    entity_id = "text.duofern_pair_code"
    with patch(
        "custom_components.duofern.button.er.async_get"
    ) as mock_er:
        mock_reg = MagicMock()
        mock_reg.async_get_entity_id.return_value = entity_id
        mock_er.return_value = mock_reg

        with pytest.raises(HomeAssistantError):
            await btn.async_press()


async def test_pair_by_code_button_calls_coordinator_with_valid_code():
    """Calls async_pair_device_by_code with uppercased 6-char hex code."""
    coordinator = _make_coordinator()
    btn = DuoFernPairByCodeButton(coordinator, MOCK_SYSTEM_CODE)

    mock_hass = MagicMock()
    mock_state = MagicMock()
    mock_state.state = "ab12cd"  # lowercase — should be uppercased
    mock_hass.states.get.return_value = mock_state
    btn.hass = mock_hass

    entity_id = "text.duofern_pair_code"
    with patch(
        "custom_components.duofern.button.er.async_get"
    ) as mock_er:
        mock_reg = MagicMock()
        mock_reg.async_get_entity_id.return_value = entity_id
        mock_er.return_value = mock_reg

        await btn.async_press()

    coordinator.async_pair_device_by_code.assert_called_once_with("AB12CD")
