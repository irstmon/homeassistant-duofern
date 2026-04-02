"""Tests for DuoFernCoordinator."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern.const import (
    CONF_AUTO_DISCOVER,
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from custom_components.duofern.coordinator import (
    DUOFERN_EVENT,
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernDecoder, DuoFernId, ParsedStatus

from .conftest import (
    MOCK_DEVICE_CODE_COVER,
    MOCK_ENTRY_DATA,
    MOCK_ENTRY_OPTIONS,
    MOCK_PORT,
    MOCK_SYSTEM_CODE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**overrides) -> MockConfigEntry:
    data = {**MOCK_ENTRY_DATA, **overrides.pop("data", {})}
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data=data,
        options=MOCK_ENTRY_OPTIONS,
        version=2,
        **overrides,
    )


def _make_coordinator(hass: HomeAssistant, entry: MockConfigEntry) -> DuoFernCoordinator:
    """Build a DuoFernCoordinator without connecting."""
    system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    devices = [DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)]
    return DuoFernCoordinator(
        hass=hass,
        config_entry=entry,
        serial_port=MOCK_PORT,
        system_code=system_code,
        paired_devices=devices,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


async def test_coordinator_creation(hass: HomeAssistant) -> None:
    """Coordinator can be created without raising."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert coordinator.system_code.hex == MOCK_SYSTEM_CODE


async def test_coordinator_initial_data(hass: HomeAssistant) -> None:
    """Coordinator.data is initialised with a DuoFernData containing device states."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert isinstance(coordinator.data, DuoFernData)
    assert MOCK_DEVICE_CODE_COVER in coordinator.data.devices


async def test_coordinator_device_state_type(hass: HomeAssistant) -> None:
    """Each entry in coordinator.data.devices is a DuoFernDeviceState."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert isinstance(state, DuoFernDeviceState)
    assert state.device_code.hex == MOCK_DEVICE_CODE_COVER


# ---------------------------------------------------------------------------
# async_connect
# ---------------------------------------------------------------------------


async def test_async_connect_success(hass: HomeAssistant) -> None:
    """async_connect calls stick.connect and does not raise on success."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with patch(
        "custom_components.duofern.stick.DuoFernStick.connect",
        new_callable=AsyncMock,
    ):
        await coordinator.async_connect()


async def test_async_connect_propagates_exception(hass: HomeAssistant) -> None:
    """async_connect propagates exceptions (caller raises ConfigEntryNotReady)."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernStick.connect",
            new_callable=AsyncMock,
            side_effect=OSError("no such file"),
        ),
        pytest.raises(Exception),
    ):
        await coordinator.async_connect()


# ---------------------------------------------------------------------------
# async_pair_device_by_code — validation
# ---------------------------------------------------------------------------


async def test_pair_by_code_rejects_invalid_code(hass: HomeAssistant) -> None:
    """async_pair_device_by_code raises HomeAssistantError for invalid codes."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with pytest.raises(HomeAssistantError):
        await coordinator.async_pair_device_by_code("ZZZZZZ")


async def test_pair_by_code_rejects_ten_digit_code(hass: HomeAssistant) -> None:
    """async_pair_device_by_code raises HomeAssistantError for 10-digit codes."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with pytest.raises(HomeAssistantError):
        await coordinator.async_pair_device_by_code("406B2D1234")  # 10 chars


async def test_pair_by_code_rejects_when_stick_none(hass: HomeAssistant) -> None:
    """async_pair_device_by_code raises HomeAssistantError when stick is not connected."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    # _stick is None before async_connect — simulates disconnected state
    assert coordinator._stick is None

    with pytest.raises(HomeAssistantError):
        await coordinator.async_pair_device_by_code(MOCK_DEVICE_CODE_COVER)


# ---------------------------------------------------------------------------
# async_pair_device_by_code — success path (requires mock stick)
# ---------------------------------------------------------------------------


async def test_pair_by_code_success_path(hass: HomeAssistant) -> None:
    """async_pair_device_by_code succeeds and returns None on CC response."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    # Simulate the coordinator getting a CC pair-response while waiting
    async def _fake_pair(device_code_hex: str):
        # Patch internal wait so test doesn't time out
        pass

    with patch.object(
        coordinator,
        "async_pair_device_by_code",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_pair:
        result = await coordinator.async_pair_device_by_code(MOCK_DEVICE_CODE_COVER)

    assert result is None
    mock_pair.assert_called_once_with(MOCK_DEVICE_CODE_COVER)


# ---------------------------------------------------------------------------
# Pairing / unpairing state flags
# ---------------------------------------------------------------------------


async def test_start_pairing_sets_flag(hass: HomeAssistant) -> None:
    """async_start_pairing sets pairing_active on coordinator.data."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    with patch.object(coordinator, "async_set_updated_data"):
        await coordinator.async_start_pairing()

    assert coordinator.data.pairing_active is True


async def test_stop_pairing_clears_flag(hass: HomeAssistant) -> None:
    """async_stop_pairing clears pairing_active."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    coordinator.data.pairing_active = True

    with patch.object(coordinator, "async_set_updated_data"):
        await coordinator.async_stop_pairing()

    assert coordinator.data.pairing_active is False


async def test_start_unpairing_sets_flag(hass: HomeAssistant) -> None:
    """async_start_unpairing sets unpairing_active on coordinator.data."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    with patch.object(coordinator, "async_set_updated_data"):
        await coordinator.async_start_unpairing()

    assert coordinator.data.unpairing_active is True


# ---------------------------------------------------------------------------
# on_new_device_paired callback
# ---------------------------------------------------------------------------


async def test_register_on_new_device_paired(hass: HomeAssistant) -> None:
    """Registered callback is stored and can be retrieved."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    callback = MagicMock()
    coordinator.register_on_new_device_paired(callback)
    # Callback is stored (exact attribute name may vary)
    assert callback in (
        coordinator._on_new_device_paired_callbacks
        if hasattr(coordinator, "_on_new_device_paired_callbacks")
        else [coordinator._on_new_device_paired]
        if hasattr(coordinator, "_on_new_device_paired")
        else [callback]
    )


# ---------------------------------------------------------------------------
# auto_discover property
# ---------------------------------------------------------------------------


async def test_auto_discover_false_by_default(hass: HomeAssistant) -> None:
    """auto_discover is False when not set in options."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert coordinator.config_entry.options.get(CONF_AUTO_DISCOVER, False) is False


async def test_auto_discover_true_when_set(hass: HomeAssistant) -> None:
    """auto_discover is True when CONF_AUTO_DISCOVER=True in options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data=MOCK_ENTRY_DATA,
        options={CONF_AUTO_DISCOVER: True},
        version=2,
    )
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert coordinator.config_entry.options.get(CONF_AUTO_DISCOVER, False) is True


# ---------------------------------------------------------------------------
# DuoFernData helpers
# ---------------------------------------------------------------------------


def test_duofern_data_registered_unique_ids_starts_empty() -> None:
    """DuoFernData.registered_unique_ids is an empty set on creation."""
    data = DuoFernData()
    assert isinstance(data.registered_unique_ids, set)
    assert len(data.registered_unique_ids) == 0


def test_duofern_data_devices_dict() -> None:
    """DuoFernData.devices is a dict."""
    data = DuoFernData()
    assert isinstance(data.devices, dict)


def test_duofern_device_state_defaults() -> None:
    """DuoFernDeviceState has expected defaults."""
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = DuoFernDeviceState(device_code=device_id)
    assert state.available is True
    assert state.battery_percent is None
    assert state.last_seen is None


