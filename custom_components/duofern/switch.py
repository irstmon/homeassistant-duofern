"""Switch platform for DuoFern switch actors and automation toggle switches.

Two types of switch entities are created:

1. Device Switch entities (main switches, no entity_category):
   Devices: 0x43 Universalaktor (2ch), 0x46 Steckdosenaktor, 0x71 Troll Lichtmodus
   These are the primary on/off control for the device.

2. Automation Toggle switches (entity_category=CONFIG):
   Created for ALL actuators (covers, switches, dimmers).
   Each automation flag from %commands in 30_DUOFERN.pm becomes its own
   Switch entity in the device's "Configuration" section:
     manualMode, timeAutomatic, dawnAutomatic, duskAutomatic, sunAutomatic,
     ventilatingMode, windAutomatic, rainAutomatic, windMode, rainMode,
     reversal, blindsMode, tiltInSunPos, tiltInVentPos, tiltAfterMoveLevel,
     tiltAfterStopDown, sunMode, stairwellFunction, intermediateMode,
     saveIntermediateOnStop, 10minuteAlarm, 2000cycleAlarm, backJump

   manualMode:
     When turned ON — the device suspends ALL its own automations internally.
     No HA involvement needed; the device handles this completely.
     When turned OFF — the device re-enables its previously active automations.
     From 30_DUOFERN.pm %commands:
       manualMode => {on => "080600FD000000000000", off => "080600FE000000000000"}

From 30_DUOFERN.pm:
  %sets = (%setsSwitchActor, %setsPair)      if ^43....(01|02)
  %sets = (%setsBasic, %setsSwitchActor)     if ^(46|71)....
  All on/off automation flags use the FD=on / FE=off byte pattern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState
from .protocol import DuoFernId

_LOGGER = logging.getLogger(__name__)

# Device type sets — used by both DuoFernSwitch and automation switches
_ALL_COVERS = frozenset({0x40, 0x41, 0x42, 0x47, 0x49, 0x4B, 0x4C, 0x4E, 0x61, 0x70})
_TROLL_TYPES = frozenset({0x42, 0x47, 0x49, 0x4B, 0x4C, 0x70})
_SWITCH_TYPES = frozenset({0x43, 0x46, 0x71})
_DIMMER_TYPES = frozenset({0x48, 0x4A})
_ALL_ACTUATORS = _ALL_COVERS | _SWITCH_TYPES | _DIMMER_TYPES


# ===========================================================================
# Automation toggle switch descriptions
# ===========================================================================


@dataclass(frozen=True)
class DuoFernAutomationSwitchDescription(SwitchEntityDescription):
    """Describes an on/off automation toggle switch (CONFIG category)."""

    reading_key: str = ""
    automation_name: str = ""
    device_types: frozenset[int] = frozenset()


AUTOMATION_SWITCH_DESCRIPTIONS: tuple[DuoFernAutomationSwitchDescription, ...] = (
    DuoFernAutomationSwitchDescription(
        key="manualMode",
        reading_key="manualMode",
        automation_name="manualMode",
        translation_key="manual_mode",
        name="Manual Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:account-cog",
        device_types=_ALL_ACTUATORS | frozenset({0xE1}),
    ),
    DuoFernAutomationSwitchDescription(
        key="timeAutomatic",
        reading_key="timeAutomatic",
        automation_name="timeAutomatic",
        translation_key="time_automatic",
        name="Time Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:clock-check",
        device_types=_ALL_ACTUATORS | frozenset({0xE1}),
    ),
    DuoFernAutomationSwitchDescription(
        key="dawnAutomatic",
        reading_key="dawnAutomatic",
        automation_name="dawnAutomatic",
        translation_key="dawn_automatic",
        name="Dawn Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-sunset-up",
        device_types=_ALL_ACTUATORS - frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="duskAutomatic",
        reading_key="duskAutomatic",
        automation_name="duskAutomatic",
        translation_key="dusk_automatic",
        name="Dusk Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-sunset-down",
        device_types=_ALL_ACTUATORS - frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="sunAutomatic",
        reading_key="sunAutomatic",
        automation_name="sunAutomatic",
        translation_key="sun_automatic",
        name="Sun Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:white-balance-sunny",
        device_types=_ALL_ACTUATORS - frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="sunMode",
        reading_key="sunMode",
        automation_name="sunMode",
        translation_key="sun_mode",
        name="Sun Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:sun-thermometer",
        device_types=_ALL_ACTUATORS - frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="ventilatingMode",
        reading_key="ventilatingMode",
        automation_name="ventilatingMode",
        translation_key="ventilating_mode",
        name="Ventilating Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:air-filter",
        device_types=_ALL_COVERS - frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="windAutomatic",
        reading_key="windAutomatic",
        automation_name="windAutomatic",
        translation_key="wind_automatic",
        name="Wind Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-windy",
        device_types=_TROLL_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="rainAutomatic",
        reading_key="rainAutomatic",
        automation_name="rainAutomatic",
        translation_key="rain_automatic",
        name="Rain Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-rainy",
        device_types=_TROLL_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="windMode",
        reading_key="windMode",
        automation_name="windMode",
        translation_key="wind_mode",
        name="Wind Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-windy",
        device_types=_TROLL_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="rainMode",
        reading_key="rainMode",
        automation_name="rainMode",
        translation_key="rain_mode",
        name="Rain Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-rainy",
        device_types=_TROLL_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="reversal",
        reading_key="reversal",
        automation_name="reversal",
        translation_key="reversal",
        name="Reversal",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:swap-vertical",
        device_types=_TROLL_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="blindsMode",
        reading_key="blindsMode",
        automation_name="blindsMode",
        translation_key="blinds_mode",
        name="Blinds Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=frozenset({0x42, 0x4B, 0x4C, 0x70}),
    ),
    DuoFernAutomationSwitchDescription(
        key="tiltInSunPos",
        reading_key="tiltInSunPos",
        automation_name="tiltInSunPos",
        translation_key="tilt_in_sun_pos",
        name="Tilt In Sun Position",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=frozenset({0x42, 0x4B, 0x4C, 0x70}),
    ),
    DuoFernAutomationSwitchDescription(
        key="tiltInVentPos",
        reading_key="tiltInVentPos",
        automation_name="tiltInVentPos",
        translation_key="tilt_in_vent_pos",
        name="Tilt In Vent Position",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=frozenset({0x42, 0x4B, 0x4C, 0x70}),
    ),
    DuoFernAutomationSwitchDescription(
        key="tiltAfterMoveLevel",
        reading_key="tiltAfterMoveLevel",
        automation_name="tiltAfterMoveLevel",
        translation_key="tilt_after_move_level",
        name="Tilt After Move Level",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=frozenset({0x42, 0x4B, 0x4C, 0x70}),
    ),
    DuoFernAutomationSwitchDescription(
        key="tiltAfterStopDown",
        reading_key="tiltAfterStopDown",
        automation_name="tiltAfterStopDown",
        translation_key="tilt_after_stop_down",
        name="Tilt After Stop Down",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:blinds",
        device_types=frozenset({0x42, 0x4B, 0x4C, 0x70}),
    ),
    DuoFernAutomationSwitchDescription(
        key="modeChange",
        reading_key="modeChange",
        automation_name="modeChange",
        translation_key="mode_change",
        name="Mode Change",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:toggle-switch",
        device_types=frozenset({0x43, 0x46, 0x71, 0x48, 0x4A}),
    ),
    DuoFernAutomationSwitchDescription(
        key="stairwellFunction",
        reading_key="stairwellFunction",
        automation_name="stairwellFunction",
        translation_key="stairwell_function",
        name="Stairwell Function",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:stairs",
        device_types=_SWITCH_TYPES | _DIMMER_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="intermediateMode",
        reading_key="intermediateMode",
        automation_name="intermediateMode",
        translation_key="intermediate_mode",
        name="Intermediate Mode",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:brightness-6",
        device_types=_DIMMER_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="saveIntermediateOnStop",
        reading_key="saveIntermediateOnStop",
        automation_name="saveIntermediateOnStop",
        translation_key="save_intermediate_on_stop",
        name="Save Intermediate On Stop",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:content-save",
        device_types=_DIMMER_TYPES,
    ),
    DuoFernAutomationSwitchDescription(
        key="10minuteAlarm",
        reading_key="10minuteAlarm",
        automation_name="10minuteAlarm",
        translation_key="ten_minute_alarm",
        name="10 Minute Alarm",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:alarm",
        device_types=frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="2000cycleAlarm",
        reading_key="2000cycleAlarm",
        automation_name="2000cycleAlarm",
        translation_key="two_thousand_cycle_alarm",
        name="2000 Cycle Alarm",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:counter",
        device_types=frozenset({0x4E}),
    ),
    DuoFernAutomationSwitchDescription(
        key="backJump",
        reading_key="backJump",
        automation_name="backJump",
        translation_key="back_jump",
        name="Back Jump",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:undo",
        device_types=frozenset({0x4E}),
    ),
    # Umweltsensor: DCF, triggerRain
    DuoFernAutomationSwitchDescription(
        key="DCF",
        reading_key="DCF",
        automation_name="DCF",
        translation_key="dcf",
        name="DCF Time Sync",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:antenna",
        device_types=frozenset({0x69}),
    ),
    DuoFernAutomationSwitchDescription(
        key="triggerRain",
        reading_key="triggerRain",
        automation_name="triggerRain",
        translation_key="trigger_rain",
        name="Trigger Rain",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:weather-rainy",
        device_types=frozenset({0x69}),
    ),
    # windowContact for HSA (Heizkörperantrieb)
    DuoFernAutomationSwitchDescription(
        key="windowContact",
        reading_key="windowContact",
        automation_name="windowContact",
        translation_key="window_contact_automatic",
        name="Window Contact Automatic",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:window-open",
        device_types=frozenset({0xE1}),
    ),
)

# Readings only shown as attributes — not as separate switch entities
_SKIP_AS_ATTRIBUTE = {"level"}


# ===========================================================================
# async_setup_entry
# ===========================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern switch and automation-toggle entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[SwitchEntity] = []

    for hex_code, device_state in coordinator.data.devices.items():
        dev_type = device_state.device_code.device_type

        # 1. Device on/off switches
        if device_state.device_code.is_switch:
            entities.append(
                DuoFernSwitch(
                    coordinator=coordinator,
                    device_state=device_state,
                    hex_code=hex_code,
                    entry_id=entry.entry_id,
                )
            )
            _LOGGER.debug("Adding switch entity for device %s", hex_code)

        # 2. Automation toggle switches (CONFIG) for actuators only
        if (
            not device_state.device_code.is_remote
            and not device_state.device_code.is_env_sensor
        ):
            for desc in AUTOMATION_SWITCH_DESCRIPTIONS:
                if dev_type in desc.device_types:
                    entities.append(
                        DuoFernAutomationSwitch(
                            coordinator, device_state, hex_code, desc
                        )
                    )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern switch entities total", len(entities))


# ===========================================================================
# Device Switch Entity (on/off control)
# ===========================================================================


class DuoFernSwitch(CoordinatorEntity[DuoFernCoordinator], SwitchEntity):
    """A DuoFern switch actor channel as a HA SwitchEntity.

    For the Universalaktor (0x43), hex_code is the 8-char channel code.
    For single-channel devices, hex_code is the 6-char device code.

    From 30_DUOFERN.pm %setsSwitchActor:
      on => "0E03tt00000000000000"
      off => "0E02tt00000000000000"
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._channel = device_state.channel
        self._attr_unique_id = f"{DOMAIN}_{hex_code}"
        self._channel_int = int(self._channel, 16) if self._channel else 1

        if self._device_code.device_type in (0x43, 0x46):
            self._attr_device_class = SwitchDeviceClass.OUTLET
        else:
            self._attr_device_class = SwitchDeviceClass.SWITCH

        self._channel_label = (
            f" Kanal {self._channel}"
            if self._channel and self._device_code.has_channels
            else ""
        )

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        state = self._device_state
        return (
            state is not None
            and state.available
            and self.coordinator.last_update_success
        )

    @property
    def is_on(self) -> bool | None:
        state = self._device_state
        if state is None or state.status.level is None:
            return None
        return state.status.level > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._device_state
        if state is None:
            return {}
        attrs: dict[str, Any] = {
            k: v
            for k, v in state.status.readings.items()
            if k not in _SKIP_AS_ATTRIBUTE
        }
        if state.status.version:
            attrs["firmware_version"] = state.status.version
        if state.battery_state is not None:
            attrs["battery_state"] = state.battery_state
        if state.battery_percent is not None:
            attrs["battery_level"] = state.battery_percent
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_switch_on(
            self._device_code, channel=self._channel_int
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_switch_off(
            self._device_code, channel=self._channel_int
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=(
                f"DuoFern {self._device_code.device_type_name}"
                f" ({self._device_code.hex}){self._channel_label}"
            ),
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=self._hex_code,
            sw_version=state.status.version if state else None,
            via_device=(DOMAIN, self.coordinator.system_code.hex),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        state = self._device_state
        if state and state.status.version:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
            if device and device.sw_version != state.status.version:
                device_reg.async_update_device(
                    device.id, sw_version=state.status.version
                )
        self.async_write_ha_state()


# ===========================================================================
# Automation Toggle Switch Entity (CONFIG category)
# ===========================================================================


class DuoFernAutomationSwitch(CoordinatorEntity[DuoFernCoordinator], SwitchEntity):
    """A DuoFern automation flag as an on/off SwitchEntity (CONFIG category).

    Appears in the device card's "Configuration" section — separate from
    the main controls. The current state is read from device status readings.

    manualMode semantics (from 30_DUOFERN.pm):
      When manualMode=on is sent to the device, the device ITSELF suspends
      all its automations internally. HA does not need to track or re-enable
      them. When manualMode=off is sent, the device re-enables its known
      previously-active automations automatically.

      From 30_DUOFERN.pm %commands:
        manualMode => {on => "080600FD000000000000", off => "080600FE000000000000"}
    """

    entity_description: DuoFernAutomationSwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        description: DuoFernAutomationSwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{description.key}_auto"
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
    def is_on(self) -> bool | None:
        """Return True if the automation flag is active ('on').

        From 30_DUOFERN.pm: automation readings stored as 'on'/'off' strings
        after the onOff mapping in parse_status().
        """
        state = self._device_state
        if state is None:
            return None
        val = state.status.readings.get(self.entity_description.reading_key)
        if val is None:
            return None
        return str(val).lower() in ("on", "1", "true")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable this automation flag (send FD command to device).

        windowContact and modeChange use dedicated coordinator methods.
        All other automations use the standard FD/FE byte pattern.
        """
        name = self.entity_description.automation_name
        if name == "windowContact":
            await self.coordinator.async_set_window_contact(self._device_code, True)
        elif name == "modeChange":
            await self.coordinator.async_set_mode_change(self._device_code)
        else:
            await self.coordinator.async_set_automation(self._device_code, name, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable this automation flag (send FE command to device).

        windowContact and modeChange use dedicated coordinator methods.
        """
        name = self.entity_description.automation_name
        if name == "windowContact":
            await self.coordinator.async_set_window_contact(self._device_code, False)
        elif name == "modeChange":
            await self.coordinator.async_set_mode_change(self._device_code)  # toggle
        else:
            await self.coordinator.async_set_automation(self._device_code, name, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        state = self._device_state
        if state and state.status.version:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
            if device and device.sw_version != state.status.version:
                device_reg.async_update_device(
                    device.id, sw_version=state.status.version
                )
        self.async_write_ha_state()
