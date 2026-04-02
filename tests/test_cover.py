"""Tests for the DuoFern cover platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntityFeature,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_OPENING,
    STATE_CLOSING,
)
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.cover import DuoFernCover
from custom_components.duofern.protocol import DuoFernId, ParsedStatus

from .conftest import (
    MOCK_DEVICE_CODE_COVER,
    MOCK_ENTRY_DATA,
    MOCK_ENTRY_OPTIONS,
    MOCK_SYSTEM_CODE,
)

# RolloTron Standard = 0x40
COVER_DEVICE_HEX = "406B2D"
# SX5 garage door = 0x4E
GARAGE_DEVICE_HEX = "4E1234"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cover_coordinator(hass, entry, device_hex=COVER_DEVICE_HEX):
    """Build a coordinator with one cover device, using a mock stick."""
    device_id = DuoFernId.from_hex(device_hex)
    device_state = DuoFernDeviceState(device_code=device_id)
    data = DuoFernData()
    data.devices[device_hex] = device_state

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = data
    return coordinator, device_state


# ---------------------------------------------------------------------------
# Unit tests for DuoFernCover
# ---------------------------------------------------------------------------


def test_cover_unique_id():
    """DuoFernCover unique_id includes device hex code."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    cover = DuoFernCover.__new__(DuoFernCover)
    cover._device_code = device_id
    cover._hex_code = COVER_DEVICE_HEX
    cover._attr_unique_id = f"{DOMAIN}_{COVER_DEVICE_HEX}"
    assert cover._attr_unique_id == f"duofern_{COVER_DEVICE_HEX}"


def test_cover_device_class_shutter():
    """RolloTron (0x40) gets SHUTTER device class."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    coordinator = MagicMock()
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = DuoFernDeviceState(
        device_code=device_id
    )
    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover._attr_device_class == CoverDeviceClass.SHUTTER


def test_cover_device_class_garage():
    """SX5 (0x4E) gets GARAGE device class."""
    device_id = DuoFernId.from_hex(GARAGE_DEVICE_HEX)
    coordinator = MagicMock()
    coordinator.data = DuoFernData()
    coordinator.data.devices[GARAGE_DEVICE_HEX] = DuoFernDeviceState(
        device_code=device_id
    )
    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover._attr_device_class == CoverDeviceClass.GARAGE


def test_cover_supported_features():
    """Cover supports open, close, stop, and set_position."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    coordinator = MagicMock()
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = DuoFernDeviceState(
        device_code=device_id
    )
    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert CoverEntityFeature.OPEN in cover._attr_supported_features
    assert CoverEntityFeature.CLOSE in cover._attr_supported_features
    assert CoverEntityFeature.STOP in cover._attr_supported_features
    assert CoverEntityFeature.SET_POSITION in cover._attr_supported_features


# ---------------------------------------------------------------------------
# Position / state
# ---------------------------------------------------------------------------


def test_cover_position_inverted():
    """DuoFern position 0 (open) maps to HA position 100 (open)."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.position = 0  # DuoFern 0 = fully open

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.current_cover_position == 100


def test_cover_position_closed():
    """DuoFern position 100 (closed) maps to HA position 0 (closed)."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.position = 100  # DuoFern 100 = fully closed

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.current_cover_position == 0
    assert cover.is_closed is True


def test_cover_position_midpoint():
    """DuoFern position 50 maps to HA position 50."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.position = 50

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.current_cover_position == 50
    assert cover.is_closed is False


def test_cover_position_none_when_no_data():
    """current_cover_position returns None when status.position is None."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.position = None

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.current_cover_position is None
    assert cover.is_closed is None


def test_cover_is_opening():
    """is_opening returns True when status.moving == 'up'."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.position = 50
    device_state.status.moving = "up"

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.is_opening is True
    assert cover.is_closing is False


def test_cover_is_closing():
    """is_closing returns True when status.moving == 'down'."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.position = 50
    device_state.status.moving = "down"

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.is_closing is True
    assert cover.is_opening is False


def test_cover_is_opening_false_when_no_data():
    """is_opening returns False when coordinator.data is None."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = None

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.is_opening is False


def test_cover_is_closing_false_when_no_data():
    """is_closing returns False when coordinator.data is None."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = None

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.is_closing is False


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


def test_cover_extra_state_attributes_empty_when_no_data():
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = None

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.extra_state_attributes == {}


def test_cover_extra_state_attributes_excludes_position_and_moving():
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {
        "position": 50,
        "moving": "stop",
        "sunAutomatic": "on",
    }
    device_state.status.version = None
    device_state.battery_state = None
    device_state.battery_percent = None
    device_state.last_seen = None

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    attrs = cover.extra_state_attributes
    assert "position" not in attrs
    assert "moving" not in attrs
    assert attrs.get("sunAutomatic") == "on"


def test_cover_extra_state_attributes_includes_firmware_version():
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.status.version = "2.1"
    device_state.battery_state = None
    device_state.battery_percent = None
    device_state.last_seen = None

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    attrs = cover.extra_state_attributes
    assert attrs.get("firmware_version") == "2.1"