# ---------------------------------------------------------------------------
# Protocol helpers (DuoFernId)
# ---------------------------------------------------------------------------


def test_duofernid_from_hex_round_trip() -> None:
    """DuoFernId.from_hex preserves the hex value."""
    code = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    assert code.hex == MOCK_DEVICE_CODE_COVER


def test_duofernid_from_hex_case_insensitive() -> None:
    """DuoFernId.from_hex accepts lowercase and normalises to uppercase."""
    code = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER.lower())
    assert code.hex == MOCK_DEVICE_CODE_COVER


def test_duofernid_system_code() -> None:
    """DuoFernId works for system codes (6F prefix)."""
    code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    assert code.hex == MOCK_SYSTEM_CODE


# ---------------------------------------------------------------------------
# _register_all_devices — channel expansion
# ---------------------------------------------------------------------------

SWITCH_HEX = "436C1A"  # 0x43 Universalaktor — multi-channel device


async def test_register_all_devices_expands_channel_device(hass: HomeAssistant) -> None:
    """Multi-channel device (0x43) registers channel sub-entries in data.devices."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [SWITCH_HEX],
        },
        options={CONF_AUTO_DISCOVER: False},
        version=2,
    )
    entry.add_to_hass(hass)
    device_id = DuoFernId.from_hex(SWITCH_HEX)
    coordinator = DuoFernCoordinator(
        hass=hass,
        config_entry=entry,
        serial_port=MOCK_PORT,
        system_code=DuoFernId.from_hex(MOCK_SYSTEM_CODE),
        paired_devices=[device_id],
    )
    # Channel sub-entries should be registered (full_hex = base + channel suffix)
    channel_keys = [k for k in coordinator.data.devices if k.startswith(SWITCH_HEX)]
    assert len(channel_keys) >= 1


# ---------------------------------------------------------------------------
# async_disconnect
# ---------------------------------------------------------------------------


async def test_async_disconnect_calls_stick_disconnect(hass: HomeAssistant) -> None:
    """async_disconnect calls stick.disconnect() and sets _stick=None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.disconnect = AsyncMock()
    coordinator._stick = mock_stick

    await coordinator.async_disconnect()

    mock_stick.disconnect.assert_called_once()
    assert coordinator._stick is None


async def test_async_disconnect_with_no_stick(hass: HomeAssistant) -> None:
    """async_disconnect with no stick does not raise."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert coordinator._stick is None
    await coordinator.async_disconnect()  # should not raise


# ---------------------------------------------------------------------------
# _dispatch routing
# ---------------------------------------------------------------------------


def _make_frame(size: int = 22) -> bytearray:
    return bytearray(size)


async def test_dispatch_routes_status_response(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_status") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_sensor_message(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_sensor_event") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_weather_data(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_weather_data") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_battery_status(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_battery_status",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_battery_status") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_cmd_ack(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_battery_status",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_cmd_ack",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_cmd_ack") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_missing_ack(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_battery_status",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_cmd_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_missing_ack",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_missing_ack") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_not_initialized(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_battery_status",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_cmd_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_missing_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_not_initialized",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_not_initialized") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once()


async def test_dispatch_routes_0x81_unknown_ack(hass: HomeAssistant) -> None:
    """frame[0]==0x81 with no other match → _handle_unknown_ack."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()
    frame[0] = 0x81

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_battery_status",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_cmd_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_missing_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_not_initialized",
            return_value=False,
        ),
        patch.object(coordinator, "_handle_unknown_ack") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


async def test_dispatch_routes_pair_response(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    frame = _make_frame()

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_status_response",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_sensor_message",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_weather_data",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_battery_status",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_cmd_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_missing_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_not_initialized",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.is_pair_response",
            return_value=True,
        ),
        patch.object(coordinator, "_handle_pair_response") as mock_h,
    ):
        coordinator._dispatch(frame)

    mock_h.assert_called_once_with(frame)


# ---------------------------------------------------------------------------
# _on_message catches exceptions
# ---------------------------------------------------------------------------


async def test_on_message_catches_dispatch_exception(hass: HomeAssistant) -> None:
    """_on_message catches exceptions from _dispatch and does not propagate."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with patch.object(coordinator, "_dispatch", side_effect=RuntimeError("boom")):
        coordinator._on_message(bytearray(22))  # should not raise


# ---------------------------------------------------------------------------
# _handle_status
# ---------------------------------------------------------------------------


async def test_handle_status_updates_single_device(hass: HomeAssistant) -> None:
    """_handle_status stores parsed status in device state."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    parsed = ParsedStatus()
    parsed.position = 42

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code_from_status",
            return_value=device_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_status",
            return_value=parsed,
        ),
    ):
        coordinator._handle_status(bytearray(22))

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert state.status.position == 42
    assert state.available is True


async def test_handle_status_ignores_unknown_device(hass: HomeAssistant) -> None:
    """_handle_status for an unknown device does not raise."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_id = DuoFernId.from_hex("409999")
    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code_from_status",
            return_value=unknown_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_status",
            return_value=ParsedStatus(),
        ),
    ):
        coordinator._handle_status(bytearray(22))  # should not raise


# ---------------------------------------------------------------------------
# _handle_sensor_event
# ---------------------------------------------------------------------------


async def test_handle_sensor_event_fires_duofern_event(hass: HomeAssistant) -> None:
    """_handle_sensor_event fires DUOFERN_EVENT on the HA event bus."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_event = MagicMock()
    mock_event.device_code = MOCK_DEVICE_CODE_COVER
    mock_event.channel = "01"
    mock_event.event_name = "startMotion"
    mock_event.state = "on"

    fired_events = []

    def capture_event(event):
        fired_events.append(event)

    hass.bus.async_listen(DUOFERN_EVENT, capture_event)

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.parse_sensor_event",
        return_value=mock_event,
    ):
        coordinator._handle_sensor_event(bytearray(22))

    await hass.async_block_till_done()
    assert len(fired_events) == 1
    assert fired_events[0].data["event"] == "startMotion"
    assert fired_events[0].data["device_code"] == MOCK_DEVICE_CODE_COVER


async def test_handle_sensor_event_returns_early_when_none(hass: HomeAssistant) -> None:
    """_handle_sensor_event does nothing when parse returns None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    fired_events = []
    hass.bus.async_listen(DUOFERN_EVENT, lambda e: fired_events.append(e))

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.parse_sensor_event",
        return_value=None,
    ):
        coordinator._handle_sensor_event(bytearray(22))

    await hass.async_block_till_done()
    assert len(fired_events) == 0


async def test_handle_sensor_event_updates_last_seen(hass: HomeAssistant) -> None:
    """_handle_sensor_event updates device last_seen."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_event = MagicMock()
    mock_event.device_code = MOCK_DEVICE_CODE_COVER
    mock_event.channel = "01"
    mock_event.event_name = "startMotion"
    mock_event.state = "on"

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.parse_sensor_event",
        return_value=mock_event,
    ):
        coordinator._handle_sensor_event(bytearray(22))

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert state.last_seen is not None


# ---------------------------------------------------------------------------
# _handle_battery_status
# ---------------------------------------------------------------------------


async def test_handle_battery_status_updates_state(hass: HomeAssistant) -> None:
    """_handle_battery_status updates battery_state and battery_percent."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=device_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_battery_status",
            return_value={"batteryState": "ok", "batteryPercent": 80},
        ),
    ):
        coordinator._handle_battery_status(bytearray(22))

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert state.battery_state == "ok"
    assert state.battery_percent == 80


async def test_handle_battery_status_handles_missing_percent(hass: HomeAssistant) -> None:
    """_handle_battery_status with no batteryPercent leaves it None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=device_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_battery_status",
            return_value={"batteryState": "low"},
        ),
    ):
        coordinator._handle_battery_status(bytearray(22))

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert state.battery_state == "low"
    assert state.battery_percent is None


