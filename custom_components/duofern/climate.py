"""Climate platform for DuoFern thermostats.

Covers the following device types:
  0x73  Raumthermostat      (format "27") — wall thermostat, read/write
  0xE1  Heizkörperantrieb   (format "29") — radiator valve, read/write

From 30_DUOFERN.pm:
  %sets = (%setsBasic, %setsThermostat) if ($hash->{CODE} =~ /^73..../);
  %sets = (%setsHSA)                    if ($hash->{CODE} =~ /^E1..../);

Raumthermostat (0x73) format "27" readings:
  measured-temp, measured-temp2, desired-temp,
  temperatureThreshold1-4, actTempLimit, output,
  manualOverride, timeAutomatic, manualMode

Heizkörperantrieb (0xE1) format "29" readings:
  desired-temp, measured-temp, manualMode, timeAutomatic,
  sendingInterval, batteryPercent, valvePosition, forceResponse

  The HSA has a special device-initiated protocol: on receipt of a status
  frame, pending set-values are encoded back. FHEM stores these in
  hash->{helper}{HSAold} and sends them with duoSetHSA when the next
  status frame arrives. The coordinator does the same: changes are queued
  in DuoFernDeviceState.hsa_pending and sent by _send_hsa_if_pending()
  when the device checks in with its next status frame.

  From 30_DUOFERN.pm:
    #Heizkörperantrieb
    if ($code =~ m/^E1..../) { ... $setValue |= ($rawValue << bitFrom) ... }

All automation readings are exposed as extra_state_attributes.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import (
    ExtraStoredData,
    RestoredExtraData,
    RestoreEntity,
)

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState
from .entity import DuoFernEntity, device_description

_LOGGER = logging.getLogger(__name__)

# Temperature range for Heizkörperantrieb (0xE1): 4.0 .. 28.0 in 0.5 steps.
# From 30_DUOFERN.pm $tempSetList.
TEMP_MIN = 4.0
TEMP_MAX_HSA = 28.0
# Temperature range for Raumthermostat (0x73): 4.0 .. 40.0 in 0.5 steps.
# The wall thermostat GUI and original Rademacher app show 4-40°C.
TEMP_MAX_THERMOSTAT = 40.0
TEMP_STEP = 0.5
# Setpoint used by "Heat" after "Off" when no setpoint from before "Off" is known.
TEMP_HEAT_DEFAULT = 20.0
# Key of the setpoint from before "Off" in the stored extra data.
_EXTRA_SETPOINT_BEFORE_OFF = "setpoint_before_off"

_SKIP_AS_ATTRIBUTE = {"desired-temp", "measured-temp", "measured-temp2"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern climate entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernClimate] = []
    for hex_code, device_state in coordinator.data.devices.items():
        if device_state.device_code.is_climate:
            entities.append(
                DuoFernClimate(
                    coordinator=coordinator,
                    device_state=device_state,
                    hex_code=hex_code,
                )
            )
            _LOGGER.debug("Adding climate entity for device %s", hex_code)

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        ("climate", e._attr_unique_id)
        for e in entities
        if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern climate entities", len(entities))


class DuoFernClimate(DuoFernEntity, ClimateEntity, RestoreEntity):
    """A DuoFern thermostat or radiator valve as a HA ClimateEntity.

    Supports HEAT and OFF modes:
      HEAT: device is controlling temperature (normal operation). A setpoint
            of 4.0°C is a normal setpoint in this mode.
      OFF:  only after "Off" was selected in HA. Sends desired-temp 4.0°C
            (minimum); manualMode is not changed. The status frame cannot
            tell "Off" from a setpoint of 4.0°C, so the mode is kept by the
            entity (restored after a restart). It ends with "Heat", any new
            temperature from HA, or a setpoint above 4.0°C reported by the
            device (dial, Homepilot).

    From 30_DUOFERN.pm %setsThermostat:
      desired-temp:$tempSetList  — 4.0-28.0°C (0xE1), 4.0-40.0°C (0x73)
      manualMode:on,off          — bypass timer program
      timeAutomatic:on,off       — enable/disable timer
      temperatureThreshold1-4    — zone thresholds (4.0-40.0°C)
      actTempLimit:1,2,3,4       — active threshold selection
    """

    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = TEMP_MIN

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}"
        # 0x73 Raumthermostat: 4-40°C; 0xE1 Heizkörperantrieb: 4-28°C (FHEM $tempSetList)
        self._attr_max_temp = (
            TEMP_MAX_THERMOSTAT
            if self._device_code.device_type == 0x73
            else TEMP_MAX_HSA
        )
        # Restored values — shown in GUI until first live frame arrives.
        # Never sent to the device; overwritten by coordinator updates.
        self._restored_desired_temp: float | None = None
        self._restored_measured_temp: float | None = None
        # "Off" selected in HA (see class docstring) and the setpoint that was
        # active before, restored by "Heat".
        self._hvac_off: bool = False
        self._setpoint_before_off: float | None = None
        # True once the device state shows the minimum setpoint after "Off"
        # was selected. Only then a higher setpoint ends "Off"; before that
        # the state still carries the setpoint from before the command (0x73
        # has no optimistic update, see coordinator.async_set_desired_temp).
        self._off_confirmed: bool = False

    async def async_added_to_hass(self) -> None:
        """Restore last known temperatures so the GUI shows values immediately.

        Battery devices (0xE1) can take minutes before sending their first
        status frame. Without restore the climate card shows 'unknown' until
        then. The restored values are display-only — nothing is ever sent to
        the device based on them.
        """
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        self._hvac_off = last_state.state == HVACMode.OFF
        self._off_confirmed = self._hvac_off
        if (extra := await self.async_get_last_extra_data()) is not None:
            try:
                if (v := extra.as_dict().get(_EXTRA_SETPOINT_BEFORE_OFF)) is not None:
                    self._setpoint_before_off = float(v)
            except (TypeError, ValueError):
                pass
        attrs = last_state.attributes
        try:
            if (v := attrs.get("temperature")) is not None:
                self._restored_desired_temp = float(v)
        except (TypeError, ValueError):
            pass
        try:
            if (v := attrs.get("current_temperature")) is not None:
                self._restored_measured_temp = float(v)
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
        if state is None:
            return False
        return state.available and self.coordinator.last_update_success

    @property
    def native_current_temperature(self) -> float | None:
        """Return current measured temperature.

        Falls back to the last restored value until the first live frame
        arrives (relevant for battery devices that report infrequently).
        """
        state = self._device_state
        if state is not None and state.status.measured_temp is not None:
            # Keep restored value in sync for next restart
            self._restored_measured_temp = state.status.measured_temp
            return state.status.measured_temp
        return self._restored_measured_temp

    @property
    def native_target_temperature(self) -> float | None:
        """Return the desired/set temperature.

        Falls back to the last restored value until the first live frame
        arrives (relevant for battery devices that report infrequently).
        """
        state = self._device_state
        if state is not None and state.status.desired_temp is not None:
            # Keep restored value in sync for next restart
            self._restored_desired_temp = state.status.desired_temp
            return state.status.desired_temp
        return self._restored_desired_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode.

        OFF only after "Off" was selected in HA (see class docstring). A
        setpoint of 4.0°C reported by the device is HEAT.
        """
        return HVACMode.OFF if self._hvac_off else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current action derived from the "output" reading.

        Only format 27 (0x73) reports "output"; 0xE1 returns None.
        """
        state = self._device_state
        if state is None:
            return None
        output = state.status.readings.get("output")
        if output is None:
            return None
        if output == "on":
            return HVACAction.HEATING
        return HVACAction.OFF if self.hvac_mode == HVACMode.OFF else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all thermostat/HSA readings as extra state attributes.

        Raumthermostat: temperatureThreshold1-4, actTempLimit, output,
          manualOverride, timeAutomatic, manualMode, measured-temp2.
        Heizkörperantrieb: valvePosition, sendingInterval, batteryPercent,
          manualMode, timeAutomatic, forceResponse.
        """
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

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the desired temperature.

        0xE1: the change is queued and sent with duoSetHSA when the device
        sends its next status frame (see coordinator.async_set_desired_temp).
        0x73: sent immediately with the desired-temp command.
        A new temperature ends "Off". If the call also asks for hvac_mode
        "off", "Off" is set instead and the temperature is ignored.

        From 30_DUOFERN.pm %setsThermostat:
          desired-temp:$tempSetList (4.0-28.0°C for 0xE1, 4.0-40.0°C for 0x73)
        """
        if kwargs.get(ATTR_HVAC_MODE) == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        temp = max(
            TEMP_MIN, min(self._attr_max_temp, round(temp / TEMP_STEP) * TEMP_STEP)
        )
        self._hvac_off = False
        await self.coordinator.async_set_desired_temp(self._device_code, temp)
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode.

        OFF  -> remember the current setpoint, set desired-temp to minimum (4°C)
        HEAT -> only when "Off": restore the setpoint from before "Off"
                (20°C if none is known). Without "Off" nothing is sent.
        """
        if hvac_mode == HVACMode.OFF:
            if not self._hvac_off:
                self._setpoint_before_off = self.native_target_temperature
                self._off_confirmed = False
            self._hvac_off = True
            await self.coordinator.async_set_desired_temp(self._device_code, TEMP_MIN)
            self.async_write_ha_state()
        elif hvac_mode == HVACMode.HEAT and self._hvac_off:
            temp = self._setpoint_before_off
            if temp is None:
                temp = TEMP_HEAT_DEFAULT
            await self.async_set_temperature(**{ATTR_TEMPERATURE: temp})

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        """Store the setpoint from before "Off" across restarts."""
        return RestoredExtraData(
            {_EXTRA_SETPOINT_BEFORE_OFF: self._setpoint_before_off}
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return device_description(
            self.coordinator,
            self._device_code,
            self._hex_code,
            sw_version=state.status.version if state else None,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        state = self._device_state
        if state:
            self._sync_device_firmware(self._hex_code, state.status.version)
            # A setpoint above the minimum set on the device (dial, Homepilot)
            # ends "Off", but only after the minimum has been seen once and
            # not while an HSA change is still queued: until then the state
            # can still carry the setpoint from before "Off".
            desired = state.status.desired_temp
            if self._hvac_off and desired is not None:
                if desired <= TEMP_MIN:
                    self._off_confirmed = True
                elif self._off_confirmed and "desired-temp" not in state.hsa_pending:
                    self._hvac_off = False
        self.async_write_ha_state()
