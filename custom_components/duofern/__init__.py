"""The Rademacher DuoFern integration.

Custom integration for controlling Rademacher DuoFern roller shutters
via the DuoFern USB stick. Uses a clean protocol re-implementation based
on the FHEM Perl modules (10_DUOFERNSTICK.pm, 30_DUOFERN.pm).

Architecture:
  config_flow.py  → User setup (serial port, system code, device codes)
  __init__.py     → Integration setup, creates coordinator and stick device
  coordinator.py  → DataUpdateCoordinator (push-based), owns the stick,
                     manages pairing/unpairing, dispatches all incoming frames
  stick.py        → Async serial I/O, init handshake, send queue
  protocol.py     → Pure protocol encoder/decoder (no HA dependencies)
  const.py        → All protocol constants, device tables, status mappings
                     transcribed 1:1 from 30_DUOFERN.pm
  cover.py        → CoverEntity for roller shutters (RolloTron, Rohrmotor,
                     Troll, SX5) — all cover formats 21/23/23a/24/24a
  button.py       → ButtonEntity for stick control: pairing starten,
                     unpairing starten, status aller Geräte abfragen
  diagnostics.py  → HA diagnostics panel ("Diagnose herunterladen") with
                     full device snapshot (codes, types, readings, versions)
  switch.py       → SwitchEntity for Universalaktor (2-channel), Steckdosenaktor,
                     Troll Lichtmodus — all readings as extra_state_attributes
  light.py        → LightEntity for Dimmaktor / Dimmer 9476 with brightness
  climate.py      → ClimateEntity for Raumthermostat and Heizkörperantrieb
  binary_sensor.py→ BinarySensorEntity for Bewegungsmelder, Rauchmelder,
                     Fenster-Tuer-Kontakt — state via duofern_event bus
  sensor.py       → SensorEntity for Umweltsensor weather readings
                     (brightness, temperature, wind, sunDirection, sunHeight)
  switch.py (2)   → Also creates DuoFernAutomationSwitch (CONFIG) for every
                     on/off automation flag per device (manualMode,
                     timeAutomatic, dawnAutomatic, sunAutomatic, etc.)
  number.py       → NumberEntity (slider) for numeric config values
                     (sunPosition, ventilatingPosition, slatPosition,
                     runningTime, stairwellTime, intermediateValue, etc.)
  select.py       → SelectEntity for multi-option settings
                     (motorDeadTime, windDirection, automaticClosing,
                     openSpeed, actTempLimit)
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_DEVICE_CODE, CONF_PAIRED_DEVICES, CONF_SERIAL_PORT, DOMAIN
from .coordinator import DuoFernCoordinator
from .protocol import DuoFernId

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.COVER,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.LIGHT,
    Platform.CLIMATE,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]

# Type alias for runtime data stored on the config entry
type DuoFernConfigEntry = ConfigEntry[DuoFernCoordinator]


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrate old config entries to new format.

    Version 1 -> 2: Add paired_devices key to entry.data (empty list default).
    """
    _LOGGER.debug(
        "Migrating DuoFern config entry from version %s", config_entry.version
    )

    if config_entry.version == 1:
        new_data = {**config_entry.data, CONF_PAIRED_DEVICES: []}
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2
        )
        _LOGGER.info("Migrated DuoFern config entry to version 2")

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: DuoFernConfigEntry
) -> bool:
    """Set up DuoFern from a config entry.

    Called by HA when the user completes the config flow or on HA startup
    if already configured.
    """
    port: str = entry.data[CONF_SERIAL_PORT]
    system_code_hex: str = entry.data[CONF_DEVICE_CODE]

    system_code = DuoFernId.from_hex(system_code_hex)

    # Collect paired device codes from config entry data
    paired_device_hexes: list[str] = entry.data.get(CONF_PAIRED_DEVICES, [])
    paired_devices = [DuoFernId.from_hex(h) for h in paired_device_hexes]

    _LOGGER.info(
        "Setting up DuoFern integration: port=%s, system_code=%s, devices=%d",
        port,
        system_code.hex,
        len(paired_devices),
    )

    # Create and connect the coordinator
    coordinator = DuoFernCoordinator(
        hass=hass,
        serial_port=port,
        system_code=system_code,
        paired_devices=paired_devices,
    )

    try:
        await coordinator.async_connect()
    except Exception as err:
        _LOGGER.error("Failed to connect to DuoFern stick: %s", err)
        raise

    # Store the coordinator as runtime data on the config entry
    entry.runtime_data = coordinator

    # Register the USB stick as a device BEFORE platforms are set up.
    # This is required so that child devices can reference it via via_device
    # without triggering a "non existing via_device" warning.
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, system_code.hex)},
        manufacturer="Rademacher",
        model="DuoFern USB-Stick 7000",
        name=f"DuoFern Stick ({system_code.hex})",
    )

    # Listen for config entry updates (e.g., device list changes via options flow)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Forward setup to platforms (cover)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DuoFernConfigEntry
) -> bool:
    """Unload a DuoFern config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: DuoFernCoordinator = entry.runtime_data
        await coordinator.async_disconnect()

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle config entry updates (reload integration)."""
    await hass.config_entries.async_reload(entry.entry_id)