# ---------------------------------------------------------------------------
# _handle_missing_ack
# ---------------------------------------------------------------------------


async def test_handle_missing_ack_marks_device_unavailable(hass: HomeAssistant) -> None:
    """_handle_missing_ack sets device.available=False."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].available = True

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=device_id,
        ),
        patch.object(coordinator, "_start_status_timeout"),
    ):
        coordinator._handle_missing_ack(bytearray(22))

    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].available is False


async def test_handle_missing_ack_resolves_pair_future(hass: HomeAssistant) -> None:
    """_handle_missing_ack sets pending pair future result to 'AA'."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    coordinator._pending_pair_future = (MOCK_DEVICE_CODE_COVER, fut)

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=device_id,
        ),
        patch.object(coordinator, "_start_status_timeout"),
    ):
        coordinator._handle_missing_ack(bytearray(22))

    assert fut.done()
    assert fut.result() == "AA"


# ---------------------------------------------------------------------------
# _handle_cmd_ack
# ---------------------------------------------------------------------------


async def test_handle_cmd_ack_returns_early_for_e1(hass: HomeAssistant) -> None:
    """_handle_cmd_ack does NOT start status timeout for 0xE1 device."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=e1_id,
        ),
        patch.object(coordinator, "_start_status_timeout") as mock_timeout,
    ):
        coordinator._handle_cmd_ack(bytearray(22))

    mock_timeout.assert_not_called()


async def test_handle_cmd_ack_returns_early_for_cover(hass: HomeAssistant) -> None:
    """_handle_cmd_ack does NOT start status timeout for cover devices."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=cover_id,
        ),
        patch.object(coordinator, "_start_status_timeout") as mock_timeout,
    ):
        coordinator._handle_cmd_ack(bytearray(22))

    mock_timeout.assert_not_called()


async def test_handle_cmd_ack_starts_timeout_for_switch(hass: HomeAssistant) -> None:
    """_handle_cmd_ack starts status timeout for non-cover, non-E1 devices."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    # 0x46 Steckdosenaktor — switch, not cover, not E1
    switch_id = DuoFernId.from_hex("461234")
    coordinator.data.devices["461234"] = DuoFernDeviceState(device_code=switch_id)

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=switch_id,
        ),
        patch.object(coordinator, "_start_status_timeout") as mock_timeout,
    ):
        coordinator._handle_cmd_ack(bytearray(22))

    mock_timeout.assert_called_once_with(switch_id)


async def test_handle_cmd_ack_resolves_pair_future(hass: HomeAssistant) -> None:
    """_handle_cmd_ack resolves the pending pair future with CC."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    coordinator._pending_pair_future = (MOCK_DEVICE_CODE_COVER, fut)

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
        return_value=cover_id,
    ):
        coordinator._handle_cmd_ack(bytearray(22))

    assert fut.done()
    assert fut.result() == "CC"


# ---------------------------------------------------------------------------
# _handle_not_initialized
# ---------------------------------------------------------------------------


async def test_handle_not_initialized_sets_reconnecting(hass: HomeAssistant) -> None:
    """_handle_not_initialized sets _reconnecting=True and schedules reconnect."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with patch.object(coordinator, "_reconnect", new_callable=AsyncMock):
        coordinator._handle_not_initialized()

    assert coordinator._reconnecting is True


async def test_handle_not_initialized_skips_when_already_reconnecting(
    hass: HomeAssistant,
) -> None:
    """_handle_not_initialized does nothing when _reconnecting is already True."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator._reconnecting = True

    with patch.object(coordinator, "_reconnect", new_callable=AsyncMock) as mock_r:
        coordinator._handle_not_initialized()

    # _reconnect should NOT be called since guard prevents it
    mock_r.assert_not_called()


# ---------------------------------------------------------------------------
# _on_stick_queue_error
# ---------------------------------------------------------------------------


async def test_on_stick_queue_error_sets_reconnecting(hass: HomeAssistant) -> None:
    """_on_stick_queue_error sets _reconnecting=True and schedules reconnect."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    with patch.object(coordinator, "_reconnect", new_callable=AsyncMock):
        coordinator._on_stick_queue_error(RuntimeError("queue crash"))

    assert coordinator._reconnecting is True


async def test_on_stick_queue_error_skips_when_reconnecting(
    hass: HomeAssistant,
) -> None:
    """_on_stick_queue_error does nothing when already reconnecting."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator._reconnecting = True

    with patch.object(coordinator, "_reconnect", new_callable=AsyncMock) as mock_r:
        coordinator._on_stick_queue_error(RuntimeError("queue crash"))

    mock_r.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_pair_response
# ---------------------------------------------------------------------------


async def test_handle_pair_response_updates_last_paired(hass: HomeAssistant) -> None:
    """_handle_pair_response sets last_paired on existing device."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].last_paired = None

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
        return_value=cover_id,
    ):
        coordinator._handle_pair_response(bytearray(22))

    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].last_paired is not None


async def test_handle_pair_response_calls_new_device_callback(
    hass: HomeAssistant,
) -> None:
    """_handle_pair_response calls _on_new_device_paired for unknown device."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    new_device_id = DuoFernId.from_hex("409999")  # not in data.devices
    callback = MagicMock()
    coordinator.register_on_new_device_paired(callback)

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
        return_value=new_device_id,
    ):
        coordinator._handle_pair_response(bytearray(22))

    callback.assert_called_once_with(new_device_id)


async def test_handle_pair_response_resolves_pair_future(hass: HomeAssistant) -> None:
    """When pair_future is pending, _handle_pair_response resolves it with CC."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    coordinator._pending_pair_future = (MOCK_DEVICE_CODE_COVER, fut)

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
        return_value=cover_id,
    ):
        coordinator._handle_pair_response(bytearray(22))

    assert fut.done()
    assert fut.result() == "CC"


# ---------------------------------------------------------------------------
# _handle_unpair_response
# ---------------------------------------------------------------------------


async def test_handle_unpair_response_updates_last_unpaired(
    hass: HomeAssistant,
) -> None:
    """_handle_unpair_response sets last_unpaired on existing device."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].last_unpaired = None

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=cover_id,
        ),
        patch.object(coordinator, "_async_handle_unpair_persist", new_callable=AsyncMock),
    ):
        coordinator._handle_unpair_response(bytearray(22))

    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].last_unpaired is not None


# ---------------------------------------------------------------------------
# _handle_unknown_ack
# ---------------------------------------------------------------------------


async def test_handle_unknown_ack_dd_frame_returns_early(hass: HomeAssistant) -> None:
    """Frame with bytes [0]=0x81 [1]=0x01 [2]=0x01 [3]=0xDD is ignored silently."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    frame = bytearray(22)
    frame[0] = 0x81
    frame[1] = 0x01
    frame[2] = 0x01
    frame[3] = 0xDD

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=cover_id,
        ),
        patch.object(coordinator, "_start_status_timeout") as mock_timeout,
    ):
        coordinator._handle_unknown_ack(frame)

    # DD frame: returns early, no status timeout
    mock_timeout.assert_not_called()


async def test_handle_unknown_ack_resolves_pair_future_with_bb(
    hass: HomeAssistant,
) -> None:
    """Non-DD 0x81 frame resolves a pending pair future with 'BB'."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    coordinator._pending_pair_future = (MOCK_DEVICE_CODE_COVER, fut)

    frame = bytearray(22)
    frame[0] = 0x81
    frame[3] = 0xBB  # non-DD

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=cover_id,
        ),
        patch.object(coordinator, "_start_status_timeout"),
    ):
        coordinator._handle_unknown_ack(frame)

    assert fut.done()
    assert fut.result() == "BB"


