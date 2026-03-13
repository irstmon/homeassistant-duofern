"""DuoFern device triggers for remote controls and environmental sensors.

Provides GUI-selectable automation triggers for:
  - Handsender / Wandtaster: one trigger per (channel, action) combination
  - Environmental sensors (A5/AF/A9/AA) and 0x61 RolloTron Comfort Master:
    one trigger per (sun/wind, start/end) combination

From 30_DUOFERN.pm sensorMsg:
  Button events: up, stop, down, stepUp, stepDown, pressed, on, off
  Sun events:    0708 startSun, 070A endSun
  Wind events:   070D startWind, 070E endWind
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
from .coordinator import DUOFERN_EVENT

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
    0x74: ["01"],  # Wandtaster 6fach 230V
    0xAD: ["01", "02", "03", "04", "05", "06"],  # Wandtaster 6fach Bat
}

# Environmental trigger types: trigger_type -> [(subtype, duofern_event_name), ...]
# From 30_DUOFERN.pm sensorMsg: 0708=startSun, 070A=endSun, 070D=startWind, 070E=endWind
_ENV_TRIGGERS: dict[str, list[tuple[str, str]]] = {
    "sun": [("start", "startSun"), ("end", "endSun")],
    "wind": [("start", "startWind"), ("end", "endWind")],
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): str,  # "channel_01".."channel_06" or "sun"/"wind"
        vol.Required(CONF_SUBTYPE): str,  # button action or "start"/"end"
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
    """Return trigger dicts for a DuoFern remote control or environmental sensor.

    For remote controls: one trigger per (channel, action) combination.
    For env sensors / 0x61: one trigger per (sun/wind, start/end) combination.
    """
    result = _get_hex_code_and_type(hass, device_id)
    if result is None:
        return []

    _hex_code, device_type = result
    triggers: list[dict] = []

    # --- Remote controls / wall buttons ---
    if device_type in REMOTE_DEVICE_TYPES:
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

    # --- Environmental sensors and 0x61 RolloTron Comfort Master ---
    # 0x61 is a cover with a built-in brightness sensor.
    # A5/AF/A9/AA are dedicated sensor devices.
    _is_sun = device_type in SUN_SENSOR_DEVICE_TYPES
    _is_wind = device_type in WIND_SENSOR_DEVICE_TYPES
    if _is_sun or _is_wind:
        for trigger_type, subtypes in _ENV_TRIGGERS.items():
            if trigger_type == "sun" and not _is_sun:
                continue
            if trigger_type == "wind" and not _is_wind:
                continue
            for subtype, _event_name in subtypes:
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

    For remotes:     (type=channel_XX, subtype=action) -> duofern_event with channel
    For env sensors: (type=sun/wind, subtype=start/end) -> duofern_event with event name
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

    if trigger_type in _ENV_TRIGGERS:
        # Environmental sensor: type="sun"/"wind", subtype="start"/"end"
        event_name = dict(_ENV_TRIGGERS[trigger_type]).get(subtype, "")
        event_data: dict = {
            "device_code": hex_code,
            "event": event_name,
        }
    else:
        # Remote control: type="channel_01", subtype="up"/"down"/etc.
        channel = trigger_type.replace("channel_", "")
        event_data = {
            "device_code": hex_code,
            "event": subtype,
            "channel": channel,
        }

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: DUOFERN_EVENT,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )

    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info
    )
