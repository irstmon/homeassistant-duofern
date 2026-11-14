"""Select platform for DuoFern multi-option device settings.

Exposes settings that have discrete options (not on/off, not sliders):
  motorDeadTime:   off / short / long           (Troll, Rohrmotor Steuerung)
  windDirection:   up / down                    (Troll, RolloTube)
  rainDirection:   up / down                    (Troll, RolloTube)
  automaticClosing: off / 30 / 60 / ... / 240s  (SX5)
  openSpeed:       11 / 15 / 19 (seconds)       (SX5)

All are placed in entity_category=CONFIG so they appear in the
"Configuration" section of the device card, not the main dashboard.

From 30_DUOFERN.pm %commands and set definitions:
  motorDeadTime:off,short,long
  windDirection:up,down  / rainDirection:up,down
  automaticClosing:off,30,60,90,120,150,180,210,240
  openSpeed:11,15,19

Note: actTempLimit (Raumthermostat) is exposed as four button entities
in button.py instead of a select, to avoid the 'always unknown' state
problem caused by the device not echoing the selected value back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuoFernSelectDescription(SelectEntityDescription):
    """Extends SelectEntityDescription with device type filter and command."""

    reading_key: str = ""
    device_types: frozenset[int] = frozenset()
    # Async method name on coordinator, signature: (device_code, value)
    coordinator_method: str = ""
    # When set, only create this entity for the matching sub-channel.
    # None (default) → no restriction; existing descriptions are unaffected.
    # Used for 0x69 Umweltsensor to keep config selects on "00" and actor
    # selects on "01".
    channel_filter: str | None = None
    # (reading value, option) pairs for readings whose decoded text differs
    # from the option name used in the UI and in the set command. Readings
    # not listed here are used as they are.
    reading_to_option: tuple[tuple[str, str], ...] = ()


# All select entities keyed by (description.key)
SELECT_DESCRIPTIONS: tuple[DuoFernSelectDescription, ...] = (
    # --- Covers (Troll / RolloTube / Rohrmotor Steuerung) ---
    DuoFernSelectDescription(
        key="motorDeadTime",
        translation_key="motor_dead_time",
        reading_key="motorDeadTime",
        name="Motor Dead Time",
        options=["off", "short", "long"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-pause",
        device_types=frozenset({0x42, 0x47, 0x4B, 0x4C, 0x70}),
        coordinator_method="async_set_motor_dead_time",
        # The status reading uses FHEM's %statusMapping "motor" texts
        # ("off", "short(160ms)", "long(480ms)", "individual"), the set
        # command uses off/short/long. Without this mapping the entity showed
        # "unknown" whenever the device reported short or long.
        reading_to_option=(("short(160ms)", "short"), ("long(480ms)", "long")),
    ),
    DuoFernSelectDescription(
        key="windDirection",
        translation_key="wind_direction",
        reading_key="windDirection",
        name="Wind Direction",
        options=["up", "down"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-down",
        device_types=frozenset({0x42, 0x47, 0x49, 0x4B, 0x4C, 0x70}),
        coordinator_method="async_set_wind_direction",
    ),
    DuoFernSelectDescription(
        key="rainDirection",
        translation_key="rain_direction",
        reading_key="rainDirection",
        name="Rain Direction",
        options=["up", "down"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-down",
        device_types=frozenset({0x42, 0x47, 0x49, 0x4B, 0x4C, 0x70}),
        coordinator_method="async_set_rain_direction",
    ),
    # --- SX5 ---
    DuoFernSelectDescription(
        key="automaticClosing",
        translation_key="automatic_closing",
        reading_key="automaticClosing",
        name="Automatic Closing",
        options=["off", "30", "60", "90", "120", "150", "180", "210", "240"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer",
        device_types=frozenset({0x4E}),
        coordinator_method="async_set_automatic_closing",
    ),
    DuoFernSelectDescription(
        key="openSpeed",
        translation_key="open_speed",
        reading_key="openSpeed",
        name="Open Speed (s)",
        options=["11", "15", "19"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:speedometer",
        device_types=frozenset({0x4E}),
        coordinator_method="async_set_open_speed",
    ),
    # --- Umweltsensor channel "00": transmit interval ---
    # Comes from the getConfig register decode (reg7 byte 0); must only
    # appear on the "00" (weather station) sub-channel.
    DuoFernSelectDescription(
        key="interval",
        translation_key="interval",
        reading_key="interval",
        name="Transmit Interval",
        options=[
            "off",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "15",
            "20",
            "30",
            "40",
            "50",
            "60",
            "70",
            "80",
            "90",
            "100",
        ],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-outline",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_umweltsensor_interval",
        channel_filter="00",
    ),
    # --- Umweltsensor channel "01" (actor): wind/rain movement direction ---
    # From 30_DUOFERN.pm %setsUmweltsensor01 — same options and commands as
    # the existing windDirection/rainDirection selects on Troll covers.
    DuoFernSelectDescription(
        key="windDirection",
        translation_key="wind_direction",
        reading_key="windDirection",
        name="Wind Direction",
        options=["up", "down"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-down",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_wind_direction",
        channel_filter="01",
    ),
    DuoFernSelectDescription(
        key="rainDirection",
        translation_key="rain_direction",
        reading_key="rainDirection",
        name="Rain Direction",
        options=["up", "down"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-down",
        device_types=frozenset({0x69}),
        coordinator_method="async_set_rain_direction",
        channel_filter="01",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern select entities."""
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[DuoFernSelect] = []
    for hex_code, device_state in coordinator.data.devices.items():
        dev_type = device_state.device_code.device_type
        for desc in SELECT_DESCRIPTIONS:
            if dev_type in desc.device_types:
                # channel_filter=None → no restriction (all existing descriptions).
                # channel_filter set → only create for the matching sub-channel.
                # Used for 0x69 Umweltsensor only; no other device type is affected.
                if (
                    desc.channel_filter is None
                    or device_state.channel == desc.channel_filter
                ):
                    entities.append(
                        DuoFernSelect(coordinator, device_state, hex_code, desc)
                    )

    # Umweltsensor (0x69) channel "00": structured trigger GUI.
    # One Grenzwert 1-5 selector per group (Wind/Temperatur/Dawn/Dusk/Sonne),
    # plus the Homepilot-confirmed discrete-value selects (sunDirection
    # Bereich, sunHeight Zielhöhe, sunHeight Bereich). See coordinator.py's
    # "Structured per-Grenzwert GUI" section for the underlying data model.
    for hex_code, device_state in coordinator.data.devices.items():
        if (
            device_state.device_code.device_type == 0x69
            and device_state.channel == "00"
        ):
            for group in ("wind", "temperature", "dawn", "dusk", "sun"):
                entities.append(
                    DuoFernGrenzwertSelector(coordinator, device_state, hex_code, group)
                )
            entities.append(
                DuoFernSunDirectionAngleSelect(coordinator, device_state, hex_code)
            )
            entities.append(
                DuoFernSunDirectionWidthSelect(coordinator, device_state, hex_code)
            )
            entities.append(
                DuoFernSunHeightTargetSelect(coordinator, device_state, hex_code)
            )
            entities.append(
                DuoFernSunHeightWidthSelect(coordinator, device_state, hex_code)
            )

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        ("select", e._attr_unique_id) for e in entities if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern select entities", len(entities))


