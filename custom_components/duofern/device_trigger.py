"""DuoFern device triggers for remote controls and environmental sensors.

Provides GUI-selectable automation triggers for:
  - Handsender / Wandtaster: one trigger per (channel, action) combination
  - Environmental sensors (A5/AF/A9/AA) and 0x61 RolloTron Comfort Master:
    one trigger per (sun/wind, start/end) combination — flat, no Grenzwert
    concept, these are simple standalone sensors
  - 0x69 Umweltsensor channel "00": one trigger per (Sonne/Wind/Temperatur/
    Morgendämmerung/Abenddämmerung, Grenzwert 1-5, start/end or single-shot)
    combination, PLUS a flat Regen trigger (Homepilot has no Grenzwert
    concept for rain — confirmed via real screenshots, only one Ein/Aus
    toggle, no "Grenzwert 1-5" list like the other four)

From 30_DUOFERN.pm sensorMsg:
  Button events:       up, stop, down, stepUp, stepDown, pressed, on, off
  Sun events:          0708 startSun, 070A endSun
  Wind events:         070D startWind, 070E endWind
  Rain events:         0711 startRain, 0712 endRain (Umweltsensor only)
  Temperature events:  071C startTemp, 071D endTemp (Umweltsensor only)
  Dawn/Dusk events:    0713 dawn, 0709 dusk (Umweltsensor only, momentary,
                        no start/end pair)

Umweltsensor (0x69) special case: it is registered as two separate HA
devices (channel "00" weather station, channel "01" actor) that both report
device_type=0x69. Only channel "00" ever sends these events — see the
channel-suffix guard in async_get_triggers().

Per-Grenzwert-slot matching (Sonne/Wind/Temperatur/Morgendämmerung/
Abenddämmerung): 30_DUOFERN.pm's sensorMsg channel byte for these event
types is a 5-bit BITMASK of which of the up to 5 configured Grenzwerte
fired, not a device channel (see coordinator._handle_sensor_event's
docstring). HA's standard device-trigger delegation
(event_trigger.async_attach_trigger) only supports EXACT match on
event_data fields — it cannot express "bit N of this bitmask is set". So
rather than matching the bitmask ourselves with a non-standard listener,
the coordinator additionally fires one clean, exact-matchable
DUOFERN_SLOT_EVENT per active slot (see coordinator.py's
DUOFERN_SLOT_EVENT/_GRENZWERT_BITMASK_EVENT_NAMES), and these per-slot
triggers match on that instead — staying fully within HA's documented,
supported device-trigger pattern.

dawn/dusk ARE offered here too (unlike earlier revisions of this file) —
now that per-Grenzwert matching exists, a dedicated trigger per Grenzwert
slot is more useful for automations than the native Event-entity trigger
alone (DuoFernUmweltsensorDawnDuskEvent in event.py, which only lets you
pick "dawn" or "dusk" as a whole, not a specific Grenzwert without a
template). Both remain available side by side — the Event entity trigger
for "any dawn/dusk", this device trigger for "Grenzwert N specifically".
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    REMOTE_DEVICE_TYPES,
    SUN_SENSOR_DEVICE_TYPES,
    WIND_SENSOR_DEVICE_TYPES,
)
from .coordinator import DUOFERN_EVENT, DUOFERN_SLOT_EVENT

_LOGGER = logging.getLogger(__name__)

CONF_SUBTYPE = "subtype"

# Button action types — from SENSOR_MESSAGES in const.py
TRIGGER_TYPES: list[str] = [
    "up",
    "stop",
    "down",
    "stepUp",
    "stepDown",
    "pressed",
    "on",
    "off",
]

# Max channels per remote device type (from device name / FHEM %devices)
_REMOTE_CHANNELS: dict[int, list[str]] = {
    0xA0: ["01", "02", "03", "04", "05", "06"],  # Handsender 6 Gruppen
    0xA1: ["01"],  # Handsender 1 Gruppe
    0xA2: ["01", "02", "03", "04", "05", "06"],  # Handsender 6 Gruppen
    0xA3: ["01"],  # Handsender 1 Gruppe
    0xA4: ["01"],  # Wandtaster
    0xA7: ["01"],  # Funksender UP
    # 6 physical buttons, distinguished purely by the channel byte inside
    # each sensorMsg event frame — same model as 0xAD below, not separate
    # HA sub-devices (FHEM %devices "chans" only pre-declares a single
    # actor/relay sub-channel "01" for this device type).
    0x74: ["01", "02", "03", "04", "05", "06"],  # Wandtaster 6fach 230V
    0xAD: ["01", "02", "03", "04", "05", "06"],  # Wandtaster 6fach Bat
}

# Flat (non-slot) environmental triggers.
# Used for: (a) non-Umweltsensor sensor devices (0x61/A5/AF/A9/AA) — these
# are simple standalone sensors with no Grenzwert/multi-slot concept at all,
# their sun/wind triggers stay exactly as before; (b) the Umweltsensor's
# Regen trigger specifically — Homepilot's own "Regen" screen has only a
# single Ein/Aus toggle, no "Grenzwert 1-5" list like Sonne/Wind/Temperatur/
# Morgen-/Abenddämmerung have, so it's deliberately NOT expanded per-slot.
_ENV_TRIGGERS: dict[str, list[tuple[str, str]]] = {
    "sun": [("start", "startSun"), ("end", "endSun")],
    "wind": [("start", "startWind"), ("end", "endWind")],
    "rain": [("start", "startRain"), ("end", "endRain")],
}

# Per-Grenzwert-slot triggers — Umweltsensor (0x69) channel "00" ONLY.
# group -> list of (subtype, base_event_name). Expanded to 5 slots each in
# async_get_triggers()/async_attach_trigger() below. Subtype vocabulary is
# deliberately different per group to read naturally in the automation UI:
#   Sonne/Wind: "start"/"end" (a physical condition becomes true / stops)
#   Temperatur: "exceeded"/"undercut" (crossing above / back below a threshold)
#   Morgen-/Abenddämmerung: "triggered" only — FHEM has no corresponding
#     "end" message for dawn/dusk (single momentary trigger, see module
#     docstring), so there is no second subtype to pair it with.
_GRENZWERT_TRIGGERS: dict[str, list[tuple[str, str]]] = {
    "sun": [("start", "startSun"), ("end", "endSun")],
    "wind": [("start", "startWind"), ("end", "endWind")],
    "temperature": [("exceeded", "startTemp"), ("undercut", "endTemp")],
    "dawn": [("triggered", "dawn")],
    "dusk": [("triggered", "dusk")],
}

_GRENZWERT_SLOTS = (1, 2, 3, 4, 5)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        # "channel_01".."channel_06" (remotes), "sun"/"wind"/"rain" (flat env),
        # or "sun_1".."dusk_5" (Umweltsensor per-Grenzwert-slot)
        vol.Required(CONF_TYPE): str,
        vol.Required(CONF_SUBTYPE): str,
    }
)


def _get_hex_code_and_type(
    hass: HomeAssistant, device_id: str
) -> tuple[str, int] | None:
    """Return (hex_code, device_type) for a DuoFern device, or None."""
    device_reg = dr.async_get(hass)
    device = device_reg.async_get(device_id)
    if device is None:
        return None
    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            hex_code = identifier
            # Device type is first byte of hex_code (2 hex chars)
            try:
                device_type = int(hex_code[:2], 16)
            except ValueError:
                return None
            return hex_code, device_type
    return None


def _parse_grenzwert_trigger_type(trigger_type: str) -> tuple[str, int] | None:
    """Split "sun_3" -> ("sun", 3), or None if not a recognised per-slot type."""
    group, _, slot_str = trigger_type.rpartition("_")
    if group in _GRENZWERT_TRIGGERS and slot_str.isdigit():
        slot = int(slot_str)
        if slot in _GRENZWERT_SLOTS:
            return group, slot
    return None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict]:
    """Return trigger dicts for a DuoFern remote control or environmental sensor.

    For remote controls: one trigger per (channel, action) combination.
    For non-Umweltsensor sensor devices: one trigger per (sun/wind, start/end).
    For Umweltsensor channel "00": one trigger per (group, Grenzwert 1-5,
    subtype) combination, plus the flat Regen trigger.
    """
    result = _get_hex_code_and_type(hass, device_id)
    if result is None:
        return []

    hex_code, device_type = result
    triggers: list[dict] = []

    # --- Remote controls / wall buttons ---
    # 0x65/0x74 are registered as two HA devices: "00" (sensor/button events)
    # and "01" (actor/relay). The button events are only ever fired with the
    # "00" device code (see _handle_sensor_event in coordinator.py), so the
    # "01" actor device must not offer these triggers - they would never fire.
    _is_actor_channel = (
        device_type in (0x65, 0x74) and len(hex_code) == 8 and hex_code.endswith("01")
    )
    if device_type in REMOTE_DEVICE_TYPES and not _is_actor_channel:
        channels = _REMOTE_CHANNELS.get(device_type, ["01"])
        for channel in channels:
            for action in TRIGGER_TYPES:
                triggers.append(
                    {
                        CONF_PLATFORM: "device",
                        CONF_DOMAIN: DOMAIN,
                        CONF_DEVICE_ID: device_id,
                        CONF_TYPE: f"channel_{channel}",
                        CONF_SUBTYPE: action,
                    }
                )

    # --- Umweltsensor (0x69) channel "00": per-Grenzwert-slot triggers ---
    # It is registered as TWO separate HA devices (channel "00" weather
    # station, channel "01" actor), both reporting device_type=0x69 since
    # _get_hex_code_and_type only looks at the first hex byte. Only channel
    # "00" ever actually sends these sensorMsg events — offering the
    # trigger on the channel "01" device would silently never fire, so this
    # whole block is gated on the "00" suffix check, and 0x69 is handled
    # entirely separately from the flat non-Umweltsensor sensor devices below.
    if device_type == 0x69 and hex_code.endswith("00"):
        for group, subtypes in _GRENZWERT_TRIGGERS.items():
            for slot in _GRENZWERT_SLOTS:
                for subtype, _event_name in subtypes:
                    triggers.append(
                        {
                            CONF_PLATFORM: "device",
                            CONF_DOMAIN: DOMAIN,
                            CONF_DEVICE_ID: device_id,
                            CONF_TYPE: f"{group}_{slot}",
                            CONF_SUBTYPE: subtype,
                        }
                    )
        # Regen: flat, no Grenzwert concept (see _ENV_TRIGGERS docstring)
        for subtype, _event_name in _ENV_TRIGGERS["rain"]:
            triggers.append(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: "rain",
                    CONF_SUBTYPE: subtype,
                }
            )

    # --- Other environmental sensors and 0x61 RolloTron Comfort Master ---
    # 0x61 is a cover with a built-in brightness sensor. A5/AF/A9/AA are
    # dedicated standalone sensor devices — none of these have a Grenzwert/
    # multi-slot concept, so they keep the original flat sun/wind triggers.
    # Explicitly excludes 0x69 (handled entirely above) even though 0x69 is
    # technically also a member of SUN_SENSOR_DEVICE_TYPES/
    # WIND_SENSOR_DEVICE_TYPES (needed there so sensor.py/binary_sensor.py
    # style device-type checks elsewhere still work) — without this
    # exclusion the Umweltsensor's channel "01" device would incorrectly
    # get these flat (non-functional, since only channel "00" ever fires
    # them) triggers offered too.
    elif device_type != 0x69:
        _is_sun = device_type in SUN_SENSOR_DEVICE_TYPES
        _is_wind = device_type in WIND_SENSOR_DEVICE_TYPES
        if _is_sun or _is_wind:
            for trigger_type in ("sun", "wind"):
                if trigger_type == "sun" and not _is_sun:
                    continue
                if trigger_type == "wind" and not _is_wind:
                    continue
                for subtype, _event_name in _ENV_TRIGGERS[trigger_type]:
                    triggers.append(
                        {
                            CONF_PLATFORM: "device",
                            CONF_DOMAIN: DOMAIN,
                            CONF_DEVICE_ID: device_id,
                            CONF_TYPE: trigger_type,
                            CONF_SUBTYPE: subtype,
                        }
                    )

    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger for a DuoFern remote or environmental sensor.

    For remotes:            (type=channel_XX, subtype=action)
                             -> duofern_event with channel, exact match
    For flat env triggers:  (type=sun/wind/rain, subtype=start/end)
                             -> duofern_event with event name, exact match
    For per-slot triggers:  (type=sun_3/etc, subtype=start/end/exceeded/...)
                             -> duofern_grenzwert_event with event name +
                                slot, exact match (see module docstring for
                                why this needs a dedicated event type)
    All three paths delegate to the standard event_trigger.async_attach_trigger
    — no custom event-bus listening, staying within HA's documented pattern.
    """
    result = _get_hex_code_and_type(hass, config[CONF_DEVICE_ID])
    if result is None:
        _LOGGER.warning(
            "DuoFern device_trigger: device %s not found in integration data — "
            "trigger will be silently inactive. The device may have been removed "
            "from the paired devices list.",
            config[CONF_DEVICE_ID],
        )
        return lambda: None

    hex_code, _device_type = result
    trigger_type: str = config[CONF_TYPE]
    subtype: str = config[CONF_SUBTYPE]

    slot_match = _parse_grenzwert_trigger_type(trigger_type)
    if slot_match is not None:
        group, slot = slot_match
        event_name = dict(_GRENZWERT_TRIGGERS[group]).get(subtype, "")
        event_type = DUOFERN_SLOT_EVENT
        event_data: dict = {
            "device_code": hex_code,
            "event": event_name,
            "slot": str(slot),
        }
    elif trigger_type in _ENV_TRIGGERS:
        # Flat environmental sensor: type="sun"/"wind"/"rain", subtype="start"/"end"
        event_name = dict(_ENV_TRIGGERS[trigger_type]).get(subtype, "")
        event_type = DUOFERN_EVENT
        event_data = {
            "device_code": hex_code,
            "event": event_name,
        }
    else:
        # Remote control: type="channel_01", subtype="up"/"down"/etc.
        channel = trigger_type.replace("channel_", "")
        event_type = DUOFERN_EVENT
        event_data = {
            "device_code": hex_code,
            "event": subtype,
            "channel": channel,
        }

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )

    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info
    )