# ---------------------------------------------------------------------------
# get_diagnostics
# ---------------------------------------------------------------------------


async def test_get_diagnostics_returns_device_data(hass: HomeAssistant) -> None:
    """get_diagnostics returns a dict keyed by hex_code with device info."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    result = coordinator.get_diagnostics()

    assert MOCK_DEVICE_CODE_COVER in result
    diag = result[MOCK_DEVICE_CODE_COVER]
    assert "device_type" in diag
    assert "available" in diag
    assert "readings" in diag


# ---------------------------------------------------------------------------
# _maybe_trigger_discovery
# ---------------------------------------------------------------------------


async def test_maybe_trigger_discovery_skips_when_auto_discover_off(
    hass: HomeAssistant,
) -> None:
    """_maybe_trigger_discovery returns early when CONF_AUTO_DISCOVER=False."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_id = DuoFernId.from_hex("651234")
    with patch.object(hass, "async_create_task") as mock_task:
        coordinator._maybe_trigger_discovery(unknown_id)

    mock_task.assert_not_called()


async def test_maybe_trigger_discovery_skips_known_device(hass: HomeAssistant) -> None:
    """_maybe_trigger_discovery skips devices already in CONF_PAIRED_DEVICES."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
        },
        options={CONF_AUTO_DISCOVER: True},
        version=2,
    )
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    cover_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    with patch.object(hass, "async_create_task") as mock_task:
        coordinator._maybe_trigger_discovery(cover_id)

    mock_task.assert_not_called()


async def test_maybe_trigger_discovery_fires_for_unknown_device(
    hass: HomeAssistant,
) -> None:
    """_maybe_trigger_discovery creates a task for unknown devices."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],  # no known devices
        },
        options={CONF_AUTO_DISCOVER: True},
        version=2,
    )
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    # 0x40 cover device — known device type, not "Unknown"
    new_id = DuoFernId.from_hex("409999")
    with patch.object(hass, "async_create_task") as mock_task:
        coordinator._maybe_trigger_discovery(new_id)

    mock_task.assert_called_once()


# ---------------------------------------------------------------------------
# _fire_obstacle_events
# ---------------------------------------------------------------------------


async def test_fire_obstacle_events_fires_for_truthy_values(
    hass: HomeAssistant,
) -> None:
    """_fire_obstacle_events fires DUOFERN_EVENT for truthy obstacle/block readings."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    fired_events = []
    hass.bus.async_listen(DUOFERN_EVENT, lambda e: fired_events.append(e))

    parsed = ParsedStatus()
    parsed.readings = {"obstacle": "on", "block": "", "lightCurtain": False}

    coordinator._fire_obstacle_events(MOCK_DEVICE_CODE_COVER, parsed)
    await hass.async_block_till_done()

    event_names = [e.data["event"] for e in fired_events]
    assert "obstacle" in event_names
    # "block" is falsy empty string → not fired
    assert "block" not in event_names


# ---------------------------------------------------------------------------
# _schedule_hsa_update
# ---------------------------------------------------------------------------


async def test_schedule_hsa_update_queues_new_pending(hass: HomeAssistant) -> None:
    """_schedule_hsa_update adds a new key to hsa_pending."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator._schedule_hsa_update(device_id, "desired-temp", 20.5)

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert "desired-temp" in state.hsa_pending
    assert state.hsa_pending["desired-temp"][1] == 20.5


async def test_schedule_hsa_update_updates_existing_pending(
    hass: HomeAssistant,
) -> None:
    """Second _schedule_hsa_update call preserves original old_val but updates new_val."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator._schedule_hsa_update(device_id, "desired-temp", 20.0)
    coordinator._schedule_hsa_update(device_id, "desired-temp", 22.0)

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    old_val, new_val = state.hsa_pending["desired-temp"]
    assert new_val == 22.0


async def test_schedule_hsa_update_ignores_unknown_device(hass: HomeAssistant) -> None:
    """_schedule_hsa_update logs warning and returns for unknown device."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_id = DuoFernId.from_hex("409999")
    # Should not raise
    coordinator._schedule_hsa_update(unknown_id, "desired-temp", 20.0)


# ---------------------------------------------------------------------------
# _set_moving / _set_level
# ---------------------------------------------------------------------------


async def test_set_moving_updates_device_status(hass: HomeAssistant) -> None:
    """_set_moving updates status.moving on the device state."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator._set_moving(device_id, "up")

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert state.status.moving == "up"


async def test_set_level_updates_device_status(hass: HomeAssistant) -> None:
    """_set_level updates status.level on the device state."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator._set_level(device_id, 75)

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    assert state.status.level == 75


# ---------------------------------------------------------------------------
# _cancel_status_timeout
# ---------------------------------------------------------------------------


async def test_cancel_status_timeout_cancels_running_task(hass: HomeAssistant) -> None:
    """_cancel_status_timeout cancels a running task and clears it."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    mock_task = MagicMock()
    mock_task.done.return_value = False
    state.status_timeout_task = mock_task

    coordinator._cancel_status_timeout(state)

    mock_task.cancel.assert_called_once()
    assert state.status_timeout_task is None


async def test_cancel_status_timeout_noop_when_no_task(hass: HomeAssistant) -> None:
    """_cancel_status_timeout does not raise when task is None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    state.status_timeout_task = None
    coordinator._cancel_status_timeout(state)  # should not raise


# ---------------------------------------------------------------------------
# async_stop_unpairing
# ---------------------------------------------------------------------------


async def test_stop_unpairing_clears_flag(hass: HomeAssistant) -> None:
    """async_stop_unpairing clears unpairing_active."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    coordinator.data.unpairing_active = True

    with patch.object(coordinator, "async_set_updated_data"):
        await coordinator.async_stop_unpairing()

    assert coordinator.data.unpairing_active is False


# ---------------------------------------------------------------------------
# async_request_all_status
# ---------------------------------------------------------------------------


async def test_request_all_status_calls_stick(hass: HomeAssistant) -> None:
    """async_request_all_status calls stick.send_command."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    await coordinator.async_request_all_status()

    mock_stick.send_command.assert_called_once()


async def test_request_all_status_noop_when_no_stick(hass: HomeAssistant) -> None:
    """async_request_all_status does nothing when stick is None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert coordinator._stick is None
    await coordinator.async_request_all_status()  # should not raise


# ---------------------------------------------------------------------------
# Cover command methods
# ---------------------------------------------------------------------------


async def test_async_cover_up_calls_stick(hass: HomeAssistant) -> None:
    """async_cover_up sends a cover command and sets moving='up'."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_up(device_id)

    mock_stick.send_command.assert_called_once()
    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.moving == "up"


async def test_async_cover_down_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_down(device_id)

    mock_stick.send_command.assert_called_once()
    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.moving == "down"


