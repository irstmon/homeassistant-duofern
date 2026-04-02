"""Tests for DuoFern integration setup and teardown (__init__.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern import _async_update_listener, async_unload_entry
from custom_components.duofern.const import (
    CONF_AUTO_DISCOVER,
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from custom_components.duofern.coordinator import DuoFernCoordinator
from custom_components.duofern.protocol import DuoFernId

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


def _make_entry(**kwargs) -> MockConfigEntry:
    data = {**MOCK_ENTRY_DATA, **kwargs.pop("data", {})}
    options = {**MOCK_ENTRY_OPTIONS, **kwargs.pop("options", {})}
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data=data,
        options=options,
        version=2,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Successful setup
# ---------------------------------------------------------------------------


async def test_setup_entry_success(hass: HomeAssistant) -> None:
    """async_setup_entry succeeds when coordinator connects without error."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator,
            "async_request_all_status",
            new_callable=AsyncMock,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)

    assert result is True
    assert entry.state == ConfigEntryState.LOADED


async def test_setup_entry_stores_coordinator_as_runtime_data(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry stores the coordinator on entry.runtime_data."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    assert isinstance(entry.runtime_data, DuoFernCoordinator)


# ---------------------------------------------------------------------------
# Connection failure → ConfigEntryNotReady
# ---------------------------------------------------------------------------


async def test_setup_entry_raises_config_entry_not_ready(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry raises ConfigEntryNotReady when connection fails."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch.object(
        DuoFernCoordinator,
        "async_connect",
        new_callable=AsyncMock,
        side_effect=Exception("serial port not found"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state == ConfigEntryState.SETUP_RETRY


# ---------------------------------------------------------------------------
# Unload
# ---------------------------------------------------------------------------


async def test_unload_entry(hass: HomeAssistant) -> None:
    """async_unload_entry unloads all platforms and returns True."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await hass.config_entries.async_unload(entry.entry_id)

    assert result is True
    assert entry.state == ConfigEntryState.NOT_LOADED


# ---------------------------------------------------------------------------
# Service registration
# ---------------------------------------------------------------------------


async def test_service_registered_on_setup(hass: HomeAssistant) -> None:
    """pair_device_by_code service is registered after setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    assert hass.services.has_service(DOMAIN, "pair_device_by_code")


async def test_service_unregistered_on_unload(hass: HomeAssistant) -> None:
    """pair_device_by_code service is removed when the entry is unloaded."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    assert hass.services.has_service(DOMAIN, "pair_device_by_code")

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await hass.config_entries.async_unload(entry.entry_id)

    assert not hass.services.has_service(DOMAIN, "pair_device_by_code")


async def test_pair_service_calls_coordinator(hass: HomeAssistant) -> None:
    """Calling pair_device_by_code invokes coordinator.async_pair_device_by_code."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    mock_pair = AsyncMock()

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch.object(
            DuoFernCoordinator,
            "async_pair_device_by_code",
            new=mock_pair,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN,
            "pair_device_by_code",
            {"device_code": MOCK_DEVICE_CODE_COVER},
            blocking=True,
        )

    mock_pair.assert_called_once_with(MOCK_DEVICE_CODE_COVER)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


async def test_migrate_entry_v1_to_v2(hass: HomeAssistant) -> None:
    """Version 1 entries are migrated to version 2 by adding paired_devices."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            # No CONF_PAIRED_DEVICES — v1 format
        },
        version=1,
    )
    entry.add_to_hass(hass)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    assert entry.version == 2
    assert CONF_PAIRED_DEVICES in entry.data
    assert entry.data[CONF_PAIRED_DEVICES] == []


async def test_migrate_entry_future_version_fails(hass: HomeAssistant) -> None:
    """Entries with a future version cannot be migrated and fail setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        version=99,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state in (
        ConfigEntryState.MIGRATION_ERROR,
        ConfigEntryState.SETUP_ERROR,
    )


# ---------------------------------------------------------------------------
# _async_update_listener
# ---------------------------------------------------------------------------


async def test_async_update_listener_calls_reload(hass: HomeAssistant) -> None:
    """_async_update_listener calls hass.config_entries.async_reload with entry_id."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as mock_reload:
        await _async_update_listener(hass, entry)

    mock_reload.assert_called_once_with(entry.entry_id)


# ---------------------------------------------------------------------------
# async_unload_entry — platform unload failure
# ---------------------------------------------------------------------------


async def test_unload_entry_when_platforms_fail_to_unload(
    hass: HomeAssistant,
) -> None:
    """When async_unload_platforms returns False, coordinator is NOT disconnected."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    # Set up the entry so entry.runtime_data holds a real coordinator
    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch.object(DuoFernCoordinator, "register_on_new_device_paired"),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    coordinator = entry.runtime_data
    mock_disconnect = AsyncMock()
    coordinator.async_disconnect = mock_disconnect

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await async_unload_entry(hass, entry)

    assert result is False
    mock_disconnect.assert_not_called()


# ---------------------------------------------------------------------------
# _on_new_device_paired callback
# ---------------------------------------------------------------------------


def _setup_entry_and_capture_callback(hass, entry):
    """Helper context manager to set up an entry and capture the pairing callback."""
    # This is done via patch.object so we can capture what's passed to register
    return (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    )


async def test_on_new_device_paired_ignores_non_duofernid(
    hass: HomeAssistant,
) -> None:
    """_on_new_device_paired returns silently if device_code is not a DuoFernId."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    original_paired = list(entry.data.get(CONF_PAIRED_DEVICES, []))

    captured: list = []

    def _capture(cb):
        captured.append(cb)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch.object(
            DuoFernCoordinator, "register_on_new_device_paired", side_effect=_capture
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    assert captured, "register_on_new_device_paired was never called"
    callback = captured[0]

    # Call with a plain string — not a DuoFernId
    callback("not-a-duofernid")

    # Entry data must be unchanged
    assert entry.data[CONF_PAIRED_DEVICES] == original_paired


async def test_on_new_device_paired_ignores_already_paired_device(
    hass: HomeAssistant,
) -> None:
    """_on_new_device_paired returns silently if device_code is already in the list."""
    entry = _make_entry()  # MOCK_DEVICE_CODE_COVER = "406B2D" is already paired
    entry.add_to_hass(hass)

    captured: list = []

    def _capture(cb):
        captured.append(cb)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch.object(
            DuoFernCoordinator, "register_on_new_device_paired", side_effect=_capture
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    callback = captured[0]

    # Call with a DuoFernId whose hex matches the already-paired MOCK_DEVICE_CODE_COVER
    already_paired_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    callback(already_paired_id)

    # Count of cover device must still be exactly 1 (no duplicate)
    assert entry.data[CONF_PAIRED_DEVICES].count(MOCK_DEVICE_CODE_COVER) == 1


async def test_on_new_device_paired_new_device_updates_entry(
    hass: HomeAssistant,
) -> None:
    """_on_new_device_paired appends a new device hex to entry.data and schedules reload."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    captured: list = []

    def _capture(cb):
        captured.append(cb)

    with (
        patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock),
        patch.object(
            DuoFernCoordinator, "async_request_all_status", new_callable=AsyncMock
        ),
        patch.object(
            DuoFernCoordinator, "register_on_new_device_paired", side_effect=_capture
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)

    callback = captured[0]

    # A completely new device not in the paired list
    new_device_id = DuoFernId.from_hex("481234")  # Dimmaktor — not in MOCK_ENTRY_DATA

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as mock_reload:
        callback(new_device_id)
        # async_create_task is used, so wait for pending tasks
        await hass.async_block_till_done()

    # New device hex must be in the paired list
    assert "481234" in entry.data[CONF_PAIRED_DEVICES]
    # Reload was scheduled
    mock_reload.assert_called_once_with(entry.entry_id)
