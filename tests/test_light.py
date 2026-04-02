"""Tests for the DuoFern light platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.light import ColorMode

from custom_components.duofern.light import DuoFernLight
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE

DIMMER_HEX = "481234"  # Dimmaktor 0x48


def _make_light() -> tuple[DuoFernLight, DuoFernDeviceState]:
    device_id = DuoFernId.from_hex(DIMMER_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.status.level = None  # explicit None so is_on returns None by default

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[DIMMER_HEX] = device_state
    coordinator.async_switch_on = AsyncMock()
    coordinator.async_switch_off = AsyncMock()
    coordinator.async_set_level = AsyncMock()

    light = DuoFernLight(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=DIMMER_HEX,
    )
    return light, device_state


def test_light_unique_id():
    light, _ = _make_light()
    assert DIMMER_HEX in light._attr_unique_id


def test_light_supported_color_modes_brightness():
    """_attr_supported_color_modes is a set containing ColorMode.BRIGHTNESS."""
    light, _ = _make_light()
    assert ColorMode.BRIGHTNESS in light._attr_supported_color_modes


def test_light_color_mode_brightness():
    light, _ = _make_light()
    assert light._attr_color_mode == ColorMode.BRIGHTNESS


def test_light_is_on_when_level_nonzero():
    """is_on uses status.level > 0."""
    light, device_state = _make_light()
    device_state.status.level = 80
    assert light.is_on is True


def test_light_is_off_when_level_zero():
    light, device_state = _make_light()
    device_state.status.level = 0
    assert light.is_on is False


def test_light_is_none_when_level_none():
    """is_on returns None when status.level is None (unknown state)."""
    light, device_state = _make_light()
    device_state.status.level = None
    assert light.is_on is None


def test_light_brightness_maps_full():
    """DuoFern level 100 → HA brightness 255."""
    light, device_state = _make_light()
    device_state.status.level = 100
    assert light.brightness == 255


def test_light_brightness_maps_midpoint():
    """DuoFern level 50 → HA brightness round(50 * 255 / 100)."""
    light, device_state = _make_light()
    device_state.status.level = 50
    assert light.brightness == round(50 * 255 / 100)


def test_light_brightness_zero():
    light, device_state = _make_light()
    device_state.status.level = 0
    assert light.brightness == 0


def test_light_brightness_none_when_level_none():
    light, device_state = _make_light()
    device_state.status.level = None
    assert light.brightness is None


async def test_light_turn_on_no_brightness_calls_switch_on():
    """async_turn_on() without brightness calls coordinator.async_switch_on(device_code)."""
    light, device_state = _make_light()
    device_id = DuoFernId.from_hex(DIMMER_HEX)
    await light.async_turn_on()
    light.coordinator.async_switch_on.assert_called_once_with(device_id)
    light.coordinator.async_set_level.assert_not_called()


async def test_light_turn_on_with_brightness_calls_set_level():
    """async_turn_on(brightness=255) calls coordinator.async_set_level(device_code, 100)."""
    light, _ = _make_light()
    device_id = DuoFernId.from_hex(DIMMER_HEX)
    await light.async_turn_on(brightness=255)
    light.coordinator.async_set_level.assert_called_once_with(device_id, 100)
    light.coordinator.async_switch_on.assert_not_called()


async def test_light_turn_on_brightness_midpoint():
    """brightness=128 → level = round(128 * 100 / 255)."""
    light, _ = _make_light()
    device_id = DuoFernId.from_hex(DIMMER_HEX)
    await light.async_turn_on(brightness=128)
    expected_level = round(128 * 100 / 255)
    light.coordinator.async_set_level.assert_called_once_with(device_id, expected_level)


async def test_light_turn_off_calls_switch_off():
    """async_turn_off calls coordinator.async_switch_off(device_code)."""
    light, _ = _make_light()
    device_id = DuoFernId.from_hex(DIMMER_HEX)
    await light.async_turn_off()
    light.coordinator.async_switch_off.assert_called_once_with(device_id)


def test_light_available_when_device_available():
    light, device_state = _make_light()
    device_state.available = True
    assert light.available is True


def test_light_unavailable_when_device_offline():
    light, device_state = _make_light()
    device_state.available = False
    assert light.available is False


def test_light_unavailable_when_coordinator_data_none():
    light, _ = _make_light()
    light.coordinator.data = None
    assert light.available is False


def test_light_unavailable_when_last_update_failed():
    light, device_state = _make_light()
    device_state.available = True
    light.coordinator.last_update_success = False
    assert light.available is False


def test_light_is_none_when_coordinator_data_none():
    light, _ = _make_light()
    light.coordinator.data = None
    assert light.is_on is None


def test_light_brightness_none_when_coordinator_data_none():
    light, _ = _make_light()
    light.coordinator.data = None
    assert light.brightness is None


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


def test_light_extra_state_attributes_empty_when_no_data():
    light, _ = _make_light()
    light.coordinator.data = None
    assert light.extra_state_attributes == {}


def test_light_extra_state_attributes_from_readings():
    light, device_state = _make_light()
    device_state.status.readings = {"timeAutomatic": "on", "level": 80}
    device_state.status.version = None
    attrs = light.extra_state_attributes
    assert attrs.get("timeAutomatic") == "on"
    # "level" is in _SKIP_AS_ATTRIBUTE → excluded
    assert "level" not in attrs


def test_light_extra_state_attributes_includes_firmware_version():
    light, device_state = _make_light()
    device_state.status.readings = {}
    device_state.status.version = "1.3"
    attrs = light.extra_state_attributes
    assert attrs.get("firmware_version") == "1.3"


# ---------------------------------------------------------------------------
# device_info
# ---------------------------------------------------------------------------


def test_light_device_info_has_domain_identifier():
    light, device_state = _make_light()
    device_state.status.version = None
    info = light.device_info
    assert (DOMAIN, DIMMER_HEX) in info["identifiers"]


def test_light_device_info_sw_version_from_state():
    light, device_state = _make_light()
    device_state.status.version = "2.0"
    info = light.device_info
    assert info.get("sw_version") == "2.0"


def test_light_device_info_sw_version_none_when_no_data():
    light, _ = _make_light()
    light.coordinator.data = None
    info = light.device_info
    assert info.get("sw_version") is None


# ---------------------------------------------------------------------------
# _handle_coordinator_update — firmware version update
# ---------------------------------------------------------------------------


def test_light_handle_coordinator_update_updates_firmware():
    """_handle_coordinator_update updates device registry when fw version changes."""
    light, device_state = _make_light()
    light.async_write_ha_state = MagicMock()

    device_state.status.version = "2.0"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-dimmer"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    light.hass = MagicMock()

    with patch(
        "custom_components.duofern.light.dr.async_get",
        return_value=mock_registry,
    ):
        light._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-dimmer", sw_version="2.0"
    )
    light.async_write_ha_state.assert_called_once()


def test_light_handle_coordinator_update_skips_when_version_unchanged():
    """_handle_coordinator_update skips registry update when version already matches."""
    light, device_state = _make_light()
    light.async_write_ha_state = MagicMock()

    device_state.status.version = "2.0"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "2.0"  # same version
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    light.hass = MagicMock()

    with patch(
        "custom_components.duofern.light.dr.async_get",
        return_value=mock_registry,
    ):
        light._handle_coordinator_update()

    mock_registry.async_update_device.assert_not_called()
    light.async_write_ha_state.assert_called_once()


def test_light_handle_coordinator_update_skips_when_no_version():
    """_handle_coordinator_update skips registry when state.status.version is None."""
    light, device_state = _make_light()
    light.async_write_ha_state = MagicMock()

    device_state.status.version = None
    device_state.available = True
    light.hass = MagicMock()

    mock_registry = MagicMock()
    with patch(
        "custom_components.duofern.light.dr.async_get",
        return_value=mock_registry,
    ):
        light._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    light.async_write_ha_state.assert_called_once()