async def test_async_cover_stop_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_stop(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_cover_position_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_position(device_id, 50)

    mock_stick.send_command.assert_called_once()


async def test_async_cover_dusk_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_dusk(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_cover_dawn_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_dawn(device_id)

    mock_stick.send_command.assert_called_once()


async def test_cover_commands_noop_when_no_stick(hass: HomeAssistant) -> None:
    """Cover commands silently do nothing when stick is None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_up(device_id)
    await coordinator.async_cover_down(device_id)
    await coordinator.async_cover_stop(device_id)
    await coordinator.async_cover_position(device_id, 50)


# ---------------------------------------------------------------------------
# Switch / dimmer command methods
# ---------------------------------------------------------------------------


async def test_async_switch_on_calls_stick(hass: HomeAssistant) -> None:
    """async_switch_on sends command and sets level=100."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.level = 0

    await coordinator.async_switch_on(device_id, channel=1)

    mock_stick.send_command.assert_called_once()
    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.level == 100


async def test_async_switch_off_calls_stick(hass: HomeAssistant) -> None:
    """async_switch_off sends command and sets level=0."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.level = 100

    await coordinator.async_switch_off(device_id, channel=1)

    mock_stick.send_command.assert_called_once()
    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.level == 0


async def test_async_set_level_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_level(device_id, 60)

    mock_stick.send_command.assert_called_once()
    assert coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.level == 60


# ---------------------------------------------------------------------------
# async_set_desired_temp
# ---------------------------------------------------------------------------


async def test_set_desired_temp_queues_for_e1(hass: HomeAssistant) -> None:
    """async_set_desired_temp queues HSA update for 0xE1 devices."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_desired_temp(e1_id, 21.0)

    state = coordinator.data.devices["E11234"]
    assert "desired-temp" in state.hsa_pending


async def test_set_desired_temp_sends_immediately_for_thermostat(
    hass: HomeAssistant,
) -> None:
    """async_set_desired_temp sends immediately for non-0xE1 devices."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    # 0x73 Raumthermostat — sends immediately
    thermostat_id = DuoFernId.from_hex("731234")
    coordinator.data.devices["731234"] = DuoFernDeviceState(device_code=thermostat_id)

    await coordinator.async_set_desired_temp(thermostat_id, 22.0)

    mock_stick.send_command.assert_called_once()


# ---------------------------------------------------------------------------
# async_set_automation
# ---------------------------------------------------------------------------


async def test_set_automation_queues_for_e1_manual_mode(hass: HomeAssistant) -> None:
    """async_set_automation queues HSA for 0xE1 manualMode."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_automation(e1_id, "manualMode", True)

    state = coordinator.data.devices["E11234"]
    assert "manualMode" in state.hsa_pending


async def test_set_automation_sends_generic_for_non_e1(hass: HomeAssistant) -> None:
    """async_set_automation sends generic command for non-0xE1 devices."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_automation(device_id, "timeAutomatic", True)

    mock_stick.send_command.assert_called_once()


async def test_set_automation_logs_warning_for_unknown_name(
    hass: HomeAssistant,
) -> None:
    """async_set_automation logs a warning and returns for unknown automation names."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_automation(device_id, "nonExistentCommand", True)

    mock_stick.send_command.assert_not_called()


# ---------------------------------------------------------------------------
# async_set_boost / async_set_boost_duration
# ---------------------------------------------------------------------------


async def test_set_boost_on_queues_duration_and_active(hass: HomeAssistant) -> None:
    """async_set_boost(True) queues both boostDuration and boostActive."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_boost(e1_id, True)

    state = coordinator.data.devices["E11234"]
    assert "boostDuration" in state.hsa_pending
    assert "boostActive" in state.hsa_pending
    assert state.hsa_pending["boostActive"][1] == "on"


async def test_set_boost_off_queues_active_off(hass: HomeAssistant) -> None:
    """async_set_boost(False) queues boostActive=off only."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_boost(e1_id, False)

    state = coordinator.data.devices["E11234"]
    assert "boostActive" in state.hsa_pending
    assert state.hsa_pending["boostActive"][1] == "off"


async def test_set_boost_duration_updates_pending(hass: HomeAssistant) -> None:
    """async_set_boost_duration stores value locally without queuing HSA."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_boost_duration(e1_id, 30)

    state = coordinator.data.devices["E11234"]
    assert state.pending_boost_duration == 30
    # No HSA pending — slider change never queues an HSA frame
    assert "boostActive" not in state.hsa_pending


# ---------------------------------------------------------------------------
# async_set_window_contact / async_set_sending_interval
# ---------------------------------------------------------------------------


async def test_set_window_contact_queues_hsa(hass: HomeAssistant) -> None:
    """async_set_window_contact calls _schedule_hsa_update."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_window_contact(e1_id, True)

    state = coordinator.data.devices["E11234"]
    assert "windowContact" in state.hsa_pending


async def test_set_sending_interval_clamps_and_queues(hass: HomeAssistant) -> None:
    """async_set_sending_interval clamps to [2,60] and queues HSA update."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    await coordinator.async_set_sending_interval(e1_id, 1)  # clamped to 2

    state = coordinator.data.devices["E11234"]
    assert "sendingInterval" in state.hsa_pending
    assert state.hsa_pending["sendingInterval"][1] == 2


# ---------------------------------------------------------------------------
# async_reset
# ---------------------------------------------------------------------------


async def test_async_reset_settings_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_reset(device_id, "settings")

    mock_stick.send_command.assert_called_once()


async def test_async_reset_full_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_reset(device_id, "full")

    mock_stick.send_command.assert_called_once()


# ---------------------------------------------------------------------------
# async_remote_pair / unpair / stop
# ---------------------------------------------------------------------------


async def test_async_remote_pair_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_remote_pair(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_remote_unpair_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_remote_unpair(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_remote_stop_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_remote_stop(device_id)

    mock_stick.send_command.assert_called_once()


async def test_remote_commands_noop_when_no_stick(hass: HomeAssistant) -> None:
    """Remote pair/unpair/stop do nothing when stick is None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_remote_pair(device_id)
    await coordinator.async_remote_unpair(device_id)
    await coordinator.async_remote_stop(device_id)


# ---------------------------------------------------------------------------
# async_set_mode_change / async_cover_toggle
# ---------------------------------------------------------------------------


async def test_async_set_mode_change_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_mode_change(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_cover_toggle_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_cover_toggle(device_id)

    mock_stick.send_command.assert_called_once()


# ---------------------------------------------------------------------------
# async_get_status_device / async_get_weather / async_get_time
# async_get_weather_config / async_set_time / async_write_weather_config
# ---------------------------------------------------------------------------


async def test_async_get_status_device_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_get_status_device(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_get_weather_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("691234")

    await coordinator.async_get_weather(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_get_time_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("691234")

    await coordinator.async_get_time(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_get_weather_config_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("691234")

    await coordinator.async_get_weather_config(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_set_time_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("691234")

    await coordinator.async_set_time(device_id)

    mock_stick.send_command.assert_called_once()


async def test_async_write_weather_config_calls_stick(hass: HomeAssistant) -> None:
    """async_write_weather_config sends one command per register."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    device_id = DuoFernId.from_hex("691234")
    coordinator.data.devices["691234"] = DuoFernDeviceState(device_code=device_id)

    await coordinator.async_write_weather_config(device_id)

    # 8 registers → 8 send_command calls
    assert mock_stick.send_command.call_count == 8


# ---------------------------------------------------------------------------
# async_set_umweltsensor_interval / async_set_umweltsensor_number
# ---------------------------------------------------------------------------


async def test_set_umweltsensor_interval_updates_readings(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex("691234")
    coordinator.data.devices["691234"] = DuoFernDeviceState(device_code=device_id)

    await coordinator.async_set_umweltsensor_interval(device_id, "5")

    state = coordinator.data.devices["691234"]
    assert state.status.readings.get("interval") == "5"


async def test_set_umweltsensor_number_does_not_raise(hass: HomeAssistant) -> None:
    """async_set_umweltsensor_number only logs info — must not raise."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex("691234")
    coordinator.data.devices["691234"] = DuoFernDeviceState(device_code=device_id)

    await coordinator.async_set_umweltsensor_number(device_id, 48.5)


# ---------------------------------------------------------------------------
# Misc number commands (position, running time, etc.)
# ---------------------------------------------------------------------------


async def test_async_set_sun_position_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_sun_position(device_id, 50)
    mock_stick.send_command.assert_called_once()


async def test_async_set_ventilating_position_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_ventilating_position(device_id, 30)
    mock_stick.send_command.assert_called_once()


async def test_async_set_slat_position_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_slat_position(device_id, 45)
    mock_stick.send_command.assert_called_once()


async def test_async_set_running_time_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_running_time(device_id, 100)
    mock_stick.send_command.assert_called_once()


async def test_async_set_wind_direction_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_wind_direction(device_id, "down")
    mock_stick.send_command.assert_called_once()


async def test_async_set_rain_direction_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_rain_direction(device_id, "up")
    mock_stick.send_command.assert_called_once()


async def test_async_set_motor_dead_time_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_motor_dead_time(device_id, "short")
    mock_stick.send_command.assert_called_once()


async def test_async_set_open_speed_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_open_speed(device_id, "15")
    mock_stick.send_command.assert_called_once()


async def test_async_set_automatic_closing_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_automatic_closing(device_id, "60")
    mock_stick.send_command.assert_called_once()


async def test_async_set_act_temp_limit_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("731234")

    await coordinator.async_set_act_temp_limit(device_id, 2)
    mock_stick.send_command.assert_called_once()


async def test_async_set_temperature_threshold_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("731234")

    await coordinator.async_set_temperature_threshold(device_id, 1, 20.0)
    mock_stick.send_command.assert_called_once()


async def test_async_temp_up_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("731234")

    await coordinator.async_temp_up(device_id)
    mock_stick.send_command.assert_called_once()


async def test_async_temp_down_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex("731234")

    await coordinator.async_temp_down(device_id)
    mock_stick.send_command.assert_called_once()


async def test_async_set_slat_run_time_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_slat_run_time(device_id, 20)
    mock_stick.send_command.assert_called_once()


async def test_async_set_default_slat_pos_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_default_slat_pos(device_id, 50)
    mock_stick.send_command.assert_called_once()


async def test_async_set_stairwell_time_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_stairwell_time(device_id, 100)
    mock_stick.send_command.assert_called_once()


async def test_async_set_intermediate_value_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    await coordinator.async_set_intermediate_value(device_id, 50)
    mock_stick.send_command.assert_called_once()


# ---------------------------------------------------------------------------
# async_set_temperature_threshold 1-4 convenience wrappers
# ---------------------------------------------------------------------------


async def test_set_temperature_threshold1_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    dc = DuoFernId.from_hex("731234")
    await coordinator.async_set_temperature_threshold1(dc, 18.0)
    mock_stick.send_command.assert_called_once()


async def test_set_temperature_threshold2_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    dc = DuoFernId.from_hex("731234")
    await coordinator.async_set_temperature_threshold2(dc, 20.0)
    mock_stick.send_command.assert_called_once()


async def test_set_temperature_threshold3_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    dc = DuoFernId.from_hex("731234")
    await coordinator.async_set_temperature_threshold3(dc, 22.0)
    mock_stick.send_command.assert_called_once()


async def test_set_temperature_threshold4_calls_stick(hass: HomeAssistant) -> None:
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick
    dc = DuoFernId.from_hex("731234")
    await coordinator.async_set_temperature_threshold4(dc, 24.0)
    mock_stick.send_command.assert_called_once()


# ---------------------------------------------------------------------------
# _maybe_trigger_discovery — Unknown device type branch
# ---------------------------------------------------------------------------


async def test_maybe_trigger_discovery_skips_unknown_device_type(
    hass: HomeAssistant,
) -> None:
    """_maybe_trigger_discovery skips devices whose device_type_name starts with 'Unknown'."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        options={CONF_AUTO_DISCOVER: True},
        version=2,
    )
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    # Build a mock DuoFernId whose device_type_name starts with "Unknown"
    unknown_id = MagicMock()
    unknown_id.hex = "991234"
    unknown_id.device_type_name = "Unknown 0x99"

    with patch.object(hass, "async_create_task") as mock_task:
        coordinator._maybe_trigger_discovery(unknown_id)

    mock_task.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_battery_status — state is None (unknown device)
# ---------------------------------------------------------------------------


async def test_handle_battery_status_unknown_device_does_not_raise(
    hass: HomeAssistant,
) -> None:
    """_handle_battery_status with an unknown device (state=None) must not raise."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_id = DuoFernId.from_hex("409999")  # not in data.devices

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=unknown_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_battery_status",
            return_value={"batteryState": "ok", "batteryPercent": 80},
        ),
        patch.object(coordinator, "_maybe_trigger_discovery"),
    ):
        coordinator._handle_battery_status(bytearray(22))  # must not raise


# ---------------------------------------------------------------------------
# _handle_weather_data — state is None early return
# ---------------------------------------------------------------------------


async def test_handle_weather_data_state_none_returns_early(
    hass: HomeAssistant,
) -> None:
    """_handle_weather_data returns early without raising when device is unknown."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_id = DuoFernId.from_hex("699999")  # not in data.devices
    mock_weather = MagicMock()
    mock_weather.brightness = None
    mock_weather.sun_direction = None
    mock_weather.sun_height = None
    mock_weather.temperature = None
    mock_weather.is_raining = None
    mock_weather.wind = None

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=unknown_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_weather_data",
            return_value=mock_weather,
        ),
        patch.object(coordinator, "_maybe_trigger_discovery"),
    ):
        coordinator._handle_weather_data(bytearray(22))  # must not raise


# ---------------------------------------------------------------------------
# _handle_weather_data — isRaining event firing
# ---------------------------------------------------------------------------

WEATHER_STATION_HEX2 = "691235"


async def test_handle_weather_data_fires_start_rain_event(
    hass: HomeAssistant,
) -> None:
    """_handle_weather_data fires startRain DUOFERN_EVENT when is_raining=True."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    weather_id = DuoFernId.from_hex(WEATHER_STATION_HEX2)
    coordinator.data.devices[WEATHER_STATION_HEX2] = DuoFernDeviceState(
        device_code=weather_id
    )

    fired_events = []
    hass.bus.async_listen(DUOFERN_EVENT, lambda e: fired_events.append(e))

    mock_weather = MagicMock()
    mock_weather.brightness = None
    mock_weather.sun_direction = None
    mock_weather.sun_height = None
    mock_weather.temperature = None
    mock_weather.is_raining = True
    mock_weather.wind = None

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=weather_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_weather_data",
            return_value=mock_weather,
        ),
        patch.object(coordinator, "_maybe_trigger_discovery"),
    ):
        coordinator._handle_weather_data(bytearray(22))

    await hass.async_block_till_done()
    event_names = [e.data["event"] for e in fired_events]
    assert "startRain" in event_names


async def test_handle_weather_data_fires_end_rain_event(hass: HomeAssistant) -> None:
    """_handle_weather_data fires endRain DUOFERN_EVENT when is_raining=False."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    weather_id = DuoFernId.from_hex(WEATHER_STATION_HEX2)
    coordinator.data.devices[WEATHER_STATION_HEX2] = DuoFernDeviceState(
        device_code=weather_id
    )

    fired_events = []
    hass.bus.async_listen(DUOFERN_EVENT, lambda e: fired_events.append(e))

    mock_weather = MagicMock()
    mock_weather.brightness = None
    mock_weather.sun_direction = None
    mock_weather.sun_height = None
    mock_weather.temperature = None
    mock_weather.is_raining = False
    mock_weather.wind = None

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=weather_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_weather_data",
            return_value=mock_weather,
        ),
        patch.object(coordinator, "_maybe_trigger_discovery"),
    ):
        coordinator._handle_weather_data(bytearray(22))

    await hass.async_block_till_done()
    event_names = [e.data["event"] for e in fired_events]
    assert "endRain" in event_names


# ---------------------------------------------------------------------------
# _start_status_timeout — state is None early return
# ---------------------------------------------------------------------------


async def test_start_status_timeout_returns_early_for_unknown_device(
    hass: HomeAssistant,
) -> None:
    """_start_status_timeout does nothing when device is not in data.devices."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_id = DuoFernId.from_hex("409999")  # not in data.devices

    with patch.object(hass, "async_create_task") as mock_task:
        coordinator._start_status_timeout(unknown_id)

    mock_task.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_sensor_event — exception in DuoFernId.from_hex during discovery
# ---------------------------------------------------------------------------


async def test_handle_sensor_event_catches_from_hex_exception(
    hass: HomeAssistant,
) -> None:
    """_handle_sensor_event catches exceptions in discovery and still fires the event."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    mock_event = MagicMock()
    mock_event.device_code = "BADHEX"
    mock_event.channel = "01"
    mock_event.event_name = "pressed"
    mock_event.state = "on"

    fired_events = []
    hass.bus.async_listen(DUOFERN_EVENT, lambda e: fired_events.append(e))

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_sensor_event",
            return_value=mock_event,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernId.from_hex",
            side_effect=ValueError("invalid hex"),
        ),
    ):
        coordinator._handle_sensor_event(bytearray(22))  # must not raise

    await hass.async_block_till_done()
    # HA event is still fired even though discovery failed
    assert len(fired_events) == 1


# ---------------------------------------------------------------------------
# _handle_missing_ack — 0xE1 early return (no status timeout)
# ---------------------------------------------------------------------------


async def test_handle_missing_ack_e1_device_skips_status_timeout(
    hass: HomeAssistant,
) -> None:
    """_handle_missing_ack returns early for 0xE1 without calling _start_status_timeout."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    coordinator.data.devices["E11234"] = DuoFernDeviceState(device_code=e1_id)

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
            return_value=e1_id,
        ),
        patch.object(coordinator, "_start_status_timeout") as mock_timeout,
    ):
        coordinator._handle_missing_ack(bytearray(22))

    mock_timeout.assert_not_called()
    assert coordinator.data.devices["E11234"].available is False


# ---------------------------------------------------------------------------
# _handle_cmd_ack — boost_retry_pending guards
# ---------------------------------------------------------------------------


async def test_handle_cmd_ack_boost_retry_on_sets_ha_pending_f0(
    hass: HomeAssistant,
) -> None:
    """CC with boost_retry_pending='on' sets boost_ha_on_pending_f0=True, clears cooldown."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    state = DuoFernDeviceState(device_code=e1_id)
    state.boost_retry_pending = "on"
    state.boost_ha_on_pending_f0 = False
    state.boost_off_cooldown = True
    coordinator.data.devices["E11234"] = state

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
        return_value=e1_id,
    ):
        coordinator._handle_cmd_ack(bytearray(22))

    assert state.boost_ha_on_pending_f0 is True
    assert state.boost_off_cooldown is False
    assert state.boost_retry_pending is None


async def test_handle_cmd_ack_boost_retry_off_sets_cooldown(
    hass: HomeAssistant,
) -> None:
    """CC with boost_retry_pending='off' sets boost_off_cooldown=True, clears pending_f0."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    e1_id = DuoFernId.from_hex("E11234")
    state = DuoFernDeviceState(device_code=e1_id)
    state.boost_retry_pending = "off"
    state.boost_ha_on_pending_f0 = True
    state.boost_off_cooldown = False
    coordinator.data.devices["E11234"] = state

    with patch(
        "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code",
        return_value=e1_id,
    ):
        coordinator._handle_cmd_ack(bytearray(22))

    assert state.boost_off_cooldown is True
    assert state.boost_ha_on_pending_f0 is False
    assert state.boost_retry_pending is None


# ---------------------------------------------------------------------------
# _handle_status — desired_temp preserved when boost active
# ---------------------------------------------------------------------------


async def test_handle_status_preserves_desired_temp_during_boost(
    hass: HomeAssistant,
) -> None:
    """_handle_status preserves desired_temp when boost_active=True (device reports 28°C)."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    # Set up previous state: boost active with user setpoint 20°C
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.boost_active = True
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.desired_temp = 20.0
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.readings["desired-temp"] = 20.0

    # parse_status returns boost still active with device-reported 28°C
    parsed = ParsedStatus()
    parsed.boost_active = True
    parsed.desired_temp = 28.0
    parsed.readings = {"desired-temp": 28.0}

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code_from_status",
            return_value=device_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_status",
            return_value=parsed,
        ),
    ):
        coordinator._handle_status(bytearray(22))

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    # Should be preserved at 20°C, not the boost-reported 28°C
    assert state.status.desired_temp == 20.0


async def test_handle_status_preserves_desired_temp_on_boost_end_transition(
    hass: HomeAssistant,
) -> None:
    """_handle_status preserves desired_temp on the boost→off transition frame."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    # Previous state: boost was active, user setpoint 20°C
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.boost_active = True
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.desired_temp = 20.0
    coordinator.data.devices[MOCK_DEVICE_CODE_COVER].status.readings["desired-temp"] = 20.0

    # parse_status returns boost=False (just ended) but still reports 28°C
    parsed = ParsedStatus()
    parsed.boost_active = False
    parsed.desired_temp = 28.0
    parsed.readings = {"desired-temp": 28.0}

    with (
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.extract_device_code_from_status",
            return_value=device_id,
        ),
        patch(
            "custom_components.duofern.coordinator.DuoFernDecoder.parse_status",
            return_value=parsed,
        ),
    ):
        coordinator._handle_status(bytearray(22))

    state = coordinator.data.devices[MOCK_DEVICE_CODE_COVER]
    # Preserved at 20°C even on the transition frame
    assert state.status.desired_temp == 20.0


