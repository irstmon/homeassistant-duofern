"""Number platform for DuoFern slider/value configuration settings.

Exposes settings that are numeric sliders:
  sunPosition          0-100   (covers: all)
  ventilatingPosition  0-100   (covers: all)
  slatPosition         0-100   (covers with blindsMode=on)
  slatRunTime          0.1-5   (blinds, step 0.1 s)
  defaultSlatPos       0-100   (blinds)
  runningTime          2-255   (Troll) / 0-255 (Dimmer)
  stairwellTime        0-3200  (Switch/Dimmer, unit = 100ms)
  intermediateValue    0-100   (Dimmer)

All appear in entity_category=CONFIG (device card "Configuration" section).

From 30_DUOFERN.pm set definitions and %commands:
  sunPosition:slider,0,1,100  + invert=100
  ventilatingPosition:slider,0,1,100  + invert=100
  slatPosition:slider,0,1,100
  slatRunTime:slider,0.1,0.1,5
  defaultSlatPos:slider,0,1,100
  runningTime:slider,2,1,255 (Troll) / slider,0,1,255 (Dimmer)
  stairwellTime:slider,0,10,3200
  intermediateValue:slider,0,1,100
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import ALL_COVER_TYPES, DOMAIN, TROLL_COVER_TYPES
from .coordinator import DuoFernCoordinator, DuoFernDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuoFernNumberDescription(NumberEntityDescription):
    """Extends NumberEntityDescription with device type filter."""

    reading_key: str = ""
    device_types: frozenset[int] = frozenset()
    coordinator_method: str = ""
    # When set, only create this entity for the matching sub-channel.
    # None (default) → no restriction; existing descriptions are unaffected.
    # Used for 0x69 Umweltsensor to keep config numbers on "00" and actor
    # numbers on "01".
    channel_filter: str | None = None
    # Raw device value = UI value * value_scale. 1.0 (default) means the
    # reading and the command use the same unit as the UI.
    value_scale: float = 1.0


# ALL_COVER_TYPES and TROLL_COVER_TYPES are imported from const.py to avoid
# duplication with switch.py. Local aliases for readability within this module.
_ALL_COVERS = ALL_COVER_TYPES
_TROLL_TYPES = TROLL_COVER_TYPES
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
        native_min_value=0.1,
        native_max_value=5,
        native_step=0.1,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer",
        device_types=_BLINDS_TYPES,
        coordinator_method="async_set_slat_run_time",
        # Device value is 0-50 (30_DUOFERN.pm: slatRunTime min 0, max 50),
        # shown here as 0.1-5.0 s, so one raw step is 0.1 s.
        value_scale=10.0,
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
        native_min_value=2,
        native_max_value=255,
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
    # 0x65 (Bewegungsmelder) / 0x74 (Wandtaster 6fach 230V) channel "01":
    # same reading, but needs its own entry with channel_filter="01" since
    # the entry above serves channel-less device types (channel_filter=None
    # there means "no restriction" — mixing a channel-carrying type into it
    # would incorrectly apply to both of its channels). From 30_DUOFERN.pm:
    #   %setsSwitchActor includes "stairwellTime:slider,0,10,3200".
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
        device_types=frozenset({0x65, 0x74}),
        channel_filter="01",
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
        native_min_value=4,
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
        native_min_value=4,
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
        native_min_value=4,
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
        native_min_value=4,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-alert",
        device_types=frozenset({0x73}),
        coordinator_method="async_set_temperature_threshold4",
    ),
    # --- Umweltsensor channel "00": location config ---
    # These come from the getConfig register decode (reg7) and must only
    # appear on the "00" (weather station) sub-channel.
    DuoFernNumberDescription(
        key="latitude",
        translation_key="latitude",
        reading_key="latitude",
        name="Latitude",
        # Protocol limitation: the FHEM reference (%commandsHSA) defines
        # latitude as min=0, max=90. The DuoFern protocol encodes latitude
        # as a single unsigned byte (0-90), so southern hemisphere latitudes
        # (negative values) cannot be represented. This is a hardware/protocol
        # constraint, not a software choice.
        native_min_value=0,
        native_max_value=90,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:map-marker",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_latitude",
        channel_filter="00",
    ),
    DuoFernNumberDescription(
        key="longitude",
        translation_key="longitude",
        reading_key="longitude",
        name="Longitude",
        # Protocol limitation: the FHEM reference (%commandsHSA) defines
        # longitude as min=-90, max=90 with offset=256 for negative values
        # (i.e. -90 is stored as 256-90=166). The encoding uses a single byte,
        # so the valid range is capped at ±90°. Locations east of 90°E or west
        # of 90°W cannot be represented in this protocol. This is intentional
        # per the Rademacher protocol specification, not a bug.
        native_min_value=-90,
        native_max_value=90,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:map-marker",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_longitude",
        channel_filter="00",
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
        coordinator_method="async_set_umweltsensor_timezone",
        channel_filter="00",
    ),
    # --- Umweltsensor channel "01" (actor): position and running time ---
    # From 30_DUOFERN.pm %setsDefaultRollerShutter inherited by channel "01":
    #   sunPosition:slider,0,1,100 + ventilatingPosition:slider,0,1,100
    # Same commands as other format-23a covers (async_set_sun_position /
    # async_set_ventilating_position), addressed to the actor sub-device.
    DuoFernNumberDescription(
        key="sunPosition_umwelt01",
        translation_key="sun_position",
        reading_key="sunPosition",
        name="Sun Position",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:sun-angle",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_sun_position",
        channel_filter="01",
    ),
    DuoFernNumberDescription(
        key="ventilatingPosition_umwelt01",
        translation_key="ventilating_position",
        reading_key="ventilatingPosition",
        name="Ventilating Position",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:air-filter",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_ventilating_position",
        channel_filter="01",
    ),
    # --- Umweltsensor channel "01" (actor): running time ---
    # From 30_DUOFERN.pm %setsUmweltsensor01: runningTime:slider,0,1,100
    # Same command as Troll covers (async_set_running_time).
    DuoFernNumberDescription(
        key="runningTime_umwelt",
        translation_key="running_time_cover",
        reading_key="runningTime",
        name="Running Time",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="s",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-settings",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_running_time",
        channel_filter="01",
    ),
    # --- HSA: sending interval ---
    DuoFernNumberDescription(
        key="sendingInterval",
        translation_key="sending_interval",
        reading_key="sendingInterval",
        name="Sending Interval",
        native_min_value=2,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement="min",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-send",
        device_types=frozenset({0xE1}),
        coordinator_method="async_set_sending_interval",
    ),
    # --- HSA: boost duration ---
    DuoFernNumberDescription(
        key="boostDuration",
        translation_key="boost_duration",
        reading_key="boostDuration",
        name="Boost Duration",
        native_min_value=4,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement="min",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-outline",
        device_types=frozenset({0xE1}),
        coordinator_method="async_set_boost_duration",
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
                # channel_filter=None → no restriction (all existing descriptions).
                # channel_filter set → only create for the matching sub-channel.
                # Used for 0x69 Umweltsensor (channel "00" vs "01") and for
                # 0x65/0x74 (channel "01" actor only).
                if (
                    desc.channel_filter is None
                    or device_state.channel == desc.channel_filter
                ):
                    entities.append(
                        DuoFernNumber(coordinator, device_state, hex_code, desc)
                    )

    # Structured trigger GUI — Umweltsensor 0x69 channel "00".
    # Value sliders for whichever Grenzwert is currently selected per group.
    # See coordinator.py's "Structured per-Grenzwert GUI" section.
    for hex_code, device_state in coordinator.data.devices.items():
        if (
            device_state.device_code.device_type == 0x69
            and device_state.channel == "00"
        ):
            for desc in GRENZWERT_NUMBER_DESCRIPTIONS:
                entities.append(
                    DuoFernGrenzwertNumber(coordinator, device_state, hex_code, desc)
                )
            # Sonnenrichtung "Zielrichtung" moved to select.py — @geraldeberle1234
            # confirmed it only takes 14 fixed values (22.5°/45°/.../315°,
            # NOT a continuous range), so it belongs as a Select, not a
            # Number. See DuoFernSunDirectionAngleSelect in select.py.

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        ("number", e._attr_unique_id) for e in entities if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern number entities", len(entities))


class DuoFernNumber(CoordinatorEntity[DuoFernCoordinator], NumberEntity, RestoreEntity):
    """A DuoFern numeric configuration value as a NumberEntity (slider).

    The current value is read from device status readings.
    Setting a new value sends the corresponding command from %commands.
    Uses RestoreEntity so battery devices (e.g. 0xE1 Heizkörperantrieb)
    show their last known value immediately after an HA restart instead of
    displaying 'unknown' until the first status frame arrives.
    The restored value is display-only — it is never sent to the device.
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
        self._restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known value for display until first live frame arrives."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            try:
                self._restored_value = float(last_state.state)
            except (TypeError, ValueError):
                pass

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
        """Return current value from device status readings, with restored fallback."""
        state = self._device_state
        if state is not None:
            val = state.status.readings.get(self.entity_description.reading_key)
            if val is not None:
                try:
                    live = float(val) / self.entity_description.value_scale
                    self._restored_value = live  # keep in sync for next restart
                    return live
                except (TypeError, ValueError):
                    pass
        return self._restored_value

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the device.

        value is passed as float (not int) to preserve precision for entities
        with native_step=0.5 (temperature thresholds on the Raumthermostat 0x73).
        Coordinator methods that expect integer values (e.g. position 0-100)
        perform their own rounding/conversion internally.
        """
        method = getattr(self.coordinator, self.entity_description.coordinator_method)
        await method(
            self._device_code, float(value) * self.entity_description.value_scale
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Structured trigger GUI — Umweltsensor 0x69 channel "00"
# ---------------------------------------------------------------------------
#
# min/max/step source per field — see NOTES.md for full detail:
#   Wind, Temperatur, Dawn/Dusk-Helligkeit: exact from FHEM wCmds table
#   Sonne Helligkeit/Verzögerung: derived from encoding bit-width, NOT
#     confirmed against a real Homepilot slider endpoint — safe assumption,
#     @geraldeberle1234 asked to verify
#   Sonne "Ab Temperatur von": bit-width + consistent with @geraldeberle1234's screenshots
#   Sonnenrichtung Zielwinkel: safe assumption (continuous Number with the
#     22.5° step instead of a fixed option list) — @geraldeberle1234 asked whether 0°/
#     337.5° are valid Homepilot values or not; using Number here means this
#     doesn't need to be "right" up front, only the min/max needs revisiting
#     later if it turns out too narrow or too wide


@dataclass(frozen=True)
class DuoFernGrenzwertNumberDescription:
    """Describes one value slider for the currently selected Grenzwert.

    get_method: coordinator method name, called as get_method(device_code, slot),
      returns a tuple whose element at value_index is the current number.
    set_method: coordinator method name, called as
      set_method(device_code, slot, value: int).
    """

    key: str
    translation_key: str
    name: str
    icon: str
    group: str
    native_min_value: float
    native_max_value: float
    native_step: float
    native_unit_of_measurement: str
    get_method: str
    set_method: str
    value_index: int = 1


GRENZWERT_NUMBER_DESCRIPTIONS: tuple[DuoFernGrenzwertNumberDescription, ...] = (
    DuoFernGrenzwertNumberDescription(
        key="wind_grenzwert_value",
        translation_key="wind_grenzwert_value",
        name="Wind Target Value",
        icon="mdi:weather-windy",
        group="wind",
        native_min_value=1,
        native_max_value=31,
        native_step=1,
        native_unit_of_measurement="m/s",
        get_method="get_trigger_wind_slot",
        set_method="async_set_trigger_wind_slot_value",
    ),
    DuoFernGrenzwertNumberDescription(
        key="temperature_grenzwert_value",
        translation_key="temperature_grenzwert_value",
        name="Temperature Target Value",
        icon="mdi:thermometer",
        group="temperature",
        native_min_value=-40,
        native_max_value=80,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        get_method="get_trigger_temperature_slot",
        set_method="async_set_trigger_temperature_slot_value",
    ),
    DuoFernGrenzwertNumberDescription(
        key="dawn_grenzwert_value",
        translation_key="dawn_grenzwert_value",
        name="Dawn Brightness",
        icon="mdi:brightness-5",
        group="dawn",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="lx",
        get_method="get_trigger_dawn_slot",
        set_method="async_set_trigger_dawn_slot_value",
    ),
    DuoFernGrenzwertNumberDescription(
        key="dusk_grenzwert_value",
        translation_key="dusk_grenzwert_value",
        name="Dusk Brightness",
        icon="mdi:brightness-3",
        group="dusk",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="lx",
        get_method="get_trigger_dusk_slot",
        set_method="async_set_trigger_dusk_slot_value",
    ),
    DuoFernGrenzwertNumberDescription(
        key="sun_grenzwert_klux",
        translation_key="sun_grenzwert_klux",
        name="Sun Brightness",
        icon="mdi:brightness-6",
        group="sun",
        native_min_value=1,
        native_max_value=100,  # confirmed by @geraldeberle1234 against real Homepilot slider
        native_step=1,
        native_unit_of_measurement="klx",
        get_method="get_trigger_sun_slot",
        set_method="async_set_trigger_sun_slot_klux",
        value_index=1,
    ),
    DuoFernGrenzwertNumberDescription(
        key="sun_grenzwert_sun_minutes",
        translation_key="sun_grenzwert_sun_minutes",
        name="Sun Detection Delay",
        icon="mdi:timer-sand",
        group="sun",
        native_min_value=1,
        native_max_value=32,  # confirmed by @geraldeberle1234 against real Homepilot slider
        native_step=1,
        native_unit_of_measurement="min",
        get_method="get_trigger_sun_slot",
        set_method="async_set_trigger_sun_slot_sun_minutes",
        value_index=2,
    ),
    DuoFernGrenzwertNumberDescription(
        key="sun_grenzwert_shadow_minutes",
        translation_key="sun_grenzwert_shadow_minutes",
        name="Shadow Detection Delay",
        icon="mdi:timer-sand",
        group="sun",
        native_min_value=1,
        native_max_value=32,  # confirmed by @geraldeberle1234 against real Homepilot slider
        native_step=1,
        native_unit_of_measurement="min",
        get_method="get_trigger_sun_slot",
        set_method="async_set_trigger_sun_slot_shadow_minutes",
        value_index=3,
    ),
    DuoFernGrenzwertNumberDescription(
        key="sun_grenzwert_temp",
        translation_key="sun_grenzwert_temp",
        name="Sun Minimum Temperature",
        icon="mdi:thermometer",
        group="sun",
        native_min_value=-5,
        native_max_value=26,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        get_method="get_trigger_sun_slot",
        set_method="async_set_trigger_sun_slot_temp",
        value_index=5,
    ),
)


class DuoFernGrenzwertNumber(CoordinatorEntity[DuoFernCoordinator], NumberEntity):
    """Generic value slider for whichever Grenzwert is currently selected
    in its trigger group (see DuoFernGrenzwertSelector in select.py).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        description: DuoFernGrenzwertNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._desc = description
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{description.key}"
        # Deliberately NO explicit _attr_name — see DuoFernActiveGrenzwerteSensor
        # in sensor.py for why (setting both translation_key and name blocks
        # the translation lookup entirely). description.name is unused now,
        # kept on the dataclass only as documentation of the English default.
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def _slot(self) -> int:
        state = self._device_state
        return state.selected_grenzwert.get(self._desc.group, 1) if state else 1

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and self.coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        get_fn = getattr(self.coordinator, self._desc.get_method)
        result = get_fn(self._device_code, self._slot)
        return float(result[self._desc.value_index])

    async def async_set_native_value(self, value: float) -> None:
        set_fn = getattr(self.coordinator, self._desc.set_method)
        await set_fn(self._device_code, self._slot, int(round(value)))

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
