"""Number platform for DuoFern slider/value configuration settings.

Exposes settings that are numeric sliders:
  sunPosition          0-100   (covers: all)
  ventilatingPosition  0-100   (covers: all)
  slatPosition         0-100   (covers with blindsMode=on)
  slatRunTime          0-50    (blinds)
  defaultSlatPos       0-100   (blinds)
  runningTime          0-150   (Troll) / 0-255 (Dimmer)
  stairwellTime        0-3200  (Switch/Dimmer, unit = 100ms)
  intermediateValue    0-100   (Dimmer)

All appear in entity_category=CONFIG (device card "Configuration" section).

From 30_DUOFERN.pm set definitions and %commands:
  sunPosition:slider,0,1,100  + invert=100
  ventilatingPosition:slider,0,1,100  + invert=100
  slatPosition:slider,0,1,100
  slatRunTime:slider,0,1,50
  defaultSlatPos:slider,0,1,100
  runningTime:slider,0,1,150 (Troll) / slider,0,1,255 (Dimmer)
  stairwellTime:slider,0,10,3200
  intermediateValue:slider,0,1,100
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState
from .protocol import DuoFernId

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuoFernNumberDescription(NumberEntityDescription):
    """Extends NumberEntityDescription with device type filter."""

    reading_key: str = ""
    device_types: frozenset[int] = frozenset()
    coordinator_method: str = ""


# Cover device types (all covers)
_ALL_COVERS = frozenset({0x40, 0x41, 0x42, 0x47, 0x49, 0x4B, 0x4C, 0x4E, 0x61, 0x70})
# Troll / RolloTube types (have runningTime, windMode etc.)
_TROLL_TYPES = frozenset({0x42, 0x47, 0x49, 0x4B, 0x4C, 0x70})
# Blinds types only (slat entities — 0x42|4B|4C|70 per FHEM dispatch)
_BLINDS_TYPES = frozenset({0x42, 0x4B, 0x4C, 0x70})
# Running time for covers: setsTroll dispatch = 42|47|4B|4C|70, NOT 0x49
_RUNNING_TIME_COVER_TYPES = frozenset({0x42, 0x47, 0x4B, 0x4C, 0x70})


NUMBER_DESCRIPTIONS: tuple[DuoFernNumberDescription, ...] = (
    # --- All covers ---
    DuoFernNumberDescription(
        key="sunPosition",
        translation_key="sun_position",
        reading_key="sunPosition",
        name="Sun Position",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:sun-angle",
        device_types=_ALL_COVERS - frozenset({0x4E}),  # not SX5
        coordinator_method="async_set_sun_position",
    ),
    DuoFernNumberDescription(
        key="ventilatingPosition",
        translation_key="ventilating_position",
        reading_key="ventilatingPosition",
        name="Ventilating Position",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:air-filter",
        device_types=_ALL_COVERS - frozenset({0x4E}),
        coordinator_method="async_set_ventilating_position",
    ),
    # --- Blinds (Troll types when blindsMode=on) ---
    DuoFernNumberDescription(
        key="slatPosition",
        translation_key="slat_position",
        reading_key="slatPosition",
        name="Slat Position",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=_BLINDS_TYPES,
        coordinator_method="async_set_slat_position",
    ),
    DuoFernNumberDescription(
        key="slatRunTime",
        translation_key="slat_run_time",
        reading_key="slatRunTime",
        name="Slat Run Time",
        native_min_value=0,
        native_max_value=50,
        native_step=1,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer",
        device_types=_BLINDS_TYPES,
        coordinator_method="async_set_slat_run_time",
    ),
    DuoFernNumberDescription(
        key="defaultSlatPos",
        translation_key="default_slat_pos",
        reading_key="defaultSlatPos",
        name="Default Slat Position",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=_BLINDS_TYPES,
        coordinator_method="async_set_default_slat_pos",
    ),
    # --- Troll: running time ---
    DuoFernNumberDescription(
        key="runningTime_cover",
        translation_key="running_time_cover",
        reading_key="runningTime",
        name="Running Time",
        native_min_value=0,
        native_max_value=150,
        native_step=1,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-settings",
        device_types=_RUNNING_TIME_COVER_TYPES,
        coordinator_method="async_set_running_time",
    ),
    # --- Switch / Dimmer: stairwell time ---
    DuoFernNumberDescription(
        key="stairwellTime",
        translation_key="stairwell_time",
        reading_key="stairwellTime",
        name="Stairwell Time",
        native_min_value=0,
        native_max_value=3200,
        native_step=10,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:stairs",
        device_types=frozenset({0x43, 0x46, 0x48, 0x4A, 0x71}),
        coordinator_method="async_set_stairwell_time",
    ),
    # --- Dimmer: intermediate value + running time ---
    DuoFernNumberDescription(
        key="intermediateValue",
        translation_key="intermediate_value",
        reading_key="intermediateValue",
        name="Intermediate Value",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:brightness-6",
        device_types=frozenset({0x48, 0x4A}),
        coordinator_method="async_set_intermediate_value",
    ),
    DuoFernNumberDescription(
        key="runningTime_dimmer",
        translation_key="running_time_dimmer",
        reading_key="runningTime",
        name="Running Time",
        native_min_value=0,
        native_max_value=255,
        native_step=1,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-settings",
        device_types=frozenset({0x48, 0x4A}),
        coordinator_method="async_set_running_time",
    ),
    # --- Raumthermostat: temperature thresholds 1-4 ---
    DuoFernNumberDescription(
        key="temperatureThreshold1",
        translation_key="temp_threshold_1",
        reading_key="temperatureThreshold1",
        name="Temp Threshold 1",
        native_min_value=-40,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-alert",
        device_types=frozenset({0x73}),
        coordinator_method="async_set_temperature_threshold1",
    ),
    DuoFernNumberDescription(
        key="temperatureThreshold2",
        translation_key="temp_threshold_2",
        reading_key="temperatureThreshold2",
        name="Temp Threshold 2",
        native_min_value=-40,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-alert",
        device_types=frozenset({0x73}),
        coordinator_method="async_set_temperature_threshold2",
    ),
    DuoFernNumberDescription(
        key="temperatureThreshold3",
        translation_key="temp_threshold_3",
        reading_key="temperatureThreshold3",
        name="Temp Threshold 3",
        native_min_value=-40,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-alert",
        device_types=frozenset({0x73}),
        coordinator_method="async_set_temperature_threshold3",
    ),
    DuoFernNumberDescription(
        key="temperatureThreshold4",
        translation_key="temp_threshold_4",
        reading_key="temperatureThreshold4",
        name="Temp Threshold 4",
        native_min_value=-40,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-alert",
        device_types=frozenset({0x73}),
        coordinator_method="async_set_temperature_threshold4",
    ),
    # --- Umweltsensor 00: location config ---
    DuoFernNumberDescription(
        key="latitude",
        translation_key="latitude",
        reading_key="latitude",
        name="Latitude",
        native_min_value=0,
        native_max_value=90,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:map-marker",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_number",
    ),
    DuoFernNumberDescription(
        key="longitude",
        translation_key="longitude",
        reading_key="longitude",
        name="Longitude",
        native_min_value=-90,
        native_max_value=90,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:map-marker",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_number",
    ),
    DuoFernNumberDescription(
        key="timezone",
        translation_key="timezone",
        reading_key="timezone",
        name="Timezone Offset",
        native_min_value=0,
        native_max_value=23,
        native_step=1,
        native_unit_of_measurement="h",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-outline",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_number",
    ),
    # --- HSA: sending interval ---
    DuoFernNumberDescription(
        key="sendingInterval",
        translation_key="sending_interval",
        reading_key="sendingInterval",
        name="Sending Interval",
        native_min_value=1,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement="min",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-send",
        device_types=frozenset({0xE1}),
        coordinator_method="async_set_sending_interval",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern number entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernNumber] = []
    for hex_code, device_state in coordinator.data.devices.items():
        dev_type = device_state.device_code.device_type
        for desc in NUMBER_DESCRIPTIONS:
            if dev_type in desc.device_types:
                entities.append(
                    DuoFernNumber(coordinator, device_state, hex_code, desc)
                )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern number entities", len(entities))


class DuoFernNumber(CoordinatorEntity[DuoFernCoordinator], NumberEntity):
    """A DuoFern numeric configuration value as a NumberEntity (slider).

    The current value is read from device status readings.
    Setting a new value sends the corresponding command from %commands.
    """

    entity_description: DuoFernNumberDescription
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        description: DuoFernNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and state.available

    @property
    def native_value(self) -> float | None:
        """Return current value from device status readings."""
        state = self._device_state
        if state is None:
            return None
        val = state.status.readings.get(self.entity_description.reading_key)
        if val is None:
            return None
        try:
            return float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the device."""
        method = getattr(self.coordinator, self.entity_description.coordinator_method)
        await method(self._device_code, int(value))

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