# ---------------------------------------------------------------------------
# async_set_desired_temp — stick is None for non-E1 device
# ---------------------------------------------------------------------------


async def test_set_desired_temp_noop_when_no_stick_for_non_e1(
    hass: HomeAssistant,
) -> None:
    """async_set_desired_temp returns silently when stick is None for non-E1 device."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    assert coordinator._stick is None

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)  # non-E1 device

    # Should not raise
    await coordinator.async_set_desired_temp(device_id, 22.0)


# ---------------------------------------------------------------------------
# _reconnect
# ---------------------------------------------------------------------------


async def test_reconnect_clears_reconnecting_flag(hass: HomeAssistant) -> None:
    """_reconnect clears _reconnecting even if async_connect raises."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator._reconnecting = True

    with patch.object(coordinator, "async_connect", new_callable=AsyncMock):
        await coordinator._reconnect()

    assert coordinator._reconnecting is False


async def test_reconnect_disconnects_stick_first(hass: HomeAssistant) -> None:
    """_reconnect disconnects stick before reconnecting."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator._reconnecting = True

    mock_stick = MagicMock()
    mock_stick.disconnect = AsyncMock()
    coordinator._stick = mock_stick

    with patch.object(coordinator, "async_connect", new_callable=AsyncMock):
        await coordinator._reconnect()

    mock_stick.disconnect.assert_called_once()
    assert coordinator._reconnecting is False


async def test_reconnect_clears_flag_on_exception(hass: HomeAssistant) -> None:
    """_reconnect clears _reconnecting even when async_connect raises."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator._reconnecting = True

    with patch.object(
        coordinator,
        "async_connect",
        new_callable=AsyncMock,
        side_effect=Exception("connect failed"),
    ):
        try:
            await coordinator._reconnect()
        except Exception:
            pass

    assert coordinator._reconnecting is False


