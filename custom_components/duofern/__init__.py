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
  button.py       → ButtonEntity for stick control: start pairing,
                     start unpairing, request status of all devices
  diagnostics.py  → HA diagnostics panel ("Download diagnostics") with
                     full device snapshot (codes, types, readings, versions)
  switch.py       → SwitchEntity for Universalaktor (2-channel), Steckdosenaktor,
                     Troll light mode — all readings as extra_state_attributes
  light.py        → LightEntity for Dimmaktor / Dimmer 9476 with brightness
  climate.py      → ClimateEntity for Raumthermostat and Heizkörperantrieb
  binary_sensor.py→ BinarySensorEntity for motion detector, smoke detector,
                     window/door contact — state via duofern_event bus
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

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

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
    Platform.EVENT,
    Platform.TEXT,
]

SERVICE_PAIR_BY_CODE = "pair_device_by_code"
PAIR_BY_CODE_SCHEMA = vol.Schema({vol.Required("device_code"): cv.string})

# Type alias for runtime data stored on the config entry
type DuoFernConfigEntry = ConfigEntry[DuoFernCoordinator]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries to new format.

    Version 1 -> 2: Add paired_devices key to entry.data (empty list default).
    """
    _LOGGER.debug(
        "Migrating DuoFern config entry from version %s", config_entry.version
    )

    if config_entry.version == 1:
        new_data = {**config_entry.data, CONF_PAIRED_DEVICES: []}
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("Migrated DuoFern config entry to version 2")

    if config_entry.version > 2:
        _LOGGER.error(
            "Cannot migrate DuoFern config entry from version %s — "
            "downgrade the integration to the version that created it",
            config_entry.version,
        )
        return False

    return True


async def async_setup_entry(hass: HomeAssistant, entry: DuoFernConfigEntry) -> bool:
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
        config_entry=entry,
        serial_port=port,
        system_code=system_code,
        paired_devices=paired_devices,
    )

    try:
        await coordinator.async_connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to DuoFern stick: {err}") from err

    # Store the coordinator as runtime data on the config entry
    entry.runtime_data = coordinator

    # Register the pair-by-code service, always with the current coordinator.
    async def _handle_pair_by_code(call: ServiceCall) -> None:
        """Handle the pair_device_by_code service call."""
        await coordinator.async_pair_device_by_code(call.data["device_code"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAIR_BY_CODE,
        _handle_pair_by_code,
        schema=PAIR_BY_CODE_SCHEMA,
    )
    entry.async_on_unload(
        lambda: hass.services.async_remove(DOMAIN, SERVICE_PAIR_BY_CODE)
    )

    # Register callback so the coordinator can notify us when a brand-new
    # device is paired via the stick's pairing button.  We then persist its
    # hex code into the config entry's paired_devices list and reload the
    # integration so HA creates all the correct entities for the new device.
    def _on_new_device_paired(device_code: object) -> None:
        """Persist a newly paired device and reload the integration."""
        if not isinstance(device_code, DuoFernId):
            return
        current: list[str] = list(entry.data.get(CONF_PAIRED_DEVICES, []))
        # Deduplicate by base 6-char hex — only store the short 6-char code.
        existing_bases = {c[:6] for c in current}
        if device_code.hex in existing_bases:
            _LOGGER.debug(
                "Device %s already in paired list — skipping update",
                device_code.hex,
            )
            return
        current.append(device_code.hex)
        _LOGGER.info(
            "Persisting new paired device %s into config entry (%d total)",
            device_code.hex,
            len(current),
        )
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_PAIRED_DEVICES: current}
        )
        # Reload so HA creates entities for the new device
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    coordinator.register_on_new_device_paired(_on_new_device_paired)

    # Register the USB stick as a device BEFORE platforms are set up.
    # This is required so that child devices can reference it via via_device
    # without triggering a "non existing via_device" warning.
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, system_code.hex)},
        manufacturer="Rademacher",
        model="DuoFern USB-Stick",
        name=f"DuoFern Stick ({system_code.hex})",
    )

    # Listen for config entry updates (e.g., device list changes via options flow)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Forward setup to platforms (cover)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Clean up any devices/entities that were removed from the config
    await _async_cleanup_stale_devices(hass, entry)

    # Second status broadcast after 15s to catch devices that missed the first one.
    # Some devices don't respond to the initial broadcast during startup.
    async def _delayed_status_broadcast(_now: object = None) -> None:
        _LOGGER.debug("Sending delayed startup status broadcast")
        await coordinator.async_request_all_status()

    entry.async_on_unload(async_call_later(hass, 15, _delayed_status_broadcast))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DuoFernConfigEntry) -> bool:
    """Unload a DuoFern config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: DuoFernCoordinator = entry.runtime_data
        await coordinator.async_disconnect()

    return unload_ok


