"""Sensor platform for DuoFern weather and environment sensors.

Covers the following device types:
  0x69  Umweltsensor        (weather station: brightness, sun, temp, rain, wind)
  0xA5  Sonnensensor        (sun sensor: brightness only)
  0xA9  Sonnen-/Windsensor  (sun + wind)
  0xAA  Markisenwaechter    (awning controller sensor)

The Umweltsensor (0x69) has two sub-channels in FHEM:
  69xxxxxx00  — weather station (getWeather, getTime, getConfig)
  69xxxxxx01  — actor sub-device (windAutomatic, rainAutomatic, etc.)
              This channel appears as a cover with extra attributes.

Weather data arrives via is_weather_data() frames (0F..1322...).
From 30_DUOFERN.pm:
  #Umweltsensor Wetter
  Parsed in parse_weather_data() in protocol.py, stored in
  coordinator device state as individual readings.

All sensor types create individual SensorEntity instances per measurement:
  brightness     (lux)
  sunDirection   (°)
  sunHeight      (°)
  temperature    (°C)
  isRaining      (boolean -> binary_sensor handled separately via events)
  wind           (m/s)

Battery state is exposed as extra_state_attributes on all sensor entities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DuoFernConfigEntry
from .const import DOMAIN
from .coordinator import DuoFernCoordinator, DuoFernDeviceState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuoFernSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with the reading key."""

    reading_key: str = ""