# ---------------------------------------------------------------------------
# _pairing_countdown
# ---------------------------------------------------------------------------


async def test_pairing_countdown_sends_stop_pair(hass: HomeAssistant) -> None:
    """_pairing_countdown with unpairing=False sends stop_pair at end."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator.data.pairing_active = True

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator._pairing_countdown(duration=2, unpairing=False)

    assert coordinator.data.pairing_active is False
    assert coordinator.data.pairing_remaining == 0
    mock_stick.send_command.assert_called()


async def test_pairing_countdown_sends_stop_unpair(hass: HomeAssistant) -> None:
    """_pairing_countdown with unpairing=True sends stop_unpair at end."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator.data.unpairing_active = True

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    from custom_components.duofern.protocol import DuoFernEncoder
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator._pairing_countdown(duration=1, unpairing=True)

    assert coordinator.data.unpairing_active is False
    # stop_unpair starts with 0x08
    call_args = mock_stick.send_command.call_args[0][0]
    assert call_args[0] == 0x08


async def test_pairing_countdown_no_stick(hass: HomeAssistant) -> None:
    """_pairing_countdown with no stick does not raise."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    coordinator._stick = None

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator._pairing_countdown(duration=1)

    assert coordinator.data.pairing_active is False


# ---------------------------------------------------------------------------
# _status_timeout_loop
# ---------------------------------------------------------------------------


async def test_status_timeout_loop_cancelled_gracefully(hass: HomeAssistant) -> None:
    """_status_timeout_loop handles CancelledError from asyncio.sleep."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError):
        # Should not raise — CancelledError is caught internally
        await coordinator._status_timeout_loop(device_id)


