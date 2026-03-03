"""DuoFern device triggers for remote controls and wall buttons.

Provides GUI-selectable automation triggers for Handsender and Wandtaster
devices. Each trigger maps to a specific button action on a specific channel.

From 30_DUOFERN.pm sensorMsg:
  Button events: up, stop, down, stepUp, stepDown, pressed, on, off
  Channel byte: frame byte 6 (chan_pos=6 in SENSOR_MESSAGES)
  For A0/A2: state includes channel suffix (e.g. "Btn01.3")
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, REMOTE_DEVICE_TYPES
from .coordinator import DUOFERN_EVENT

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
    0x74: ["01"],  # Wandtaster 6fach 230V
    0xAD: ["01", "02", "03", "04", "05", "06"],  # Wandtaster 6fach Bat
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
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


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict]:
    """Return list of trigger dicts for a DuoFern remote device.

    One trigger per (action_type, channel) combination.
    """
    result = _get_hex_code_and_type(hass, device_id)
    if result is None:
        return []

    _hex_code, device_type = result
    if device_type not in REMOTE_DEVICE_TYPES:
        return []

    channels = _REMOTE_CHANNELS.get(device_type, ["01"])
    triggers: list[dict] = []

    for action in TRIGGER_TYPES:
        for channel in channels:
            triggers.append(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: action,
                    CONF_SUBTYPE: f"channel_{channel}",
                }
            )

    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger for a DuoFern remote button press.

    Translates the (type, subtype) GUI selection into a duofern_event
    filter on device_code + event + channel.
    """
    result = _get_hex_code_and_type(hass, config[CONF_DEVICE_ID])
    if result is None:
        return lambda: None

    hex_code, _device_type = result
    action_type: str = config[CONF_TYPE]
    subtype: str = config[CONF_SUBTYPE]
    # subtype is "channel_01" → channel is "01"
    channel = subtype.replace("channel_", "")

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: DUOFERN_EVENT,
            event_trigger.CONF_EVENT_DATA: {
                "device_code": hex_code,
                "event": action_type,
                "channel": channel,
            },
        }
    )

    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info
    )
