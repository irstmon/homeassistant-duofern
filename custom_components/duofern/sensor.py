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
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
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
        name="Helligkeit",
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="lx",
    ),
    DuoFernSensorDescription(
        key="temperature",
        reading_key="temperature",
        name="Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    DuoFernSensorDescription(
        key="wind",
        reading_key="wind",
        name="Wind",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="m/s",
    ),
    DuoFernSensorDescription(
        key="sunDirection",
        reading_key="sunDirection",
        name="Sonnenrichtung",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="°",
        icon="mdi:sun-compass",
    ),
    DuoFernSensorDescription(
        key="sunHeight",
        reading_key="sunHeight",
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

    entities: list[DuoFernSensor] = []
    for hex_code, device_state in coordinator.data.devices.items():
        if not device_state.device_code.is_sensor:
            continue
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
                description.key, hex_code,
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hex_code)},
            name=f"DuoFern {device_state.device_code.device_type_name} ({hex_code})",
            manufacturer="Rademacher",
            model=device_state.device_code.device_type_name,
            via_device=(DOMAIN, coordinator.system_code.hex),
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
            attrs["battery_percent"] = state.battery_percent
        if state.last_seen is not None:
            attrs["last_seen"] = state.last_seen
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
