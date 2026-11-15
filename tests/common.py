"""Helpers for tests that run the integration in a Home Assistant test instance.

The stick is replaced by FakeStick: frames the integration sends are recorded,
frames "from the radio" are fed into the coordinator with feed().
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern import coordinator as coordinator_module
from custom_components.duofern.const import (
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DEVICE_TYPES,
    DOMAIN,
)
from custom_components.duofern.coordinator import DuoFernCoordinator

SYSTEM_CODE = "6F1A2B"

# Raumthermostat (0x73) and Heizkörperantrieb (0xE1) create climate entities.
# These use the native_* temperature API of Home Assistant 2026.11; the test
# plugin still installs an older Home Assistant, so they are left out of the
# tests that set up entities until the plugin supports 2026.11.
CLIMATE_TYPES = (0x73, 0xE1)

ALL_TYPES = sorted(t for t in DEVICE_TYPES if t not in CLIMATE_TYPES)
ALL_DEVICES = [f"{t:02X}A1B2" for t in ALL_TYPES]


class FakeStick:
    """Stand-in for DuoFernStick."""

    instances: list[FakeStick] = []

    def __init__(
        self,
        port: Any = None,
        system_code: Any = None,
        paired_devices: Any = None,
        message_callback: Any = None,
        error_callback: Any = None,
    ) -> None:
        self.sent: list[str] = []
        self.message_callback = message_callback
        self.closed = False
        FakeStick.instances.append(self)

    async def connect(self) -> None:
        return

    async def disconnect(self) -> None:
        self.closed = True

    async def send_command(self, frame: bytearray) -> None:
        self.sent.append(bytes(frame).hex().upper())


def make_entry(hass: HomeAssistant, devices: list[str]) -> MockConfigEntry:
    """Create a config entry with the given paired devices and add it to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SYSTEM_CODE,
        version=2,
        data={
            CONF_SERIAL_PORT: "/dev/ttyUSB0",
            CONF_DEVICE_CODE: SYSTEM_CODE,
            CONF_PAIRED_DEVICES: list(devices),
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@asynccontextmanager
async def fake_stick(
    stick_class: type[FakeStick] = FakeStick,
    startup_status_timeout: float = 36000,
    status_timeout: float = 36000,
) -> AsyncGenerator[type[FakeStick]]:
    """Patch the stick and the two poll timeouts for the duration of a test."""
    FakeStick.instances.clear()
    with (
        patch.object(coordinator_module, "DuoFernStick", stick_class),
        patch.object(
            coordinator_module, "STARTUP_STATUS_TIMEOUT", startup_status_timeout
        ),
        patch.object(coordinator_module, "STATUS_TIMEOUT", status_timeout),
    ):
        yield stick_class


async def setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> DuoFernCoordinator:
    """Set the entry up and return its coordinator."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def unload_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Cancel running status polls and unload the entry."""
    for state in entry.runtime_data.data.devices.values():
        task = state.status_timeout_task
        if task and not task.done():
            task.cancel()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def feed(coordinator: DuoFernCoordinator, frame_hex: str) -> None:
    """Hand a frame to the coordinator as if the stick had received it."""
    coordinator._on_message(bytearray.fromhex(frame_hex))


def stick_ack(kind_hex: str, device_code: str) -> str:
    """Build a stick response frame (810003CC, 810108AA, ...) for a device.

    The device code sits at bytes 18-20, as in real frames.
    """
    return (
        bytes.fromhex(kind_hex) + bytes(14) + bytes.fromhex(device_code) + b"\x00"
    ).hex()


def entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    """Resolve an entity id from domain and unique id."""
    found = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert found, f"no {domain} entity with unique_id {unique_id}"
    return found


async def enable_all_entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Enable entities that are disabled by default and reload the entry."""
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.disabled_by is not None:
            registry.async_update_entity(reg_entry.entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