class DuoFernSelect(CoordinatorEntity[DuoFernCoordinator], SelectEntity, RestoreEntity):
    """A DuoFern multi-option configuration setting as a SelectEntity.

    The current value is read from the device's status readings (as set by
    parse_status() in protocol.py). Changing the value sends the corresponding
    command from %commands in 30_DUOFERN.pm.

    Uses RestoreEntity so that after an HA restart the last known value is
    shown immediately instead of 'unknown', until the first live status frame
    arrives from the device.
    """

    entity_description: DuoFernSelectDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        description: DuoFernSelectDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{description.key}"
        self._attr_options = list(description.options)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})
        self._restored_option: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known option for display until first live frame arrives."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            self._restored_option = last_state.state

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        """Return True only if device is present AND last coordinator update succeeded.

        Without the last_update_success check, the select entity would appear
        available even when the serial connection is down — because device state
        objects remain in coordinator.data between reconnects.
        """
        if not self.coordinator.last_update_success:
            return False
        state = self._device_state
        return state is not None and state.available

    @property
    def current_option(self) -> str | None:
        """Return current option read from device status, with restored fallback."""
        state = self._device_state
        if state is not None:
            val = state.status.readings.get(self.entity_description.reading_key)
            if val is not None:
                live = str(val)
                live = dict(self.entity_description.reading_to_option).get(live, live)
                self._restored_option = live  # keep in sync for next restart
                return live
        return self._restored_option

    async def async_select_option(self, option: str) -> None:
        """Send the selected option to the device."""
        method = getattr(self.coordinator, self.entity_description.coordinator_method)
        await method(self._device_code, option)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Structured trigger GUI — Umweltsensor 0x69 channel "00"
