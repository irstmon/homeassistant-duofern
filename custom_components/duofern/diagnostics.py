"""Diagnostics support for the DuoFern integration.

Provides a "Diagnose herunterladen" button on each device card in HA.
Downloads a JSON snapshot with all device codes, types, positions,
firmware versions, battery states and all raw readings.

Sensitive data (system code, serial port) is redacted automatically
by HA before showing the download to the user.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DuoFernConfigEntry
from .const import CONF_DEVICE_CODE, CONF_PAIRED_DEVICES, CONF_SERIAL_PORT

# Fields to redact from the config entry data
TO_REDACT = {CONF_DEVICE_CODE, CONF_SERIAL_PORT, CONF_PAIRED_DEVICES}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for the config entry (= the whole integration).

    This is what gets downloaded when the user clicks
    "Diagnose herunterladen" on the integration card.
    """
    coordinator = entry.runtime_data

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "integration": coordinator.get_diagnostics(),
    }
