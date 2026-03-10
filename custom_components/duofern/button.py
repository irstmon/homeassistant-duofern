"""Button platform for DuoFern.

Stick control buttons (appear on the Stick device card):
  - "Start pairing"    (60s pairing window, auto-stop)
  - "Start unpairing"  (60s unpairing window, auto-stop)
  - "Status Broadcast" (broadcast status request to all paired devices)

Cover dusk/dawn buttons (appear on each cover device card):
  - "Dusk position"    Move to the device's programmed dusk position
  - "Dawn position"    Move to the device's programmed dawn position

  dusk/dawn positions are NOT the same as duskAutomatic/dawnAutomatic
  (which toggle automation). These buttons explicitly command the device
  to move to its programmed position — typically slower and quieter
  than a direct position command.

  From 30_DUOFERN.pm:
    dusk => {cmd => {noArg => "070901FF000000000000"}}
    dawn => {cmd => {noArg => "071301FF000000000000"}}

  FHEM equivalents: set ROLLONAME dusk / set ROLLONAME dawn

  In FHEM, dusk/dawn are part of %setsBasic (all covers) and
  %setsSX5 (SX5 garage), and %setsDimmer (dimmers).
  In HA they appear as Buttons on the respective device card.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernData
from .protocol import DuoFernId

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern button entities.

    Creates:
      - 3 stick control buttons (pairing, unpairing, status broadcast)
      - 2 dusk/dawn buttons per cover device
    """
    coordinator: DuoFernCoordinator = entry.runtime_data
    system_code_hex = coordinator.system_code.hex

    entities: list[ButtonEntity] = [
        DuoFernPairButton(coordinator, system_code_hex),
        DuoFernUnpairButton(coordinator, system_code_hex),
        DuoFernStatusButton(coordinator, system_code_hex),
    ]

    # Add dusk/dawn/toggle buttons for every cover device
    for hex_code, device_state in coordinator.data.devices.items():
        dc = (
            device_state.device_code.with_channel(device_state.channel)
            if device_state.channel
            else device_state.device_code
        )
        if dc.is_cover:
            entities.append(DuoFernDuskButton(coordinator, dc))
            entities.append(DuoFernDawnButton(coordinator, dc))
            entities.append(DuoFernToggleButton(coordinator, dc))

    # Reset buttons for all actuators (covers, switches, dimmers)
    # remotePair/remoteUnpair for all
    for hex_code, device_state in coordinator.data.devices.items():
        dev_code = (
            device_state.device_code.with_channel(device_state.channel)
            if device_state.channel
            else device_state.device_code
        )
        dev_type = dev_code.device_type

        # reset:settings,full for all devices that support it
        # From 30_DUOFERN.pm %setsBasic / %setsReset: covers, switches, dimmers
        # 0xE1 Heizkörperantrieb uses %setsHSA which has no reset commands
        if (
            dev_code.is_cover
            or dev_code.is_switch
            or dev_code.is_light
            or (dev_code.is_climate and dev_code.device_type != 0xE1)
        ):
            entities.append(DuoFernResetSettingsButton(coordinator, dev_code))
            entities.append(DuoFernResetFullButton(coordinator, dev_code))

        # remotePair/remoteUnpair — not for remotes, env/binary sensors, or 0xE1 HSA
        # Binary sensors (0xAB Rauchmelder, 0xAC Fensterkontakt, 0x65 Bewegungsmelder)
        # are pure event senders with no set commands in FHEM, same as remotes.
        # 0xE1 Heizkörperantrieb uses %setsHSA which has no remotePair commands.
        if (
            not dev_code.is_remote
            and not dev_code.is_env_sensor
            and not dev_code.is_binary_sensor
            and dev_code.device_type != 0xE1
        ):
            entities.append(DuoFernRemotePairButton(coordinator, dev_code))
            entities.append(DuoFernRemoteUnpairButton(coordinator, dev_code))
            entities.append(DuoFernRemoteStopButton(coordinator, dev_code))

        # tempUp/tempDown only for 0x73 Raumthermostat (in %setsThermostat).
        # NOT for 0xE1 HSA — that device uses the climate entity slider via
        # the HSA pending protocol instead.
        if dev_code.device_type == 0x73:
            entities.append(DuoFernTempUpButton(coordinator, dev_code))
            entities.append(DuoFernTempDownButton(coordinator, dev_code))

    # Per-device getStatus buttons for all actuators
    for hex_code, device_state in coordinator.data.devices.items():
        dev_code = (
            device_state.device_code.with_channel(device_state.channel)
            if device_state.channel
            else device_state.device_code
        )
        dev_type = dev_code.device_type
        # getStatus for all actuators (from %commandsStatus)
        # Remotes, env/binary sensors, and 0xE1 have no getStatus in FHEM.
        # Binary sensors (0xAB/0xAC/0x65) are battery-powered event senders only.
        if (
            not dev_code.is_remote
            and not dev_code.is_env_sensor
            and not dev_code.is_binary_sensor
            and dev_code.device_type != 0xE1
        ):
            entities.append(DuoFernGetStatusButton(coordinator, dev_code))

        # Umweltsensor 00 channel: getWeather, getTime, getConfig, writeConfig, setTime
        if (
            dev_type == 0x69
            and hasattr(dev_code, "channel")
            and str(getattr(dev_code, "channel", "")) == "00"
        ):
            entities.append(DuoFernGetWeatherButton(coordinator, dev_code))
            entities.append(DuoFernGetTimeButton(coordinator, dev_code))
            entities.append(DuoFernGetConfigButton(coordinator, dev_code))
            entities.append(DuoFernWriteConfigButton(coordinator, dev_code))
            entities.append(DuoFernSetTimeButton(coordinator, dev_code))

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id")
    )
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Helper: device info for the stick
# ---------------------------------------------------------------------------


