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

  The HSA has a special bidirectional protocol: on receipt of a status
  frame, pending set-values are encoded back. FHEM stores these in
  hash->{helper}{HSAold} and sends them in the next status ACK.
  We implement a simpler version: desired-temp is sent via the
  coordinator's async_switch_on/off mechanism, which triggers a
  status request after ACK.

  From 30_DUOFERN.pm:
    #Heizkörperantrieb
    if ($code =~ m/^E1..../) { ... $setValue |= ($rawValue << bitFrom) ... }

All automation readings are exposed as extra_state_attributes.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState

_LOGGER = logging.getLogger(__name__)

# Temperature range for Heizkörperantrieb (0xE1): 4.0 .. 28.0 in 0.5 steps.
# From 30_DUOFERN.pm $tempSetList.
TEMP_MIN = 4.0
TEMP_MAX_HSA = 28.0
# Temperature range for Raumthermostat (0x73): 4.0 .. 40.0 in 0.5 steps.
# The wall thermostat GUI and original Rademacher app show 4-40°C.
TEMP_MAX_THERMOSTAT = 40.0
TEMP_STEP = 0.5

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
        e._attr_unique_id for e in entities if e._attr_unique_id is not None
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern climate entities", len(entities))


class DuoFernClimate(
    CoordinatorEntity[DuoFernCoordinator], ClimateEntity, RestoreEntity
):
    """A DuoFern thermostat or radiator valve as a HA ClimateEntity.

    Supports HEAT and OFF modes:
      HEAT: device is controlling temperature (normal operation)
      OFF:  manualMode=on with desired-temp at minimum (FHEM behaviour)

    From 30_DUOFERN.pm %setsThermostat:
      desired-temp:$tempSetList  — 4.0-28.0°C (0xE1), 4.0-40.0°C (0x73)
      manualMode:on,off          — bypass timer program
      timeAutomatic:on,off       — enable/disable timer
      temperatureThreshold1-4    — zone thresholds (4.0-40.0°C)
      actTempLimit:1,2,3,4       — active threshold selection
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
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
    def current_temperature(self) -> float | None:
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
    def target_temperature(self) -> float | None:
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

        Derived exclusively from live device data (state.status.desired_temp),
        NOT from the restored fallback (self._restored_desired_temp).
        Reason: the default restored value is TEMP_MIN (4.0°C), which would
        incorrectly show HVACMode.OFF on startup even if the device is actively
        heating. We return HEAT as the safe default until a live frame arrives.
        """
        state = self._device_state
        if state is not None and state.status.desired_temp is not None:
            if state.status.desired_temp <= TEMP_MIN:
                return HVACMode.OFF
        return HVACMode.HEAT

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

        Sends a DuoFern command to the device. The actual protocol for
        the HSA is bidirectional (helper{HSAold} in FHEM), but a simpler
        approach works: send desired-temp as a level command and wait for
        the next status response to confirm.

        From 30_DUOFERN.pm %setsThermostat:
          desired-temp:$tempSetList (4.0-28.0°C for 0xE1, 4.0-40.0°C for 0x73)
        """
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        temp = max(
            TEMP_MIN, min(self._attr_max_temp, round(temp / TEMP_STEP) * TEMP_STEP)
        )
        await self.coordinator.async_set_desired_temp(self._device_code, temp)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode.

        OFF  -> set desired-temp to minimum (4°C) — equivalent to FHEM off
        HEAT -> set desired-temp to a reasonable default (20°C) if currently off
        """
        if hvac_mode == HVACMode.OFF:
            await self.async_set_temperature(**{ATTR_TEMPERATURE: TEMP_MIN})
        elif hvac_mode == HVACMode.HEAT:
            state = self._device_state
            current = state.status.desired_temp if state else None
            if current is None or current <= TEMP_MIN:
                await self.async_set_temperature(**{ATTR_TEMPERATURE: 20.0})

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=(f"DuoFern {self._device_code.device_type_name} ({self._hex_code})"),
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