# ---------------------------------------------------------------------------
#
# One Grenzwert 1-5 selector per trigger group, plus the Homepilot-confirmed
# discrete-value selects (angle/width options that only ever take specific
# fixed values, per @geraldeberle1234's Homepilot screenshots). All other trigger
# values (continuous ranges, or unconfirmed ranges) are Number entities in
# number.py instead — see NOTES.md for the min/max/step source per field.


class DuoFernGrenzwertSelector(CoordinatorEntity[DuoFernCoordinator], SelectEntity):
    """Picks which of the up to 5 Grenzwerte (trigger slots) is currently
    shown/edited by the other entities in this group (Number/Switch).

    Purely a local HA UI concept — not stored on the device. Changing this
    just changes what coordinator.selected_grenzwert[group] points at; the
    dependent Number/Switch entities re-read/re-render via the coordinator
    update this triggers.
    """

    _attr_has_entity_name = True
    _attr_options = ["1", "2", "3", "4", "5"]
    _attr_icon = "mdi:numeric"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        group: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._group = group
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{group}_grenzwert_select"
        # Deliberately NO explicit _attr_name — see
        # DuoFernActiveGrenzwerteSensor in sensor.py for why (setting both
        # translation_key and name blocks the translation lookup entirely).
        self._attr_translation_key = f"{group}_grenzwert"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and self.coordinator.last_update_success

    @property
    def current_option(self) -> str:
        state = self._device_state
        if state is None:
            return "1"
        return str(state.selected_grenzwert.get(self._group, 1))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_selected_grenzwert(
            self._device_code, self._group, int(option)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class DuoFernSunDirectionAngleSelect(
    CoordinatorEntity[DuoFernCoordinator], SelectEntity
):
    """Sonnenrichtung "Zielrichtung" — confirmed discrete values from Homepilot:
    22.5/45/67.5/90/112.5/135/157.5/180/202.5/225/247.5/270/292.5/315°.

    Originally built as a continuous Number (0-337.5° in 22.5° steps) because
    the exact valid set wasn't confirmed yet. @geraldeberle1234 confirmed the real
    Homepilot dropdown only offers these 14 fixed values — notably NOT 0° and
    NOT 337.5°, which a naive "0 to 337.5 step 22.5" range would have wrongly
    allowed. Converted to Select to make invalid values unselectable, matching
    the same pattern already used for Bereich/Zielhöhe.

    Keeps the current "Bereich" (width) unchanged when only the angle is
    adjusted, since the device encodes both in the same byte and always needs
    both written together.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sun_direction_angle"
    # Deliberately NO explicit _attr_name — see DuoFernActiveGrenzwerteSensor
    # in sensor.py for why (setting both translation_key and name blocks
    # the translation lookup entirely).
    _attr_icon = "mdi:compass-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [
        "22.5",
        "45",
        "67.5",
        "90",
        "112.5",
        "135",
        "157.5",
        "180",
        "202.5",
        "225",
        "247.5",
        "270",
        "292.5",
        "315",
    ]

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_sun_direction_angle"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def _slot(self) -> int:
        state = self._device_state
        return state.selected_grenzwert.get("sun", 1) if state else 1

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and self.coordinator.last_update_success

    @property
    def current_option(self) -> str:
        _, angle, _ = self.coordinator.get_trigger_sun_direction_slot(
            self._device_code, self._slot
        )
        # Snap to the nearest confirmed option — the register can technically
        # hold any of the 16 raw angle_idx slots, but only these 14 are ever
        # written by this entity or by Homepilot itself.
        formatted = f"{angle:g}"
        return (
            formatted
            if formatted in self._attr_options
            else min(self._attr_options, key=lambda o: abs(float(o) - angle))
        )

    async def async_select_option(self, option: str) -> None:
        _, _, width = self.coordinator.get_trigger_sun_direction_slot(
            self._device_code, self._slot
        )
        await self.coordinator.async_set_trigger_sun_direction_slot_value(
            self._device_code, self._slot, float(option), width
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class DuoFernSunDirectionWidthSelect(
    CoordinatorEntity[DuoFernCoordinator], SelectEntity
):
    """Sonnenrichtung "Bereich" — confirmed discrete values from Homepilot: 0/45/90/135/180°.

    Reads/writes whichever Grenzwert is currently selected for the "sun"
    group (shared selector with the other Sonne fields). Changing this keeps
    the current angle unchanged — both values are always written together
    since the device encodes them in the same byte.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sun_direction_width"
    _attr_icon = "mdi:angle-acute"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["0", "45", "90", "135", "180"]

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_sun_direction_width"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def _slot(self) -> int:
        state = self._device_state
        return state.selected_grenzwert.get("sun", 1) if state else 1

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and self.coordinator.last_update_success

    @property
    def current_option(self) -> str:
        _, _, width = self.coordinator.get_trigger_sun_direction_slot(
            self._device_code, self._slot
        )
        return str(int(width))

    async def async_select_option(self, option: str) -> None:
        _, angle, _ = self.coordinator.get_trigger_sun_direction_slot(
            self._device_code, self._slot
        )
        await self.coordinator.async_set_trigger_sun_direction_slot_value(
            self._device_code, self._slot, angle, float(option)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class DuoFernSunHeightTargetSelect(CoordinatorEntity[DuoFernCoordinator], SelectEntity):
    """Sonnenhöhe "Zielhöhe" — confirmed discrete values from Homepilot: 13/26/39/52/65/78°."""

    _attr_has_entity_name = True
    _attr_translation_key = "sun_height_target"
    _attr_icon = "mdi:angle-acute"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["13", "26", "39", "52", "65", "78"]

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_sun_height_target"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def _slot(self) -> int:
        state = self._device_state
        return state.selected_grenzwert.get("sun", 1) if state else 1

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and self.coordinator.last_update_success

    @property
    def current_option(self) -> str:
        _, from_angle, _ = self.coordinator.get_trigger_sun_height_slot(
            self._device_code, self._slot
        )
        return str(int(from_angle))

    async def async_select_option(self, option: str) -> None:
        _, _, width = self.coordinator.get_trigger_sun_height_slot(
            self._device_code, self._slot
        )
        await self.coordinator.async_set_trigger_sun_height_slot_value(
            self._device_code, self._slot, float(option), width
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class DuoFernSunHeightWidthSelect(CoordinatorEntity[DuoFernCoordinator], SelectEntity):
    """Sonnenhöhe "Bereich" — confirmed discrete values from Homepilot: 0/26/52°."""

    _attr_has_entity_name = True
    _attr_translation_key = "sun_height_width"
    _attr_icon = "mdi:angle-acute"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["0", "26", "52"]

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_sun_height_width"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def _slot(self) -> int:
        state = self._device_state
        return state.selected_grenzwert.get("sun", 1) if state else 1

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and self.coordinator.last_update_success

    @property
    def current_option(self) -> str:
        _, _, width = self.coordinator.get_trigger_sun_height_slot(
            self._device_code, self._slot
        )
        return str(int(width))

    async def async_select_option(self, option: str) -> None:
        _, from_angle, _ = self.coordinator.get_trigger_sun_height_slot(
            self._device_code, self._slot
        )
        await self.coordinator.async_set_trigger_sun_height_slot_value(
            self._device_code, self._slot, from_angle, float(option)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
