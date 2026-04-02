"""Tests for the DuoFern event entity platform (remote controls)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import Event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.duofern.coordinator import DUOFERN_EVENT

from custom_components.duofern.event import (
    DuoFernRemoteEvent,
    _REMOTE_EVENT_TYPES,
)
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE

# Handsender 0xA0
REMOTE_HEX = "A01234"


def _make_remote() -> DuoFernRemoteEvent:
    device_id = DuoFernId.from_hex(REMOTE_HEX)
    device_state = DuoFernDeviceState(device_code=device_id)

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[REMOTE_HEX] = device_state

    remote = DuoFernRemoteEvent(
        coordinator=coordinator,
        hex_code=REMOTE_HEX,
        device_state=device_state,
    )
    return remote


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


def test_remote_event_types_includes_up_down_stop():
    assert "up" in _REMOTE_EVENT_TYPES
    assert "down" in _REMOTE_EVENT_TYPES
    assert "stop" in _REMOTE_EVENT_TYPES


def test_remote_event_types_includes_on_off():
    assert "on" in _REMOTE_EVENT_TYPES
    assert "off" in _REMOTE_EVENT_TYPES


def test_remote_event_types_includes_step():
    assert "stepUp" in _REMOTE_EVENT_TYPES
    assert "stepDown" in _REMOTE_EVENT_TYPES


def test_remote_event_types_includes_pressed():
    assert "pressed" in _REMOTE_EVENT_TYPES


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_remote_unique_id():
    remote = _make_remote()
    assert remote._attr_unique_id == f"duofern_{REMOTE_HEX}_event"


def test_remote_event_types_attr():
    remote = _make_remote()
    assert remote._attr_event_types == _REMOTE_EVENT_TYPES


# ---------------------------------------------------------------------------
# _handle_duofern_event
# ---------------------------------------------------------------------------


def _make_ha_event(device_code: str, event_name: str, channel: str = "01") -> Event:
    mock_event = MagicMock(spec=Event)
    mock_event.data = {
        "device_code": device_code,
        "event": event_name,
        "channel": channel,
    }
    return mock_event


def test_handle_event_fires_for_matching_device():
    remote = _make_remote()
    remote._trigger_event = MagicMock()
    remote.async_write_ha_state = MagicMock()

    event = _make_ha_event(REMOTE_HEX, "up", "01")
    remote._handle_duofern_event(event)

    remote._trigger_event.assert_called_once_with("up", {"channel": "01"})
    remote.async_write_ha_state.assert_called_once()


def test_handle_event_ignores_other_device():
    remote = _make_remote()
    remote._trigger_event = MagicMock()
    remote.async_write_ha_state = MagicMock()

    event = _make_ha_event("A09999", "up", "01")
    remote._handle_duofern_event(event)

    remote._trigger_event.assert_not_called()
    remote.async_write_ha_state.assert_not_called()


def test_handle_event_ignores_unknown_event_type():
    remote = _make_remote()
    remote._trigger_event = MagicMock()
    remote.async_write_ha_state = MagicMock()

    event = _make_ha_event(REMOTE_HEX, "unknownAction", "01")
    remote._handle_duofern_event(event)

    remote._trigger_event.assert_not_called()


def test_handle_event_passes_channel():
    remote = _make_remote()
    remote._trigger_event = MagicMock()
    remote.async_write_ha_state = MagicMock()

    event = _make_ha_event(REMOTE_HEX, "down", "03")
    remote._handle_duofern_event(event)

    remote._trigger_event.assert_called_once_with("down", {"channel": "03"})


def test_handle_all_valid_event_types():
    """Every event type in _REMOTE_EVENT_TYPES is handled."""
    for event_type in _REMOTE_EVENT_TYPES:
        remote = _make_remote()
        remote._trigger_event = MagicMock()
        remote.async_write_ha_state = MagicMock()

        event = _make_ha_event(REMOTE_HEX, event_type, "01")
        remote._handle_duofern_event(event)

        remote._trigger_event.assert_called_once_with(event_type, {"channel": "01"})


# ---------------------------------------------------------------------------
# async_added_to_hass
# ---------------------------------------------------------------------------


async def test_added_to_hass_subscribes_to_event_bus():
    """async_added_to_hass subscribes to the DUOFERN_EVENT on the HA bus."""
    remote = _make_remote()

    mock_hass = MagicMock()
    mock_unsub = MagicMock()
    mock_hass.bus.async_listen.return_value = mock_unsub
    remote.hass = mock_hass

    mock_device = MagicMock()
    mock_device.serial_number = REMOTE_HEX  # already correct
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    # async_on_remove is an Entity method — patch it to avoid needing full hass
    remote.async_on_remove = MagicMock()

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock),
        patch(
            "custom_components.duofern.event.dr.async_get",
            return_value=mock_registry,
        ),
    ):
        await remote.async_added_to_hass()

    mock_hass.bus.async_listen.assert_called_once_with(
        DUOFERN_EVENT, remote._handle_duofern_event
    )
    remote.async_on_remove.assert_called_once_with(mock_unsub)


async def test_added_to_hass_updates_serial_number_when_different():
    """async_added_to_hass updates device registry when serial_number doesn't match."""
    remote = _make_remote()

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    remote.hass = mock_hass
    remote.async_on_remove = MagicMock()

    mock_device = MagicMock()
    mock_device.serial_number = "DIFFERENT"
    mock_device.id = "device-id-abc"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock),
        patch(
            "custom_components.duofern.event.dr.async_get",
            return_value=mock_registry,
        ),
    ):
        await remote.async_added_to_hass()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-abc", serial_number=REMOTE_HEX
    )


async def test_added_to_hass_no_update_when_serial_already_correct():
    """async_added_to_hass does not update registry when serial_number already matches."""
    remote = _make_remote()

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    remote.hass = mock_hass
    remote.async_on_remove = MagicMock()

    mock_device = MagicMock()
    mock_device.serial_number = REMOTE_HEX  # already matches
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock),
        patch(
            "custom_components.duofern.event.dr.async_get",
            return_value=mock_registry,
        ),
    ):
        await remote.async_added_to_hass()

    mock_registry.async_update_device.assert_not_called()


async def test_added_to_hass_no_update_when_device_not_in_registry():
    """async_added_to_hass does not crash when device not found in registry."""
    remote = _make_remote()

    mock_hass = MagicMock()
    mock_hass.bus.async_listen.return_value = MagicMock()
    remote.hass = mock_hass
    remote.async_on_remove = MagicMock()

    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = None  # not found

    with (
        patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock),
        patch(
            "custom_components.duofern.event.dr.async_get",
            return_value=mock_registry,
        ),
    ):
        await remote.async_added_to_hass()

    mock_registry.async_update_device.assert_not_called()
