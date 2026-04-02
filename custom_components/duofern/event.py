"""DuoFern remote control / wall button event entities.

Each paired Handsender or Wandtaster gets one EventEntity.
When a button is pressed, the entity fires an HA event with the
action name (up/stop/down/pressed/on/off/stepUp/stepDown) and
the channel number so automations can distinguish which button
group was used.

From 30_DUOFERN.pm:
  For A0/A2 devices: state = sensorMsg{id}{state} + "." + chan
  e.g. pressing "up" on channel 3 → state="Btn01.3", channel3="up"
"""

from __future__ import annotations

import logging

from homeassistant.components.event import EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, REMOTE_DEVICE_TYPES
from . import DuoFernConfigEntry
from .coordinator import DUOFERN_EVENT, DuoFernCoordinator, DuoFernDeviceState

_LOGGER = logging.getLogger(__name__)

# All button action names that a remote can send
_REMOTE_EVENT_TYPES: list[str] = [
    "up",
    "stop",
    "down",
    "stepUp",
    "stepDown",
    "pressed",
    "on",
    "off",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern event entities for remote controls."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernRemoteEvent] = []
    for hex_code, device_state in coordinator.data.devices.items():
        if device_state.device_code.device_type in REMOTE_DEVICE_TYPES:
            entities.append(DuoFernRemoteEvent(coordinator, hex_code, device_state))
            _LOGGER.debug("Adding event entity for remote %s", hex_code)

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if e._attr_unique_id is not None
    )
    if entities:
        async_add_entities(entities)


class DuoFernRemoteEvent(CoordinatorEntity[DuoFernCoordinator], EventEntity):
    """An EventEntity for a DuoFern remote control or wall button.

    Fires an HA event with:
      event_type: the button action ("up", "stop", "down", etc.)
      extra data:
        channel: which button group was pressed (e.g. "03" for group 3)
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_event_types = _REMOTE_EVENT_TYPES

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        hex_code: str,
        device_state: DuoFernDeviceState,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_event"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hex_code)},
            name=(f"DuoFern {self._device_code.device_type_name} ({hex_code})"),
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=hex_code,
            via_device=(DOMAIN, coordinator.system_code.hex),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to DuoFern events on the HA event bus."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(DUOFERN_EVENT, self._handle_duofern_event)
        )
        # Ensure serial_number is always set in device registry,
        # even if device was previously registered without it.
        device_reg = dr.async_get(self.hass)
        device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
        if device and device.serial_number != self._hex_code:
            device_reg.async_update_device(device.id, serial_number=self._hex_code)

    @callback
    def _handle_duofern_event(self, event: Event) -> None:
        """Handle a duofern_event for this remote."""
        data = event.data
        if data.get("device_code") != self._hex_code:
            return

        event_type: str = data.get("event", "")
        if event_type not in _REMOTE_EVENT_TYPES:
            return

        channel: str = data.get("channel", "")
        self._trigger_event(event_type, {"channel": channel})
        self.async_write_ha_state()
        _LOGGER.debug(
            "Remote %s: event=%s channel=%s",
            self._hex_code,
            event_type,
            channel,
        )
