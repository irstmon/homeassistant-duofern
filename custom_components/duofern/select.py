"""Select platform for DuoFern multi-option device settings.

Exposes settings that have discrete options (not on/off, not sliders):
  motorDeadTime:   off / short / long           (Troll, Rohrmotor Steuerung)
  windDirection:   up / down                    (Troll, RolloTube)
  rainDirection:   up / down                    (Troll, RolloTube)
  automaticClosing: off / 30 / 60 / ... / 240s  (SX5)
  openSpeed:       11 / 15 / 19 (seconds)       (SX5)
  actTempLimit:    1 / 2 / 3 / 4                (Raumthermostat)

All are placed in entity_category=CONFIG so they appear in the
"Configuration" section of the device card, not the main dashboard.

From 30_DUOFERN.pm %commands and set definitions:
  motorDeadTime:off,short,long
  windDirection:up,down  / rainDirection:up,down
  automaticClosing:off,30,60,90,120,150,180,210,240
  openSpeed:11,15,19
  actTempLimit:1,2,3,4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState
from .protocol import DuoFernId

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuoFernSelectDescription(SelectEntityDescription):
    """Extends SelectEntityDescription with device type filter and command."""

    reading_key: str = ""
    device_types: frozenset[int] = frozenset()
    # Async method name on coordinator, signature: (device_code, value)
    coordinator_method: str = ""


# All select entities keyed by (description.key)
SELECT_DESCRIPTIONS: tuple[DuoFernSelectDescription, ...] = (
    # --- Covers (Troll / RolloTube / Rohrmotor Steuerung) ---
    DuoFernSelectDescription(
        key="motorDeadTime",
        translation_key="motor_dead_time",
        reading_key="motorDeadTime",
        name="Motor Dead Time",
        options=["off", "short", "long"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-pause",
        device_types=frozenset({0x42, 0x47, 0x4B, 0x4C, 0x70}),
        coordinator_method="async_set_motor_dead_time",
    ),
    DuoFernSelectDescription(
        key="windDirection",
        translation_key="wind_direction",
        reading_key="windDirection",
        name="Wind Direction",
        options=["up", "down"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-down",
        device_types=frozenset({0x42, 0x47, 0x49, 0x4B, 0x4C, 0x70}),
        coordinator_method="async_set_wind_direction",
    ),
    DuoFernSelectDescription(
        key="rainDirection",
        translation_key="rain_direction",
        reading_key="rainDirection",
        name="Rain Direction",
        options=["up", "down"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-down",
        device_types=frozenset({0x42, 0x47, 0x49, 0x4B, 0x4C, 0x70}),
        coordinator_method="async_set_rain_direction",
    ),
    # --- SX5 ---
    DuoFernSelectDescription(
        key="automaticClosing",
        translation_key="automatic_closing",
        reading_key="automaticClosing",
        name="Automatic Closing",
        options=["off", "30", "60", "90", "120", "150", "180", "210", "240"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer",
        device_types=frozenset({0x4E}),
        coordinator_method="async_set_automatic_closing",
    ),
    DuoFernSelectDescription(
        key="openSpeed",
        translation_key="open_speed",
        reading_key="openSpeed",
        name="Open Speed (s)",
        options=["11", "15", "19"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:speedometer",
        device_types=frozenset({0x4E}),
        coordinator_method="async_set_open_speed",
    ),
    # --- Raumthermostat ---
    DuoFernSelectDescription(
        key="actTempLimit",
        translation_key="act_temp_limit",
        reading_key="actTempLimit",
        name="Active Temp Limit",
        options=["1", "2", "3", "4"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-check",
        device_types=frozenset({0x73}),
        coordinator_method="async_set_act_temp_limit",
    ),
    # --- Umweltsensor: transmit interval ---
    DuoFernSelectDescription(
        key="interval",
        translation_key="interval",
        reading_key="interval",
        name="Transmit Interval",
        options=[
            "off",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "15",
            "20",
            "30",
            "40",
            "50",
            "60",
            "70",
            "80",
            "90",
            "100",
        ],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-outline",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_interval",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern select entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernSelect] = []
    for hex_code, device_state in coordinator.data.devices.items():
        dev_type = device_state.device_code.device_type
        for desc in SELECT_DESCRIPTIONS:
            if dev_type in desc.device_types:
                entities.append(
                    DuoFernSelect(coordinator, device_state, hex_code, desc)
                )

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern select entities", len(entities))


class DuoFernSelect(CoordinatorEntity[DuoFernCoordinator], SelectEntity, RestoreEntity):
    """A DuoFern multi-option configuration setting as a SelectEntity.

    The current value is read from the device's status readings (as set by
    parse_status() in protocol.py). Changing the value sends the corresponding
    command from %commands in 30_DUOFERN.pm.

    Uses RestoreEntity so that after an HA restart the last known value is
    shown immediately instead of 'unknown', until the first live status frame
    arrives from the device.
    """

    entity_description: DuoFernSelectDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        description: DuoFernSelectDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{description.key}"
        self._attr_options = list(description.options)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})
        self._restored_option: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known option for display until first live frame arrives."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            self._restored_option = last_state.state

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        """Return True only if device is present AND last coordinator update succeeded.

        Without the last_update_success check, the select entity would appear
        available even when the serial connection is down — because device state
        objects remain in coordinator.data between reconnects.
        """
        if not self.coordinator.last_update_success:
            return False
        state = self._device_state
        return state is not None and state.available

    @property
    def current_option(self) -> str | None:
        """Return current option read from device status, with restored fallback."""
        state = self._device_state
        if state is not None:
            val = state.status.readings.get(self.entity_description.reading_key)
            if val is not None:
                live = str(val)
                self._restored_option = live  # keep in sync for next restart
                return live
        return self._restored_option

    async def async_select_option(self, option: str) -> None:
        """Send the selected option to the device."""
        method = getattr(self.coordinator, self.entity_description.coordinator_method)
        await method(self._device_code, option)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