# Sensor definitions for the Umweltsensor weather readings.
# From parse_weather_data() in protocol.py and 30_DUOFERN.pm #Umweltsensor Wetter.
SENSOR_DESCRIPTIONS: tuple[DuoFernSensorDescription, ...] = (
    DuoFernSensorDescription(
        key="brightness",
        reading_key="brightness",
        translation_key="brightness",
        name="Helligkeit",
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="lx",
    ),
    DuoFernSensorDescription(
        key="temperature",
        reading_key="temperature",
        translation_key="temperature",
        name="Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    DuoFernSensorDescription(
        key="wind",
        reading_key="wind",
        translation_key="wind_speed",
        name="Wind",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="m/s",
    ),
    DuoFernSensorDescription(
        key="sunDirection",
        reading_key="sunDirection",
        translation_key="sun_direction",
        name="Sonnenrichtung",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="°",
        icon="mdi:sun-compass",
    ),
    DuoFernSensorDescription(
        key="sunHeight",
        reading_key="sunHeight",
        translation_key="sun_height",
        name="Sonnenhöhe",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="°",
        icon="mdi:weather-sunny",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DuoFernConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DuoFern sensor entities.

    Creates one SensorEntity per measurement per sensor device.
    """
    coordinator: DuoFernCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []
    for hex_code, device_state in coordinator.data.devices.items():
        dev_code = device_state.device_code

        # Weather/environment sensor readings (Umweltsensor, Sonnensensor etc.)
        if dev_code.is_sensor:
            for description in SENSOR_DESCRIPTIONS:
                entities.append(
                    DuoFernSensor(
                        coordinator=coordinator,
                        device_state=device_state,
                        hex_code=hex_code,
                        description=description,
                    )
                )
                _LOGGER.debug(
                    "Adding sensor entity %s for device %s",
                    description.key,
                    hex_code,
                )

        # Battery sensor: created for every device type that is known to transmit
        # battery data — either via dedicated 0FFF1323 battery frames (binary
        # sensors 0xAB/0xAC/0x65) or embedded in regular status frames (0xE1
        # format 29 batteryPercent, 0x73 Raumthermostat).
        # Also created dynamically for any device that already has battery data
        # stored (handles unknown future device types that happen to send it).
        #
        # The entity uses RestoreEntity so the last known value survives a
        # restart without waiting for the next battery transmission.
        # Statically known battery senders:
        #   is_binary_sensor (0xAB/0xAC/0x65) always send 0FFF1323 battery frames.
        #   0xE1 Heizkörperantrieb embeds batteryPercent in every format-29 status frame.
        # 0x73 Raumthermostat is NOT included — it exists in both battery-powered and
        # 230V variants and FHEM has no device-type filter on battery frames either.
        # The fallback condition (battery_percent is not None) handles 0x73 and any
        # other device type dynamically: once a battery frame has been received and
        # stored by the coordinator, the entity is created on the next HA restart.
        _sends_battery = (
            dev_code.is_binary_sensor  # 0xAB, 0xAC, 0x65 — guaranteed 0FFF1323
            or dev_code.device_type == 0xE1  # format-29 embeds batteryPercent
            or device_state.battery_percent is not None  # seen at runtime from any type
        )
        if _sends_battery:
            entities.append(
                DuoFernBatterySensor(
                    coordinator=coordinator,
                    device_state=device_state,
                    hex_code=hex_code,
                )
            )
            _LOGGER.debug("Adding battery sensor for device %s", hex_code)

        # Valve position sensor for 0xE1 Heizkörperantrieb.
        # valvePosition is statusId 186 in format-29, range 0-100%.
        if dev_code.device_type == 0xE1:
            entities.append(
                DuoFernValveSensor(
                    coordinator=coordinator,
                    device_state=device_state,
                    hex_code=hex_code,
                )
            )

        # Boost sensor for 0xE1: only the start-timestamp (DIAGNOSTIC).
        # boost on/off → switch entity (boostActive reading)
        # boost duration → number entity (boostDuration reading)
        if dev_code.device_type == 0xE1:
            entities.append(
                DuoFernBoostStartSensor(
                    coordinator=coordinator,
                    device_state=device_state,
                    hex_code=hex_code,
                )
            )
        # Last-seen timestamp sensor for every known device.
        entities.append(
            DuoFernLastSeenSensor(
                coordinator=coordinator,
                device_state=device_state,
                hex_code=hex_code,
            )
        )

    # Register this platform's unique_ids centrally so __init__.py can
    # remove stale entities from previous integration versions.
    coordinator.data.registered_unique_ids.update(
        e._attr_unique_id for e in entities if hasattr(e, "_attr_unique_id")
    )
    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d DuoFern sensor entities", len(entities))


class DuoFernSensor(CoordinatorEntity[DuoFernCoordinator], SensorEntity):
    """A single measurement from a DuoFern weather/environment sensor.

    State is updated when the coordinator receives a weather data frame
    (0F..1322...) and calls async_set_updated_data().

    From 30_DUOFERN.pm:
      #Umweltsensor Wetter
      brightness, sunDirection, sunHeight, temperature, isRaining, wind
    """

    entity_description: DuoFernSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
        description: DuoFernSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_{description.key}"

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
        return (
            state.available
            and self.coordinator.last_update_success
            and self.entity_description.reading_key in state.status.readings
        )

    @property
    def native_value(self) -> float | None:
        """Return the sensor reading value.

        From coordinator weather data: stored in state.status.readings
        after parse_weather_data() in protocol.py.
        """
        state = self._device_state
        if state is None:
            return None
        val = state.status.readings.get(self.entity_description.reading_key)
        if val is None:
            return None
        try:
            return float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return battery and rain status as extra attributes.

        isRaining from the Umweltsensor is also available here as an attribute
        (the main rain binary sensor comes via the event bus).
        """
        state = self._device_state
        if state is None:
            return {}
        attrs: dict[str, Any] = {}
        is_raining = state.status.readings.get("isRaining")
        if is_raining is not None:
            attrs["is_raining"] = is_raining
        if state.battery_state is not None:
            attrs["battery_state"] = state.battery_state
        if state.battery_percent is not None:
            attrs["battery_level"] = state.battery_percent
        if state.last_seen is not None:
            attrs["last_seen"] = state.last_seen
        return attrs

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
# Battery sensor — works for all device types that transmit battery data
# ---------------------------------------------------------------------------


class DuoFernBatterySensor(
    CoordinatorEntity[DuoFernCoordinator], SensorEntity, RestoreEntity
):
    """A battery level sensor for any DuoFern device that transmits battery data.

    Battery data reaches us via two paths:
      1. Dedicated battery frame (0FFF1323) — binary sensors 0xAB/0xAC/0x65.
         Stored as DuoFernDeviceState.battery_percent / battery_state by the
         coordinator's _handle_battery_status().
      2. Embedded in regular status frames — 0xE1 Heizkörperantrieb (format 29,
         statusId 185) stores batteryPercent in ParsedStatus.readings.

    The entity merges both sources, preferring the dedicated battery fields.
    RestoreEntity ensures the last-known value is shown immediately after an
    HA restart without waiting for the next battery transmission.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_battery"
        self._restored_value: int | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known battery level from recorder on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None,
            "unknown",
            "unavailable",
        ):
            try:
                self._restored_value = int(float(last_state.state))
                _LOGGER.debug(
                    "Restored battery level %s%% for device %s",
                    self._restored_value,
                    self._hex_code,
                )
            except (ValueError, TypeError):
                pass

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        return self._device_state is not None

    @property
    def native_value(self) -> int | None:
        """Return battery percentage.

        Priority:
          1. Live value from DuoFernDeviceState.battery_percent (0FFF1323 frame)
          2. Live value from ParsedStatus.readings["batteryPercent"] (status frame)
          3. Restored value from HA recorder (survives restarts)
        """
        state = self._device_state
        if state is None:
            return self._restored_value

        # Source 1: dedicated battery frame
        if state.battery_percent is not None:
            return state.battery_percent

        # Source 2: embedded in status readings (e.g. 0xE1 format 29)
        raw = state.status.readings.get("batteryPercent")
        if raw is not None:
            try:
                return int(raw)
            except (ValueError, TypeError):
                pass

        # Source 3: restored value from last run
        return self._restored_value

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose battery_state (ok/low) as an additional attribute."""
        state = self._device_state
        if state is None or state.battery_state is None:
            return {}
        return {"battery_state": state.battery_state}

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=f"DuoFern {self._device_code.device_type_name} ({self._hex_code})",
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=self._hex_code,
            sw_version=state.status.version if state else None,
            via_device=(DOMAIN, self.coordinator.system_code.hex),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update entity when coordinator pushes new data."""
        # Clear restored value once we have live data so we don't show stale
        # data after the device has reported back.
        state = self._device_state
        if state is not None and (
            state.battery_percent is not None
            or state.status.readings.get("batteryPercent") is not None
        ):
            self._restored_value = None
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Valve position sensor — 0xE1 Heizkörperantrieb
# ---------------------------------------------------------------------------


class DuoFernValveSensor(CoordinatorEntity[DuoFernCoordinator], SensorEntity):
    """Sensor showing the current valve opening position of the radiator valve.

    From 30_DUOFERN.pm format "29" statusId 186:
      valvePosition: position=6, bits 0-6, range 0-100%.
    Stored in ParsedStatus.readings["valvePosition"] by parse_status().

    Shown in the "Sensoren" section of the device card (no EntityCategory so
    it appears as a primary sensor, not a diagnostic).
    Uses SensorDeviceClass.POWER_FACTOR for % unit — HA renders a nice
    gauge icon. Alternatively mdi:valve is a clear custom icon.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "valve_position"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:valve"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_valve_position"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and state.available

    @property
    def native_value(self) -> float | None:
        state = self._device_state
        if state is None:
            return None
        val = state.status.readings.get("valvePosition")
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Last-seen timestamp sensor — shown on device info card for every device
# ---------------------------------------------------------------------------


class DuoFernLastSeenSensor(
    CoordinatorEntity[DuoFernCoordinator], SensorEntity, RestoreEntity
):
    """Sensor that shows when the device last sent any signal.

    Updated on every status frame, sensor event, weather frame, and battery
    frame. Uses SensorDeviceClass.TIMESTAMP so HA formats it as a human-
    readable time ("3 minutes ago") in the device info card.

    RestoreEntity ensures the timestamp survives HA restarts — without it
    the sensor would show 'unknown' until the next frame arrives.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "last_seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._device_code = device_state.device_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_last_seen"
        self._restored_value: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known timestamp from recorder on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None,
            "unknown",
            "unavailable",
        ):
            try:
                # HA stores timestamps as ISO 8601 with timezone info
                from homeassistant.util import dt as dt_util

                self._restored_value = dt_util.parse_datetime(last_state.state)
            except (ValueError, TypeError):
                pass

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        return self._device_state is not None

    @property
    def native_value(self) -> datetime | None:
        """Return the last-seen timestamp as a timezone-aware datetime."""
        state = self._device_state
        if state is None or state.last_seen is None:
            return self._restored_value

        try:
            from homeassistant.util import dt as dt_util

            # last_seen is stored as ISO string without timezone — treat as local
            naive = datetime.fromisoformat(state.last_seen)
            aware = dt_util.as_local(naive)
            return aware
        except (ValueError, TypeError):
            return self._restored_value

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        state = data.devices.get(self._hex_code) if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, self._hex_code)},
            name=f"DuoFern {self._device_code.device_type_name} ({self._hex_code})",
            manufacturer="Rademacher",
            model=self._device_code.device_type_name,
            serial_number=self._hex_code,
            sw_version=state.status.version if state else None,
            via_device=(DOMAIN, self.coordinator.system_code.hex),
        )


# ---------------------------------------------------------------------------
# Boost sensors — 0xE1 Heizkörperantrieb
# ---------------------------------------------------------------------------


class DuoFernBoostStartSensor(
    CoordinatorEntity[DuoFernCoordinator], SensorEntity, RestoreEntity
):
    """Timestamp sensor: when was the last boost started?

    Set in the coordinator when boost transitions from inactive → active
    (first 0xF0 frame after a 0xD4/0xE0 frame).

    Uses RestoreEntity so the last known start time survives HA restarts.
    HA renders datetime sensors as relative time: "vor 13 Minuten".
    """

    _attr_has_entity_name = True
    _attr_translation_key = "boost_started"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DuoFernCoordinator,
        device_state: DuoFernDeviceState,
        hex_code: str,
    ) -> None:
        super().__init__(coordinator)
        self._hex_code = hex_code
        self._attr_unique_id = f"{DOMAIN}_{hex_code}_boost_started"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hex_code)})
        self._restored_value: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None,
            "unknown",
            "unavailable",
        ):
            try:
                from homeassistant.util import dt as dt_util

                self._restored_value = dt_util.parse_datetime(last_state.state)
            except (ValueError, TypeError):
                pass

    @property
    def _device_state(self) -> DuoFernDeviceState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.devices.get(self._hex_code)

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and state.available

    @property
    def native_value(self) -> datetime | None:
        state = self._device_state
        if state is None or state.boost_start is None:
            return self._restored_value

        from homeassistant.util import dt as dt_util

        naive = state.boost_start
        # boost_start is stored as naive local datetime — make timezone-aware
        if naive.tzinfo is None:
            return dt_util.as_local(naive)
        return naive

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
