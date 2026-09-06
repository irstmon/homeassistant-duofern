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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, REMOTE_DEVICE_TYPES
from . import DuoFernConfigEntry
from .coordinator import DUOFERN_EVENT, DuoFernCoordinator

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
        # 0x74 now has two sub-channels ("00" events, "01" actor — see
        # DEVICE_CHANNELS in const.py); the event entity belongs on "00",
        # where sensorMsg events actually land (see coordinator.
        # _handle_sensor_event's "00"-redirect for 65/69/74). channel !=
        # "01" also passes for every other REMOTE_DEVICE_TYPES entry
        # (channel is always None for them), so this only changes 0x74.
        if (
            device_state.device_code.device_type in REMOTE_DEVICE_TYPES
            and device_state.channel != "01"
        ):
            entities.append(DuoFernRemoteEvent(coordinator, hex_code, device_state))
            _LOGGER.debug("Adding event entity for remote %s", hex_code)

    # Umweltsensor (0x69) channel "00": dawn/dusk trigger events.
    # From 30_DUOFERN.pm sensorMsg 0713 (dawn) / 0709 (dusk) — unlike
    # Sun/Wind/Temp/Rain, these have no corresponding "end" event (device
    # sends one frame when a Grenzwert's brightness threshold is crossed,
    # nothing when it's no longer crossed), so they don't fit the persistent
    # on/off or active-slot-set model used elsewhere — they're genuinely
    # momentary triggers, which is exactly what EventEntity is for.
    for hex_code, device_state in coordinator.data.devices.items():
        if (
            device_state.device_code.device_type == 0x69
            and device_state.channel == "00"
        ):
            entities.append(
                DuoFernUmweltsensorDawnDuskEvent(coordinator, hex_code, device_state)
            )
            _LOGGER.debug("Adding dawn/dusk event entity for Umweltsensor %s", hex_code)

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        ("event", e._attr_unique_id) for e in entities if hasattr(e, "_attr_unique_id")
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
        device_state,
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
            via_device_id=coordinator.stick_device_id,
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
        device = device_reg.async_get_device_by_identifier(
            (DOMAIN, self._hex_code), self.coordinator.config_entry.entry_id
        )
        if device and device.serial_number != self._hex_code:
            device_reg.async_update_device(device.id, serial_number=self._hex_code)

    @callback
    def _handle_duofern_event(self, event) -> None:
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


class DuoFernUmweltsensorDawnDuskEvent(
    CoordinatorEntity[DuoFernCoordinator], EventEntity
):
    """EventEntity for Umweltsensor (0x69) dawn/dusk trigger events.

    From 30_DUOFERN.pm sensorMsg:
      0713 dawn  (chan=5)
      0709 dusk  (chan=5)
    Both are chan=5 type messages — same bitmask semantics as the Sun/Wind/
    Temperature Grenzwerte (see DuoFernActiveGrenzwerteSensor in sensor.py):
    the channel byte is a 5-bit mask of which of the up to 5 configured
    Grenzwerte triggered, decoded here and passed as extra event data so
    automations can filter by Grenzwert if needed, same idea as the
    "{{ '3' in ... }}" template pattern used for Sun/Wind/Temp.

    Unlike Sun/Wind/Temp/Rain, dawn/dusk have no corresponding "end" event
    in 30_DUOFERN.pm — the device sends one frame when a Grenzwert's
    brightness threshold is crossed and nothing when it no longer is. That
    asymmetry is exactly why this is an EventEntity (momentary trigger)
    rather than a BinarySensor or the active-slot-set sensor used for the
    other three trigger types.

    NOT verified against a real device: no 0713/0709 frame has been
    captured from a real Umweltsensor yet. The channel="00" device lookup
    this depends on (see coordinator._handle_sensor_event) is confirmed
    directly from the FHEM source, but the bitmask decode specifically for
    dawn/dusk has not been cross-checked against a real captured frame.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "dawn_dusk"
    # Deliberately NO explicit _attr_name — see DuoFernActiveGrenzwerteSensor
    # in sensor.py for why (setting both blocks the translation lookup).
    _attr_event_types = ["dawn", "dusk"]

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        hex_code: str,
        device_state,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_dawn_dusk_event"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_added_to_hass(self) -> None:
        """Subscribe to DuoFern events on the HA event bus."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(DUOFERN_EVENT, self._handle_duofern_event)
        )

    @callback
    def _handle_duofern_event(self, event) -> None:
        """Handle a duofern_event for this Umweltsensor's dawn/dusk trigger."""
        data = event.data
        if data.get("device_code") != self._hex_code:
            return

        event_type: str = data.get("event", "")
        if event_type not in ("dawn", "dusk"):
            return

        chan_hex = data.get("channel", "00")
        try:
            raw = int(chan_hex, 16)
        except (TypeError, ValueError):
            raw = 0
        # FHEM: channel byte "00" is not a bitmask — Grenzwert indeterminate.
        grenzwerte = (
            ",".join(str(x + 1) for x in range(5) if (1 << x) & raw) if raw != 0 else ""
        )

        self._trigger_event(event_type, {"grenzwerte": grenzwerte})
        self.async_write_ha_state()
        _LOGGER.debug(
            "Umweltsensor %s: event=%s grenzwerte=%s",
            self._hex_code,
            event_type,
            grenzwerte,
        )
