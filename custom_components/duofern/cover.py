"""Cover platform for DuoFern roller shutters.

Supports all DuoFern cover device types and status formats:
  Format 21:  RolloTron Standard / Comfort (0x40, 0x41, 0x61)
  Format 23:  Rohrmotor-Aktor, Connect-Aktor, Troll Basis,
              Troll Comfort (0x42, 0x49, 0x4B, 0x4C, 0x70)
  Format 23a: Rohrmotor Steuerung (0x47) — format override in const.py
  Format 24a: SX5 garage door (0x4E) — format override in const.py

Each device becomes one CoverEntity with:
  - Open / Close / Stop / Set Position
  - Dusk position command ("set DEVICENAME dusk" in FHEM)
  - Dawn position command ("set DEVICENAME dawn" in FHEM)
  - Position reporting (0 = closed, 100 = open in HA convention)
  - Moving state (opening / closing / stopped)
  - Extra state attributes: ALL readings from the status frame
    (sunMode, ventilatingPosition, manualMode, timeAutomatic,
     dawnAutomatic, duskAutomatic, sunAutomatic, etc.)
  - Device info linked to the hub (USB stick) via via_device

dusk/dawn positions:
  These are NOT the same as dawnAutomatic/duskAutomatic (which toggle automation).
  "dusk" explicitly commands the device to move to its programmed dusk position —
  which is typically slower and quieter than a direct position command.
  "dawn" commands the device to move to its programmed dawn (open) position.

  From 30_DUOFERN.pm %commands:
    dusk => {cmd => {noArg => "070901FF000000000000"}}
    dawn => {cmd => {noArg => "071301FF000000000000"}}

  FHEM commands: set ROLLONAME dusk / set ROLLONAME dawn

  In HA these appear as two extra Buttons on the device card, named
  "Dusk position" and "Dawn position".

Position convention (matches existing HA addon behaviour):
  DuoFern native: 0 = fully open, 100 = fully closed
  Home Assistant: 0 = fully closed, 100 = fully open
  Always inverted — same as the original HA addon cover.py.

Device class per format:
  Format 21/23/23a: CoverDeviceClass.SHUTTER (roller shutter)
  Format 24a:       CoverDeviceClass.GARAGE   (SX5 garage door)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import (
    COVER_DEVICE_TYPES_FORMAT24,
    DOMAIN,
)
from .coordinator import DuoFernCoordinator, DuoFernDeviceState
from .protocol import DuoFernId

_LOGGER = logging.getLogger(__name__)

# Readings exposed as first-class HA properties — skip from extra_state_attributes
_SKIP_AS_ATTRIBUTE = {"position", "moving"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern cover entities from a config entry."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernCover] = []
    for hex_code, device_state in coordinator.data.devices.items():
        if device_state.device_code.is_cover:
            entities.append(
                DuoFernCover(
                    coordinator=coordinator,
                    device_code=device_state.device_code,
                    entry_id=entry.entry_id,
                )
            )
            _LOGGER.debug("Adding cover entity for device %s", hex_code)

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern cover entities", len(entities))


class DuoFernCover(CoordinatorEntity[DuoFernCoordinator], CoverEntity):
    """Representation of a DuoFern roller shutter or garage door as a CoverEntity.

    Inherits from CoordinatorEntity for automatic state updates when the
    coordinator calls async_set_updated_data() on incoming status frames.

    From 30_DUOFERN.pm set commands per device type:
      RolloTron (0x40/0x41/0x61): %setsBasic + %setsDefaultRollerShutter
      Rohrmotor/Troll (0x42/0x4B/0x4C/0x70): + %setsTroll + blindsMode
      Rohrmotor Steuerung (0x47): + %setsTroll (no blindsMode)
      Rohrmotor (0x49): + %setsRolloTube
      SX5 (0x4E): %setsSX5
    All commands including dusk/dawn are implemented.
    All readings are exposed in extra_state_attributes.
    """

    _attr_has_entity_name = True
    _attr_name = None  # Use device name as entity name

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
        entry_id: str,
    ) -> None:
        """Initialize the cover entity."""
        super().__init__(coordinator)

        self._device_code = device_code
        self._hex_code = device_code.hex

        self._attr_unique_id = f"{DOMAIN}_{self._hex_code}"

        # Device class: GARAGE for SX5, SHUTTER for all others
        if device_code.device_type in COVER_DEVICE_TYPES_FORMAT24:
            self._attr_device_class = CoverDeviceClass.GARAGE
        else:
            self._attr_device_class = CoverDeviceClass.SHUTTER

        # All cover types support open/close/stop/set_position.
        # From 30_DUOFERN.pm %setsBasic + %setsDefaultRollerShutter + %setsSX5:
        #   up, down, stop, position (slider 0-100)
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        """Return current device state from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    # ------------------------------------------------------------------
    # CoverEntity properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        state = self._device_state
        if state is None:
            return False
        return state.available and self.coordinator.last_update_success

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (HA: 0=closed, 100=open).

        DuoFern native (invert=100): 0=open, 100=closed.
        HA convention (always inverted, matches existing addon):
          ha_position = 100 - duofern_position

        From 30_DUOFERN.pm (default, without positionInverse attr):
          $state = "opened" if ($state eq "0");
          $state = "closed" if ($state eq "100");
        """
        state = self._device_state
        if state is None or state.status.position is None:
            return None
        return 100 - state.status.position

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is fully closed (HA position == 0)."""
        pos = self.current_cover_position
        if pos is None:
            return None
        return pos == 0

    @property
    def is_opening(self) -> bool:
        """Return True if the cover is currently opening (moving up).

        From 30_DUOFERN.pm:
          readingsSingleUpdate($hash, "moving", "up", 1) if ($cmd eq "up")
        """
        state = self._device_state
        if state is None:
            return False
        return state.status.moving == "up"

    @property
    def is_closing(self) -> bool:
        """Return True if the cover is currently closing (moving down).

        From 30_DUOFERN.pm:
          readingsSingleUpdate($hash, "moving", "down", 1) if ($cmd eq "down")
        """
        state = self._device_state
        if state is None:
            return False
        return state.status.moving == "down"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all device readings as extra state attributes.

        Exposes ALL readings from ParsedStatus.readings that are not
        already first-class HA properties (position, moving).

        This includes all automation flags and configuration values:
          Format 21:  sunMode, ventilatingMode, ventilatingPosition,
                      sunPosition, timeAutomatic, duskAutomatic,
                      dawnAutomatic, sunAutomatic, manualMode, runningTime
          Format 23:  + windAutomatic, rainAutomatic, windMode,
                      rainMode, windDirection, rainDirection, reversal,
                      motorDeadTime, runningTime, blindsMode
          Format 23 blinds: + slatPosition, slatRunTime, tiltInSunPos,
                      tiltInVentPos, tiltAfterMoveLevel, tiltAfterStopDown,
                      defaultSlatPos
          Format 24a (SX5): automaticClosing, openSpeed, 2000cycleAlarm,
                      wicketDoor, backJump, 10minuteAlarm, light
                      [obstacle/block/lightCurtain are separate binary_sensors]
        """
        state = self._device_state
        if state is None:
            return {}

        attrs: dict[str, Any] = {}

        # All readings except first-class HA properties
        for key, value in state.status.readings.items():
            if key not in _SKIP_AS_ATTRIBUTE:
                attrs[key] = value

        if state.status.version:
            attrs["firmware_version"] = state.status.version

        if state.battery_state is not None:
            attrs["battery_state"] = state.battery_state
        if state.battery_percent is not None:
            attrs["battery_level"] = state.battery_percent
        if state.last_seen is not None:
            attrs["last_seen"] = state.last_seen

        return attrs

    # ------------------------------------------------------------------
    # CoverEntity commands
    # ------------------------------------------------------------------

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (move up).

        From 30_DUOFERN.pm: up => cmd => {noArg => "0701tt00000000000000"}
        """
        await self.coordinator.async_cover_up(self._device_code)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (move down).

        From 30_DUOFERN.pm: down => cmd => {noArg => "0703tt00000000000000"}
        """
        await self.coordinator.async_cover_down(self._device_code)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover movement.

        From 30_DUOFERN.pm: stop => cmd => {noArg => "07020000000000000000"}
        """
        await self.coordinator.async_cover_stop(self._device_code)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position.

        HA: 0=closed, 100=open. DuoFern: 0=open, 100=closed.
        duofern_position = 100 - ha_position

        From 30_DUOFERN.pm: position => cmd => {value => "0707ttnn000000000000"}
        """
        ha_position: int = kwargs.get("position", 0)
        duofern_position = 100 - ha_position
        await self.coordinator.async_cover_position(self._device_code, duofern_position)

    # ------------------------------------------------------------------
    # Coordinator entity callbacks
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        state = self._device_state
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
        """Handle updated data from the coordinator."""
        state = self._device_state
        if state and state.status.version:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
            if device and device.sw_version != state.status.version:
                device_reg.async_update_device(
                    device.id, sw_version=state.status.version
                )
        self.async_write_ha_state()