def _stick_device_info(
    coordinator: DuoFernCoordinator, system_code_hex: str
) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, system_code_hex)})


# ---------------------------------------------------------------------------
# Stick control buttons
# ---------------------------------------------------------------------------


class DuoFernPairButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Button to start 60s pairing window on the DuoFern stick."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_pairing"
    _attr_icon = "mdi:link-plus"

    def __init__(self, coordinator: DuoFernCoordinator, system_code_hex: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{system_code_hex}_pair"
        self._attr_device_info = _stick_device_info(coordinator, system_code_hex)

    @property
    def available(self) -> bool:
        """Only available when not already in pair/unpair mode."""
        if self.coordinator.data is None:
            return False
        d = self.coordinator.data
        return not d.pairing_active and not d.unpairing_active

    async def async_press(self) -> None:
        """Start 60s pairing window."""
        await self.coordinator.async_start_pairing()


class DuoFernUnpairButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Button to start 60s unpairing window on the DuoFern stick."""

    _attr_has_entity_name = True
    _attr_translation_key = "start_unpairing"
    _attr_icon = "mdi:link-off"

    def __init__(self, coordinator: DuoFernCoordinator, system_code_hex: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{system_code_hex}_unpair"
        self._attr_device_info = _stick_device_info(coordinator, system_code_hex)

    @property
    def available(self) -> bool:
        if self.coordinator.data is None:
            return False
        d = self.coordinator.data
        return not d.pairing_active and not d.unpairing_active

    async def async_press(self) -> None:
        """Start 60s unpairing window."""
        await self.coordinator.async_start_unpairing()


class DuoFernStatusButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Button to request fresh status from all paired DuoFern devices."""

    _attr_has_entity_name = True
    _attr_translation_key = "request_status"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: DuoFernCoordinator, system_code_hex: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{system_code_hex}_status"
        self._attr_device_info = _stick_device_info(coordinator, system_code_hex)

    async def async_press(self) -> None:
        """Send broadcast status request to all paired devices."""
        await self.coordinator.async_request_all_status()


# ---------------------------------------------------------------------------
# Cover dusk / dawn buttons
# ---------------------------------------------------------------------------


class DuoFernDuskButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Move a cover to its programmed dusk (closing) position.

    Dusk position is typically slower/quieter than position=0 because
    the device uses its programmed speed profile for dusk movement.

    From 30_DUOFERN.pm %commands:
      dusk => {cmd => {noArg => "070901FF000000000000"}}

    FHEM: set ROLLONAME dusk
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cover_dusk"
    _attr_icon = "mdi:weather-sunset-down"

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_dusk"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hex_code)},
        )

    async def async_press(self) -> None:
        """Command the cover to move to its dusk position."""
        await self.coordinator.async_cover_dusk(self._device_code)


class DuoFernDawnButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Move a cover to its programmed dawn (opening) position.

    Dawn position is the device's stored program for morning opening,
    typically with a specific speed profile.

    From 30_DUOFERN.pm %commands:
      dawn => {cmd => {noArg => "071301FF000000000000"}}

    FHEM: set ROLLONAME dawn
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cover_dawn"
    _attr_icon = "mdi:weather-sunset-up"

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_dawn"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hex_code)},
        )

    async def async_press(self) -> None:
        """Command the cover to move to its dawn position."""
        await self.coordinator.async_cover_dawn(self._device_code)


# ---------------------------------------------------------------------------
# Cover toggle button
# ---------------------------------------------------------------------------


class DuoFernToggleButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Toggle cover direction (reverse current movement / change direction).

    From 30_DUOFERN.pm: toggle => {cmd => {noArg => "071A0000000000000000"}}
    FHEM command: set DEVICENAME toggle
    """

    _attr_has_entity_name = True
    _attr_translation_key = "cover_toggle"
    _attr_icon = "mdi:swap-vertical"
    _attr_entity_category = None  # main action

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_toggle"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_cover_toggle(self._device_code)


# ---------------------------------------------------------------------------
# Reset buttons (settings / full) — CONFIG category
# ---------------------------------------------------------------------------


class DuoFernResetSettingsButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Reset device settings (keeps pairing).

    From 30_DUOFERN.pm: reset => {settings => "0815CB00000000000000"}
    FHEM command: set DEVICENAME reset settings
    """

    _attr_has_entity_name = True
    _attr_translation_key = "reset_settings"
    _attr_icon = "mdi:restore"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_reset_settings"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_reset(self._device_code, "settings")


class DuoFernResetFullButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Full factory reset of the device (loses pairing).

    From 30_DUOFERN.pm: reset => {full => "0815CC00000000000000"}
    FHEM command: set DEVICENAME reset full
    """

    _attr_has_entity_name = True
    _attr_translation_key = "reset_full"
    _attr_icon = "mdi:delete-forever"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_reset_full"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_reset(self._device_code, "full")


# ---------------------------------------------------------------------------
# Remote pair / unpair buttons (CONFIG category, for Handsender / Wandtaster)
# ---------------------------------------------------------------------------


class DuoFernRemotePairButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Initiate remote pairing with a Handsender or Wandtaster.

    From 30_DUOFERN.pm: remotePair => uses duoCommand2
    FHEM command: set DEVICENAME remotePair
    """

    _attr_has_entity_name = True
    _attr_translation_key = "remote_pair"
    _attr_icon = "mdi:remote"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_remote_pair"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_remote_pair(self._device_code)


class DuoFernRemoteUnpairButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Remove remote pairing with a Handsender or Wandtaster.

    From 30_DUOFERN.pm: remoteUnpair => uses duoCommand2
    FHEM command: set DEVICENAME remoteUnpair
    """

    _attr_has_entity_name = True
    _attr_translation_key = "remote_unpair"
    _attr_icon = "mdi:remote-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_remote_unpair"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_remote_unpair(self._device_code)


class DuoFernRemoteStopButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Stop remote pairing/unpairing mode on a device.

    OTA-verified 2026-03-10: f[2]=0x06, f[3]=0x03.
    Ends the pairing window early after a remotePair or remoteUnpair press.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "remote_stop"
    _attr_icon = "mdi:remote-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_remote_stop"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_remote_stop(self._device_code)


# ---------------------------------------------------------------------------
# Thermostat temp up / temp down buttons
# ---------------------------------------------------------------------------


class DuoFernTempUpButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Increment thermostat target temperature by one step.

    From 30_DUOFERN.pm: tempUp => {noArg => "0718tt00000000000000"}
    FHEM command: set DEVICENAME tempUp
    """

    _attr_has_entity_name = True
    _attr_translation_key = "temp_up"
    _attr_icon = "mdi:thermometer-plus"

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_temp_up"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_temp_up(self._device_code)


class DuoFernTempDownButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Decrement thermostat target temperature by one step.

    From 30_DUOFERN.pm: tempDown => {noArg => "0719tt00000000000000"}
    FHEM command: set DEVICENAME tempDown
    """

    _attr_has_entity_name = True
    _attr_translation_key = "temp_down"
    _attr_icon = "mdi:thermometer-minus"

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_code: DuoFernId,
    ) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_temp_down"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_temp_down(self._device_code)


# ---------------------------------------------------------------------------
# Per-device getStatus button
# ---------------------------------------------------------------------------


class DuoFernGetStatusButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Request current status from a single DuoFern device.

    From 30_DUOFERN.pm: getStatus => commandsStatus{getStatus} = "0F"
    Builds: 0DFF0F400000000000000000000000000000CCCCCC01
    FHEM command: set DEVICENAME getStatus
    """

    _attr_has_entity_name = True
    _attr_translation_key = "get_status"
    _attr_icon = "mdi:refresh-circle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DuoFernCoordinator, device_code: DuoFernId) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_get_status"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_get_status_device(self._device_code)


# ---------------------------------------------------------------------------
# Umweltsensor weather station buttons
# ---------------------------------------------------------------------------


class DuoFernGetWeatherButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Request weather data from Umweltsensor weather station.

    From 30_DUOFERN.pm: getWeather => commandsStatus{getWeather} = "13"
    FHEM command: set DEVICENAME getWeather
    """

    _attr_has_entity_name = True
    _attr_translation_key = "get_weather"
    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DuoFernCoordinator, device_code: DuoFernId) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_get_weather"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_get_weather(self._device_code)


class DuoFernGetTimeButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Request time from Umweltsensor.

    From 30_DUOFERN.pm: getTime => commandsStatus{getTime} = "10"
    FHEM command: set DEVICENAME getTime
    """

    _attr_has_entity_name = True
    _attr_translation_key = "get_time"
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DuoFernCoordinator, device_code: DuoFernId) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_get_time"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_get_time(self._device_code)


class DuoFernGetConfigButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Request configuration from Umweltsensor (register dump).

    From 30_DUOFERN.pm:
      getConfig => $duoWeatherConfig = "0D001B400000000000000000000000000000yyyyyy00"
    FHEM command: set DEVICENAME00 getConfig
    """

    _attr_has_entity_name = True
    _attr_translation_key = "get_config"
    _attr_icon = "mdi:cog-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DuoFernCoordinator, device_code: DuoFernId) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_get_config"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_get_weather_config(self._device_code)


class DuoFernSetTimeButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Sync current system time to Umweltsensor.

    From 30_DUOFERN.pm:
      time => $duoSetTime = "0D0110800001mmmmmmmmnnnnnn0000000000yyyyyy00"
    FHEM command: set DEVICENAME00 time
    """

    _attr_has_entity_name = True
    _attr_translation_key = "set_time"
    _attr_icon = "mdi:clock-check"

    def __init__(self, coordinator: DuoFernCoordinator, device_code: DuoFernId) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_set_time"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_set_time(self._device_code)


class DuoFernWriteConfigButton(CoordinatorEntity[DuoFernCoordinator], ButtonEntity):
    """Write all stored configuration registers to the Umweltsensor.

    From 30_DUOFERN.pm:
      writeConfig: reads .reg0-.reg7 readings and sends each as a register
      write frame using $duoWeatherWriteConfig.

    Use this after changing latitude, longitude, timezone, DCF, interval,
    or trigger settings to actually push them to the device.
    FHEM command: set DEVICENAME00 writeConfig
    """

    _attr_has_entity_name = True
    _attr_translation_key = "write_config"
    _attr_icon = "mdi:content-save-cog"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DuoFernCoordinator, device_code: DuoFernId) -> None:
        super().__init__(coordinator)
        self._device_code = device_code
        hex_code = device_code.full_hex
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_write_config"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    async def async_press(self) -> None:
        await self.coordinator.async_write_weather_config(self._device_code)