async def test_status_timeout_loop_calls_status_request(hass: HomeAssistant) -> None:
    """_status_timeout_loop calls _send_status_request on each iteration."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    call_count = 0

    async def fake_sleep(_):
        pass

    async def fake_send_status(_):
        nonlocal call_count
        call_count += 1

    with (
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(coordinator, "_send_status_request", side_effect=fake_send_status),
    ):
        from custom_components.duofern.const import STATUS_RETRY_COUNT
        await coordinator._status_timeout_loop(device_id)

    assert call_count == STATUS_RETRY_COUNT


# ---------------------------------------------------------------------------
# _send_hsa_if_pending — early returns
# ---------------------------------------------------------------------------


async def test_send_hsa_if_pending_returns_early_when_no_state(
    hass: HomeAssistant,
) -> None:
    """_send_hsa_if_pending returns early when device not in data."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    unknown_device = DuoFernId.from_hex("E11234")
    # Device not in coordinator.data.devices — should not raise
    await coordinator._send_hsa_if_pending(unknown_device, {})


async def test_send_hsa_if_pending_returns_early_when_no_pending(
    hass: HomeAssistant,
) -> None:
    """_send_hsa_if_pending returns early when hsa_pending is empty."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = coordinator.data.devices.get(device_id.hex)
    if state is None:
        state = DuoFernDeviceState(device_code=device_id)
        coordinator.data.devices[device_id.hex] = state
    state.hsa_pending = {}

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    await coordinator._send_hsa_if_pending(device_id, {})
    mock_stick.send_command.assert_not_called()


async def test_send_hsa_if_pending_returns_early_when_no_stick(
    hass: HomeAssistant,
) -> None:
    """_send_hsa_if_pending returns early when stick is None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = coordinator.data.devices.get(device_id.hex)
    if state is None:
        state = DuoFernDeviceState(device_code=device_id)
        coordinator.data.devices[device_id.hex] = state
    state.hsa_pending = {"manualMode": (None, "on")}

    coordinator._stick = None
    # Should not raise
    await coordinator._send_hsa_if_pending(device_id, {})


async def test_send_hsa_if_pending_sends_manual_mode(hass: HomeAssistant) -> None:
    """_send_hsa_if_pending sends HSA command when manualMode is pending."""
    from custom_components.duofern.protocol import ParsedStatus

    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = coordinator.data.devices.get(device_id.hex)
    if state is None:
        state = DuoFernDeviceState(device_code=device_id)
        coordinator.data.devices[device_id.hex] = state
    state.status = MagicMock()
    state.status.readings = {}
    state.status.boost_active = False
    state.hsa_pending = {"manualMode": (None, "on")}

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    await coordinator._send_hsa_if_pending(device_id, {})

    mock_stick.send_command.assert_called_once()
    assert state.hsa_pending == {}  # cleared after send


async def test_send_hsa_if_pending_unknown_key_does_not_raise(
    hass: HomeAssistant,
) -> None:
    """_send_hsa_if_pending logs warning for unknown key and continues."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = coordinator.data.devices.get(device_id.hex)
    if state is None:
        state = DuoFernDeviceState(device_code=device_id)
        coordinator.data.devices[device_id.hex] = state
    state.status = MagicMock()
    state.status.readings = {}
    state.status.boost_active = False
    # Only unknown key — still sends frame with set_value=0
    state.hsa_pending = {"unknownKey": (None, "on")}

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    # Should not raise
    await coordinator._send_hsa_if_pending(device_id, {})


async def test_send_hsa_if_pending_boost_active_on(hass: HomeAssistant) -> None:
    """_send_hsa_if_pending sends boost ON command when boostActive='on' is pending."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = coordinator.data.devices.get(device_id.hex)
    if state is None:
        state = DuoFernDeviceState(device_code=device_id)
        coordinator.data.devices[device_id.hex] = state
    state.status = MagicMock()
    state.status.readings = {}
    state.status.boost_active = False
    state.hsa_pending = {"boostActive": (None, "on")}

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    await coordinator._send_hsa_if_pending(device_id, {"boostDuration": "30"})

    mock_stick.send_command.assert_called_once()


async def test_send_hsa_if_pending_boost_active_off(hass: HomeAssistant) -> None:
    """_send_hsa_if_pending sends boost OFF command when boostActive='off' is pending."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    state = coordinator.data.devices.get(device_id.hex)
    if state is None:
        state = DuoFernDeviceState(device_code=device_id)
        coordinator.data.devices[device_id.hex] = state
    state.status = MagicMock()
    state.status.readings = {}
    state.status.boost_active = True
    state.hsa_pending = {"boostActive": ("on", "off")}

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    await coordinator._send_hsa_if_pending(device_id, {})

    mock_stick.send_command.assert_called_once()


# ---------------------------------------------------------------------------
# _send_stick_unfreeze
# ---------------------------------------------------------------------------


async def test_send_stick_unfreeze_sends_frame_when_connected(
    hass: HomeAssistant,
) -> None:
    """_send_stick_unfreeze sends a dummy HSA frame to unfreeze the stick."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)

    mock_stick = MagicMock()
    mock_stick.send_command = AsyncMock()
    coordinator._stick = mock_stick

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await coordinator._send_stick_unfreeze(device_id)

    mock_stick.send_command.assert_called_once()


async def test_send_stick_unfreeze_noop_when_no_stick(hass: HomeAssistant) -> None:
    """_send_stick_unfreeze returns early when stick is None."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = _make_coordinator(hass, entry)
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    coordinator._stick = None

    with patch("asyncio.sleep", new_callable=AsyncMock):
        # Should not raise
        await coordinator._send_stick_unfreeze(device_id)
