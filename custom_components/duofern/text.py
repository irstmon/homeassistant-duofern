"""Text platform for DuoFern.

Provides a text input entity on the stick device card for entering a
6-digit hex device code before triggering pair-by-code.

The text entity is read by DuoFernPairByCodeButton in button.py when
the user presses the "Pair by Code" button.
"""

from __future__ import annotations

import logging
import re

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator

_LOGGER = logging.getLogger(__name__)

# Pattern: exactly 6 hex characters (case-insensitive)
DEVICE_CODE_PATTERN = r"^([0-9A-Fa-f]{6})?$"  # empty or exactly 6 hex chars


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern text entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data
    system_code_hex = coordinator.system_code.hex

    entities = [DuoFernPairCodeText(coordinator, system_code_hex)]

    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id")
    )
    async_add_entities(entities)


class DuoFernPairCodeText(CoordinatorEntity[DuoFernCoordinator], TextEntity):
    """Text input for entering a 6-digit hex device code before pair-by-code.

    Appears on the stick device card alongside the "Pair by Code" button.
    The button reads the current value of this entity when pressed.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "pair_code_input"
    _attr_icon = "mdi:barcode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0  # empty string allowed as initial state
    _attr_native_max = 6
    _attr_pattern = DEVICE_CODE_PATTERN

    def __init__(self, coordinator: DuoFernCoordinator, system_code_hex: str) -> None:
        """Initialize the pair code text input."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{system_code_hex}_pair_code_input"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, system_code_hex)})
        self._current_value: str = ""

    @property
    def native_value(self) -> str:
        """Return the current code value."""
        return self._current_value

    async def async_set_value(self, value: str) -> None:
        """Store and validate the entered code.

        HA enforces the pattern on the frontend, but we also validate here
        as a safety net and normalise to uppercase.
        """
        value = value.upper().strip()
        if not re.match(r"^[0-9A-Fa-f]{6}$", value):
            _LOGGER.warning(
                "Invalid device code entered: %r — must be exactly 6 hex characters",
                value,
            )
            return
        self._current_value = value
        self.async_write_ha_state()
