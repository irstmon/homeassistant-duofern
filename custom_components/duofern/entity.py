"""Base entity for the DuoFern integration.

Everything the entity platforms have in common lives here:

* DuoFernEntity - the base class of all entities (coordinator entity with
  has_entity_name set, plus the firmware version sync of the device entry).
* device_description() - the full description of a DuoFern device for the
  device registry.
* device_link() - attaches an entity to a device that another entity of the
  same device already describes.
"""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DuoFernCoordinator
from .protocol import DuoFernId

MANUFACTURER = "Rademacher"


def device_link(hex_code: str) -> DeviceInfo:
    """Return device info that only refers to an existing device.

    Used by the additional entities of a device (automation switches,
    buttons, numbers, ...). The device itself is described by its main
    entity through device_description().
    """
    return DeviceInfo(identifiers={(DOMAIN, hex_code)})


def device_name(device_code: DuoFernId, hex_code: str) -> str:
    """Return the name of a device for the device registry.

    "DuoFern <type> (<6-digit code>)", for a channel of a multi-channel
    device followed by " Channel <nn>".
    """
    name = f"DuoFern {device_code.device_type_name} ({hex_code[:6]})"
    if len(hex_code) > 6:
        name += f" Channel {hex_code[6:]}"
    return name


def device_description(
    coordinator: DuoFernCoordinator,
    device_code: DuoFernId,
    hex_code: str,
    *,
    sw_version: str | None = None,
) -> DeviceInfo:
    """Return the full description of a DuoFern device.

    hex_code is the registry identifier: the 6-digit device code, or the
    8-digit code with channel for multi-channel devices. The device name
    shows the channel in words: "DuoFern Universalaktor (43ABCD) Channel 02".

    The firmware version is only included when it is known. Passing None
    would clear the version stored in the device registry, and it is not
    known at startup before the device has sent its first status frame.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, hex_code)},
        name=device_name(device_code, hex_code),
        manufacturer=MANUFACTURER,
        model=device_code.device_type_name,
        serial_number=hex_code,
        via_device_id=coordinator.stick_device_id,
    )
    if sw_version:
        info["sw_version"] = sw_version
    return info


class DuoFernEntity(CoordinatorEntity[DuoFernCoordinator]):
    """Base class of all DuoFern entities."""

    _attr_has_entity_name = True

    @callback
    def _sync_device_firmware(self, hex_code: str, version: str | None) -> None:
        """Write a firmware version from a status frame to the device registry.

        The version is not known when the device entry is created; it arrives
        with the first status frame.
        """
        if not version:
            return
        device_reg = dr.async_get(self.hass)
        device = device_reg.async_get_device_by_identifier(
            (DOMAIN, hex_code), self.coordinator.config_entry.entry_id
        )
        if device and device.sw_version != version:
            device_reg.async_update_device(device.id, sw_version=version)