async def _async_cleanup_stale_devices(
    hass: HomeAssistant, entry: DuoFernConfigEntry
) -> None:
    """Remove stale devices and entities from the HA registry.

    Called once after all platforms have finished their setup, so every entity
    that the current code wants to create is already registered before we start
    removing things.

    Two kinds of staleness are handled here:

    1. **Stale devices** — a device code was removed from the DuoFern pairing
       list (e.g. the user un-paired a roller shutter).  The device entry and
       all its child entities are deleted from the registry.

    2. **Stale entities on still-paired devices** — the integration was updated
       and a particular entity type is no longer created for a given device type
       (e.g. the "Remote Pair" / "Remote Unpair" buttons were removed for the
       0xE1 Heizkörperantrieb, or an obstacle-detection binary sensor was
       dropped because we verified the device doesn't report it).  These orphan
       entities linger in the registry after an update until explicitly removed.

    Strategy for (2): after all platforms ran their async_setup_entry the HA
    entity registry already contains every *current* entity.  We collect the
    unique_ids that belong to this config entry, compare them against all
    registry entries for the entry, and delete the difference.  HA will
    recreate any entity that should exist on the next startup automatically.
    """
    coordinator: DuoFernCoordinator = entry.runtime_data
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    # ── 1. Build the set of device identifier strings that are still paired ──
    paired_hexes: set[str] = {hex_code for hex_code in coordinator.data.devices}
    # Always keep the USB stick itself
    paired_hexes.add(coordinator.system_code.hex)

    # ── 2. The set of unique_ids that the current integration code actually
    #       created this run — populated by each platform via coordinator.data.
    #       registered_unique_ids.update(...) before calling async_add_entities.
    #       This is the ground truth: anything NOT in this set is stale. ───────
    current_unique_ids: set[str] = coordinator.data.registered_unique_ids

    # Safety guard: if no unique_ids were registered at all, one or more
    # platforms failed to load (e.g. button.py raised during async_setup_entry).
    # In that case skip stale-entity cleanup entirely to avoid incorrectly
    # deleting entities that simply weren't registered this run due to the error.
    # The missing entities will re-appear on the next successful startup.
    if not current_unique_ids:
        _LOGGER.warning(
            "DuoFern: no unique_ids were registered during platform setup — "
            "skipping stale entity cleanup to avoid accidental entity deletion. "
            "Check integration logs for platform load errors."
        )
        return

    # ── 3. Remove stale devices (and their child entities) ──────────────────
    for device_entry in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        device_idents = {
            ident[1] for ident in device_entry.identifiers if ident[0] == DOMAIN
        }
        if device_idents and not device_idents.intersection(paired_hexes):
            # Device no longer paired — remove all its entities first, then
            # the device itself so the registry stays consistent.
            for entity_entry in er.async_entries_for_device(
                entity_reg, device_entry.id, include_disabled_entities=True
            ):
                entity_reg.async_remove(entity_entry.entity_id)
                _LOGGER.debug(
                    "Removed entity '%s' — parent device '%s' is no longer paired",
                    entity_entry.entity_id,
                    device_entry.name,
                )
            device_reg.async_remove_device(device_entry.id)
            _LOGGER.info(
                "Removed device '%s' — no longer in paired devices list",
                device_entry.name,
            )

    # ── 4. Remove stale entities on still-paired devices ────────────────────
    # After step 3 the registry only contains entities for devices that are
    # still paired.  Any entity whose unique_id is NOT in current_unique_ids
    # was created by an older version of the integration and should be removed.
    for reg_entry in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if reg_entry.unique_id not in current_unique_ids:
            entity_reg.async_remove(reg_entry.entity_id)
            _LOGGER.warning(
                "Removed stale entity '%s' (unique_id '%s' is no longer created "
                "by the current integration version — this is expected after an "
                "integration update that removed or renamed entity types)",
                reg_entry.entity_id,
                reg_entry.unique_id,
            )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates (reload integration)."""
    await hass.config_entries.async_reload(entry.entry_id)
