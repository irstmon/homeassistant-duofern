"""Binary sensor platform for DuoFern motion, smoke, contact and obstacle sensors.

Two types of binary sensor entities are created:

1. Event-based sensors (motion, smoke, contact):
   Devices: 0x65 Bewegungsmelder, 0xAB Rauchmelder, 0xAC Fenster-Tuer-Kontakt
   These fire sensor events and are updated via the duofern_event bus.

   From 30_DUOFERN.pm %sensorMsg:
     0720 startMotion  -> True    (Bewegungsmelder)
     0721 endMotion    -> False
     071E startSmoke   -> True    (Rauchmelder)
     071F endSmoke     -> False
     0723 opened       -> True    (Fensterkontakt)
     0724 closed       -> False
     0725 startVibration -> True
     0726 endVibration   -> False

2. Status-based obstacle sensors (SX5 garage door only):
   Device: 0x4E SX5
   These are read from each status frame and create three separate entities:
     - obstacle      (BinarySensorDeviceClass.PROBLEM)
     - block         (BinarySensorDeviceClass.PROBLEM)
     - lightCurtain  (BinarySensorDeviceClass.SAFETY)

   These are FULLY TRIGGERABLE in HA automations:
     Trigger type: State
     Entity: "DuoFern SX5 (xxxxxx) — Obstacle" / "Block" / "Light Curtain"

   From 30_DUOFERN.pm format "24a" (SX5):
     obstacle, block, lightCurtain in %statusIds.
     When obstacle/block is set, the garage door has detected an obstruction.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DUOFERN_EVENT, DuoFernCoordinator, DuoFernDeviceState

_LOGGER = logging.getLogger(__name__)

# Map duofern event names to binary on/off state
# From %sensorMsg in 30_DUOFERN.pm
_EVENT_TO_STATE: dict[str, bool] = {
    "startMotion": True,
    "endMotion": False,
    "startSmoke": True,
    "endSmoke": False,
    "startRain": True,
    "endRain": False,
    "startVibration": True,
    "endVibration": False,
    "opened": True,  # Fensterkontakt: open = True
    "closed": False,
}

# Device class per device type byte
_DEVICE_CLASS_FOR_TYPE: dict[int, BinarySensorDeviceClass] = {
    0x65: BinarySensorDeviceClass.MOTION,
    0xAB: BinarySensorDeviceClass.SMOKE,
    0xAC: BinarySensorDeviceClass.OPENING,
}

# SX5 obstacle/block/lightCurtain entities
# key -> (translation_key, device_class, icon)
# Generic obstacle/block sensors for all covers with obstacle detection
# (Rohrmotor 0x49, Rohrmotor-Aktor 0x42, SX5 0x4E, Troll 0x4C/0x70 etc.)
_COVER_OBSTACLE_SENSORS: dict[str, tuple[str, BinarySensorDeviceClass, str]] = {
    "obstacle": (
        "cover_obstacle",
        BinarySensorDeviceClass.PROBLEM,
        "mdi:alert-circle",
    ),
    "block": (
        "cover_block",
        BinarySensorDeviceClass.PROBLEM,
        "mdi:garage-alert",
    ),
}

# SX5-only: light curtain sensor
_SX5_OBSTACLE_SENSORS: dict[str, tuple[str, BinarySensorDeviceClass, str]] = {
    "lightCurtain": (
        "sx5_light_curtain",
        BinarySensorDeviceClass.SAFETY,
        "mdi:motion-sensor",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern binary sensor entities.

    Creates:
      - One event-based BinarySensor per motion/smoke/contact device
      - Three status-based BinarySensors per SX5 (obstacle, block, lightCurtain)
    """
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []
    for hex_code, device_state in coordinator.data.devices.items():
        # Event-based sensors
        if device_state.device_code.is_binary_sensor:
            if device_state.device_code.device_type == 0xAC:
                # Fenster-Tuer-Kontakt: two separate entities for opened vs tilted
                for sensor_type, trans_key in (
                    ("opened", "window_opened"),
                    ("tilted", "window_tilted"),
                ):
                    entities.append(
                        DuoFernWindowSensor(
                            coordinator=coordinator,
                            device_state=device_state,
                            hex_code=hex_code,
                            sensor_type=sensor_type,
                            translation_key=trans_key,
                        )
                    )
                _LOGGER.debug(
                    "Adding window sensor entities (opened+tilted) for device %s",
                    hex_code,
                )
            else:
                entities.append(
                    DuoFernBinarySensor(
                        coordinator=coordinator,
                        device_state=device_state,
                        hex_code=hex_code,
                    )
                )
                _LOGGER.debug("Adding binary sensor entity for device %s", hex_code)

        # Obstacle/block sensors for all covers with detection hardware
        if device_state.device_code.is_obstacle_cover:
            for reading_key, (
                trans_key,
                dev_class,
                icon,
            ) in _COVER_OBSTACLE_SENSORS.items():
                entities.append(
                    DuoFernObstacleSensor(
                        coordinator=coordinator,
                        device_state=device_state,
                        hex_code=hex_code,
                        reading_key=reading_key,
                        translation_key=trans_key,
                        device_class=dev_class,
                        icon=icon,
                    )
                )
            # SX5 additionally has a light curtain sensor
            if device_state.device_code.device_type == 0x4E:
                for reading_key, (
                    trans_key,
                    dev_class,
                    icon,
                ) in _SX5_OBSTACLE_SENSORS.items():
                    entities.append(
                        DuoFernObstacleSensor(
                            coordinator=coordinator,
                            device_state=device_state,
                            hex_code=hex_code,
                            reading_key=reading_key,
                            translation_key=trans_key,
                            device_class=dev_class,
                            icon=icon,
                        )
                    )
            _LOGGER.debug(
                "Adding obstacle/block sensors for cover %s",
                hex_code,
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern binary sensor entities", len(entities))


# ---------------------------------------------------------------------------
# Event-based binary sensors (motion, smoke, contact)
# ---------------------------------------------------------------------------


class DuoFernBinarySensor(CoordinatorEntity[DuoFernCoordinator], BinarySensorEntity):
    """A DuoFern motion/smoke/contact sensor as a HA BinarySensorEntity.

    State is updated via HA event bus (duofern_event) because these devices
    only send events — not periodic status frames.

    From 30_DUOFERN.pm:
      #Wandtaster, Funksender UP, Handsender, Sensoren
      Events dispatched via DUOFERN_Parse -> Dispatch -> here.
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}"
        self._is_on: bool | None = None
        self._attr_device_class = _DEVICE_CLASS_FOR_TYPE.get(
            self._device_code.device_type,
            BinarySensorDeviceClass.MOTION,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to DuoFern events on the HA event bus."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(DUOFERN_EVENT, self._handle_duofern_event)
        )

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        return self._device_state is not None

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return battery info.

        From 30_DUOFERN.pm: #Sensoren Batterie (0FFF1323...)
          batteryState: ok | low
          batteryPercent: 0-100
        """
        state = self._device_state
        if state is None:
            return {}
        attrs: dict[str, Any] = {}
        if state.battery_state is not None:
            attrs["battery_state"] = state.battery_state
        if state.battery_percent is not None:
            attrs["battery_percent"] = state.battery_percent
        if state.last_seen is not None:
            attrs["last_seen"] = state.last_seen
        return attrs

    @callback
    def _handle_duofern_event(self, event: Event) -> None:
        """Handle a duofern_event for this device.

        Maps event names to binary on/off using _EVENT_TO_STATE.
        """
        data = event.data
        if data.get("device_code") != self._hex_code:
            return

        event_name: str = data.get("event", "")
        new_state = _EVENT_TO_STATE.get(event_name)
        if new_state is not None:
            self._is_on = new_state
            self.async_write_ha_state()
            _LOGGER.debug(
                "Binary sensor %s: %s -> %s",
                self._hex_code,
                event_name,
                new_state,
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=(f"DuoFern {self._device_code.device_type_name} ({self._hex_code})"),
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=self._hex_code,
            sw_version=state.status.version if state else None,
            via_device=(DOMAIN, self.coordinator.system_code.hex),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        if state and state.status.version:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
            if device and device.sw_version != state.status.version:
                device_reg.async_update_device(
                    device.id, sw_version=state.status.version
                )
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Fenster-Tuer-Kontakt (0xAC) — two entities: opened and tilted
# ---------------------------------------------------------------------------


class DuoFernWindowSensor(CoordinatorEntity[DuoFernCoordinator], BinarySensorEntity):
    """A single binary sensor for the DuoFern Fenster-Tuer-Kontakt (0xAC).

    Two instances are created per device:
      - "opened":  on=True only for 'opened' event  (FHEM state 'on')
      - "tilted":  on=True only for 'tilted' event  (FHEM state 'tilted')

    From 30_DUOFERN.pm:
      0723 opened  -> state="on"     (sensorMsg)
      0724 closed  -> state="off"    (sensorMsg)
      AC + byte14=FE -> state="tilted"
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    # Events that set this specific instance to True/False
    _EVENTS_ON: dict[str, set[str]] = {
        "opened": {"opened"},
        "tilted": {"tilted"},
    }
    _EVENTS_OFF: set[str] = {"closed"}

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        sensor_type: str,  # "opened" or "tilted"
        translation_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._sensor_type = sensor_type
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{sensor_type}"
        self._is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to DuoFern events on the HA event bus."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(DUOFERN_EVENT, self._handle_duofern_event)
        )

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        return self._device_state is not None

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._device_state
        if state is None:
            return {}
        attrs: dict[str, Any] = {}
        if state.battery_state is not None:
            attrs["battery_state"] = state.battery_state
        if state.battery_percent is not None:
            attrs["battery_percent"] = state.battery_percent
        if state.last_seen is not None:
            attrs["last_seen"] = state.last_seen
        return attrs

    @callback
    def _handle_duofern_event(self, event: Event) -> None:
        """Handle duofern_event — react only to relevant events for this instance."""
        data = event.data
        if data.get("device_code") != self._hex_code:
            return

        event_name: str = data.get("event", "")
        my_on_events = self._EVENTS_ON[self._sensor_type]

        if event_name in my_on_events:
            self._is_on = True
            self.async_write_ha_state()
        elif event_name in self._EVENTS_OFF:
            self._is_on = False
            self.async_write_ha_state()
        # Other events (e.g. the sibling opened/tilted) are ignored

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=(f"DuoFern {self._device_code.device_type_name} ({self._hex_code})"),
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=self._hex_code,
            sw_version=state.status.version if state else None,
            via_device=(DOMAIN, self.coordinator.system_code.hex),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        if state and state.status.version:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
            if device and device.sw_version != state.status.version:
                device_reg.async_update_device(
                    device.id, sw_version=state.status.version
                )
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Cover obstacle / block / lightCurtain binary sensors
# ---------------------------------------------------------------------------


class DuoFernObstacleSensor(CoordinatorEntity[DuoFernCoordinator], BinarySensorEntity):
    """A status-frame-based binary sensor for SX5 obstacle detection.

    These entities are read directly from the SX5 status frame (format 24a)
    and updated push-based via the coordinator whenever a status frame arrives.

    They are FULLY TRIGGERABLE in HA automations as State triggers:
      - obstacle:     True when SX5 detected an obstacle during movement
      - block:        True when SX5 is blocked
      - lightCurtain: True when the light curtain (safety sensor) is active

    This enables automations like:
      Trigger: state of "DuoFern SX5 (xxxxxx) — Obstacle" changes to "on"
      Action: open garage door / send notification

    From 30_DUOFERN.pm %statusIds format "24a":
      obstacle, block, lightCurtain readings in the status frame.
    The coordinator fires these as duofern_events AND stores them in
    device state readings for persistent display.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        reading_key: str,
        translation_key: str,
        device_class: BinarySensorDeviceClass,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._reading_key = reading_key
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{reading_key}"
        self._attr_translation_key = translation_key
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hex_code)},
        )

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        state = self._device_state
        if state is None:
            return False
        return state.available and self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        """Return True if this sensor is active (obstacle/block/curtain detected).

        Value is read from ParsedStatus.readings, updated on each status frame.
        """
        state = self._device_state
        if state is None:
            return None
        val = state.status.readings.get(self._reading_key)
        if val is None:
            return None
        # FHEM stores these as "on"/"off" strings after onOff mapping
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("on", "1", "true", "yes")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, including firmware version when available."""
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=(f"DuoFern {self._device_code.device_type_name} ({self._hex_code})"),
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=self._hex_code,
            sw_version=state.status.version if state else None,
            via_device=(DOMAIN, self.coordinator.system_code.hex),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        if state and state.status.version:
            device_reg = dr.async_get(self.hass)
            device = device_reg.async_get_device(identifiers={(DOMAIN, self._hex_code)})
            if device and device.sw_version != state.status.version:
                device_reg.async_update_device(
                    device.id, sw_version=state.status.version
                )
        self.async_write_ha_state()