def test_cover_extra_state_attributes_includes_battery():
    from datetime import datetime, timezone

    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.status.version = None
    device_state.battery_state = "ok"
    device_state.battery_percent = 85
    ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    device_state.last_seen = ts

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    attrs = cover.extra_state_attributes
    assert attrs.get("battery_state") == "ok"
    assert attrs.get("battery_level") == 85
    assert attrs.get("last_seen") == ts


# ---------------------------------------------------------------------------
# device_info
# ---------------------------------------------------------------------------


def test_cover_device_info_has_domain_identifier():
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.version = None

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.system_code = DuoFernId.from_hex("6F1A2B")

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    info = cover.device_info
    assert (DOMAIN, COVER_DEVICE_HEX) in info["identifiers"]


def test_cover_device_info_sw_version_from_state():
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.version = "3.0"

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.system_code = DuoFernId.from_hex("6F1A2B")

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    info = cover.device_info
    assert info.get("sw_version") == "3.0"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_cover_available():
    """available returns True when device.available and coordinator ok."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.available = True

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.available is True


def test_cover_unavailable_when_device_offline():
    """available returns False when device.available is False."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.available = False

    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.available is False


def test_cover_unavailable_when_missing_from_data():
    """available returns False when device is not in coordinator.data.devices."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()  # empty, no devices

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    assert cover.available is False


# ---------------------------------------------------------------------------
# Command methods (open/close/stop/set_position)
# ---------------------------------------------------------------------------


async def test_cover_open(hass: HomeAssistant) -> None:
    """async_open_cover calls coordinator.async_cover_up with DuoFernId."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.async_cover_up = AsyncMock()

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    await cover.async_open_cover()
    coordinator.async_cover_up.assert_called_once_with(device_id)


async def test_cover_close(hass: HomeAssistant) -> None:
    """async_close_cover calls coordinator.async_cover_down with DuoFernId."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.async_cover_down = AsyncMock()

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    await cover.async_close_cover()
    coordinator.async_cover_down.assert_called_once_with(device_id)


async def test_cover_stop(hass: HomeAssistant) -> None:
    """async_stop_cover calls coordinator.async_cover_stop with DuoFernId."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.async_cover_stop = AsyncMock()

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    await cover.async_stop_cover()
    coordinator.async_cover_stop.assert_called_once_with(device_id)


async def test_cover_set_position(hass: HomeAssistant) -> None:
    """async_set_cover_position translates HA position to DuoFern position."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.async_cover_position = AsyncMock()

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    # HA position 30 → DuoFern position 70 (inverted)
    await cover.async_set_cover_position(position=30)
    coordinator.async_cover_position.assert_called_once_with(device_id, 70)


async def test_cover_set_position_fully_open(hass: HomeAssistant) -> None:
    """HA position 100 (fully open) → DuoFern position 0."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.async_cover_position = AsyncMock()

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    await cover.async_set_cover_position(position=100)
    coordinator.async_cover_position.assert_called_once_with(device_id, 0)


async def test_cover_set_position_fully_closed(hass: HomeAssistant) -> None:
    """HA position 0 (fully closed) → DuoFern position 100."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state
    coordinator.async_cover_position = AsyncMock()

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    await cover.async_set_cover_position(position=0)
    coordinator.async_cover_position.assert_called_once_with(device_id, 100)


# ---------------------------------------------------------------------------
# _handle_coordinator_update — firmware version update
# ---------------------------------------------------------------------------


def test_cover_handle_coordinator_update_updates_firmware():
    """_handle_coordinator_update updates device registry when fw version changes."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.version = "2.0"

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    cover.async_write_ha_state = MagicMock()
    cover.hass = MagicMock()

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-cover"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    with patch(
        "custom_components.duofern.cover.dr.async_get",
        return_value=mock_registry,
    ):
        cover._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-cover", sw_version="2.0"
    )
    cover.async_write_ha_state.assert_called_once()


def test_cover_handle_coordinator_update_skips_when_version_unchanged():
    """_handle_coordinator_update skips registry update when version already matches."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.version = "2.0"

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    cover.async_write_ha_state = MagicMock()
    cover.hass = MagicMock()

    mock_device = MagicMock()
    mock_device.sw_version = "2.0"  # same version → no update
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    with patch(
        "custom_components.duofern.cover.dr.async_get",
        return_value=mock_registry,
    ):
        cover._handle_coordinator_update()

    mock_registry.async_update_device.assert_not_called()
    cover.async_write_ha_state.assert_called_once()


def test_cover_handle_coordinator_update_skips_when_no_version():
    """_handle_coordinator_update skips registry when state.status.version is None."""
    device_id = DuoFernId.from_hex(COVER_DEVICE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.version = None

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[COVER_DEVICE_HEX] = device_state

    cover = DuoFernCover(coordinator=coordinator, device_code=device_id)
    cover.async_write_ha_state = MagicMock()
    cover.hass = MagicMock()

    mock_registry = MagicMock()
    with patch(
        "custom_components.duofern.cover.dr.async_get",
        return_value=mock_registry,
    ):
        cover._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    cover.async_write_ha_state.assert_called_once()
