"""Light platform for DuoFern dimmers.

Covers the following device types:
  0x48  Dimmaktor
  0x4A  Dimmer (9476-1)

Both use status format "25" / "2B" with a "level" reading (0-100).
In HA, level maps to brightness (0-255).

From 30_DUOFERN.pm:
  %sets = (%setsBasic, %setsDimmer) if ($hash->{CODE} =~ /^(48|4A)..../);

%setsDimmer includes: level, on, off, dawnAutomatic, duskAutomatic,
  manualMode, sunAutomatic, timeAutomatic, sunMode, modeChange,
  stairwellFunction, stairwellTime, runningTime, intermediateMode,
  intermediateValue, saveIntermediateOnStop, dusk, dawn.

All automation readings are exposed as extra_state_attributes.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
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

_SKIP_AS_ATTRIBUTE = {"level"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern light/dimmer entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernLight] = []
    for hex_code, device_state in coordinator.data.devices.items():
        if device_state.device_code.is_light:
            entities.append(
                DuoFernLight(
                    coordinator=coordinator,
                    device_state=device_state,
                    hex_code=hex_code,
                )
            )
            _LOGGER.debug("Adding light entity for device %s", hex_code)

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern light entities", len(entities))


class DuoFernLight(CoordinatorEntity[DuoFernCoordinator], LightEntity):
    """A DuoFern dimmer as a HA LightEntity with brightness control.

    Level 0-100 from DuoFern maps to brightness 0-255 in HA.

    From 30_DUOFERN.pm %setsDimmer:
      level:slider,0,1,100  — main dim level
      on / off              — full on / full off
      intermediateValue     — saved intermediate level (e.g. 50%)
      stairwellFunction     — timed auto-off
      stairwellTime         — auto-off delay (seconds / 10)
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

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
    def is_on(self) -> bool | None:
        """Return True if dimmer level > 0."""
        state = self._device_state
        if state is None or state.status.level is None:
            return None
        return state.status.level > 0

    @property
    def brightness(self) -> int | None:
        """Return HA brightness (0-255) from DuoFern level (0-100).

        From 30_DUOFERN.pm %statusIds id=300:
          "level" -> 0-100
        """
        state = self._device_state
        if state is None or state.status.level is None:
            return None
        return round(state.status.level * 255 / 100)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return automation and timer readings as extra state attributes.

        Includes: dawnAutomatic, duskAutomatic, sunAutomatic, timeAutomatic,
        manualMode, sunMode, modeChange, stairwellFunction, stairwellTime,
        runningTime, intermediateMode, intermediateValue, saveIntermediateOnStop.
        All defined in %setsDimmer and %statusIds (format 25/2B) in 30_DUOFERN.pm.
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
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the dimmer, optionally to a specific brightness.

        From 30_DUOFERN.pm %commands:
          on       => cmd => {val => "0E03"}
          position => cmd => {val => "0707"} (level command)
        """
        if ATTR_BRIGHTNESS in kwargs:
            # Convert HA brightness (0-255) to DuoFern level (0-100)
            level = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            await self.coordinator.async_set_level(self._device_code, level)
        else:
            await self.coordinator.async_switch_on(self._device_code)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the dimmer.

        From 30_DUOFERN.pm %commands: off => cmd => {val => "0E02"}
        """
        await self.coordinator.async_switch_off(self._device_code)

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
