# Supported Devices & Features

Full device support matrix and per-platform feature reference. See the [main README](../README.md) for installation and configuration.

---

## Supported Devices

### Covers (Roller Shutters & Garage Doors)

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| RolloTron Standard | `0x40` | `cover` | ✅ |
| RolloTron Comfort Slave | `0x41` | `cover` | ❌ |
| Rohrmotor-Aktor | `0x42` | `cover` | ✅ |
| Rohrmotor Steuerung | `0x47` | `cover` | ❌ |
| Rohrmotor | `0x49` | `cover` | ✅ |
| Connect-Aktor | `0x4B` | `cover` | ❌ |
| Troll Basis | `0x4C` | `cover` | ❌ |
| SX5 (Garage Door) | `0x4E` | `cover` | ❌ |
| RolloTron Comfort Master | `0x61` | `cover` | ✅ |
| Troll Comfort DuoFern | `0x70` | `cover` | ❌ |

### Switches

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Universalaktor (2-channel) | `0x43` | `switch` | ✅ |
| Steckdosenaktor (also Universalaktor 1-Channel) | `0x46` | `switch` | ✅ |
| Troll Comfort DuoFern (Lichtmodus) | `0x71` | `switch` | ❌ |

### Lights / Dimmers

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Dimmaktor | `0x48` | `light` | ❌ |
| Dimmer (9476-1) | `0x4A` | `light` | ✅ |

### Climate / Heating

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Raumthermostat | `0x73` | `climate` | ✅ |
| Heizkörperantrieb | `0xE1` | `climate` | ✅ |

### Sensors & Detectors

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Bewegungsmelder | `0x65` | `binary_sensor`, `switch`, `number`, `button` | ❌ |
| Rauchmelder | `0xAB` | `binary_sensor` | ✅ |
| Fenster-Tür-Kontakt | `0xAC` | `binary_sensor` | ✅ |
| Umweltsensor | `0x69` | `sensor`, `binary_sensor`, `number`, `select`, `switch`, `text`, `button` | ✅ |
| Sonnensensor | `0xA5` | `binary_sensor` | ✅ |
| Sonnensensor (alt) | `0xAF` | `binary_sensor` | ❌ |
| Sonnen-/Windsensor | `0xA9` | `binary_sensor` | ✅ |
| Markisenwaechter | `0xAA` | `binary_sensor` | ❌ |

`0x65` (Bewegungsmelder) is registered as two sub-devices, same pattern as the Umweltsensor: sub-channel "00" carries the motion sensor, sub-channel "01" is a switch actor (`%setsSwitchActor` in FHEM) - on/off, dusk/dawn buttons, a stairwell timer, and automation switches. See [Switch Entities](#switch-entities-universalaktor-steckdosenaktor).

### Remote Controls & Wall Buttons (event-only)

| Description | Code | Notes | Tested |
|-------------|------|-------|:------:|
| Wandtaster | `0xA4` | Fires `duofern_event` on the HA event bus | ❌ |
| Wandtaster 6fach 230V | `0x74` | Fires `duofern_event` on the HA event bus (sub-channel "00"); sub-channel "01" is also a switch actor, same as `0x65` above | ❌ |
| Wandtaster 6fach Bat | `0xAD` | Fires `duofern_event` on the HA event bus | ❌ |
| Funksender UP | `0xA7` | Fires `duofern_event` on the HA event bus | ❌ |
| Handsender (6 Gruppen / 48 Geräte) | `0xA0` | Fires `duofern_event` on the HA event bus | ✅ |
| Handsender (1 Gruppe / 48 Geräte) | `0xA1` | Fires `duofern_event` on the HA event bus | ❌ |
| Handsender (6 Gruppen / 1 Gerät) | `0xA2` | Fires `duofern_event` on the HA event bus | ❌ |
| Handsender (1 Gruppe / 1 Gerät) | `0xA3` | Fires `duofern_event` on the HA event bus | ❌ |
| HomeTimer | `0xA8` | Fires `duofern_event` on the HA event bus | ❌ |
| Handzentrale | `0xE0` | Fires `duofern_event` on the HA event bus | ❌ |

**USB Stick:** Rademacher DuoFern USB-Stick 7000 and 9000 (VID: `0x0403`, PID: `0x6001`)

---

## Per-Platform Features

### Cover Entities (Roller Shutters)

- **Open / Close / Stop** - standard movement commands
- **Set Position** - move to any position (0-100 %)
- **Dusk position button** - move to the device's programmed dusk position using the device's built-in speed profile. Equivalent to `set DEVICE dusk` in FHEM.
- **Dawn position button** - move to the device's programmed dawn position. Equivalent to `set DEVICE dawn` in FHEM.
- **Toggle button** - reverse current movement / change direction
- **Push-based state updates** - position and moving state update in real time as status frames arrive
- **All automation flags as entity attributes** - visible on the entity detail card and usable in automations:
  `dawnAutomatic`, `duskAutomatic`, `sunAutomatic`, `timeAutomatic`, `manualMode`, `sunMode`,
  `ventilatingMode`, `ventilatingPosition`, `sunPosition`, `windAutomatic`, `rainAutomatic`,
  `windMode`, `rainMode`, `windDirection`, `rainDirection`, `blindsMode`, `slatPosition`,
  `slatRunTime`, `tiltInSunPos`, `tiltInVentPos`, `reversal`, `motorDeadTime`, `runningTime`,
  and more - depending on device type and status format
- **Obstacle / Block detection** - the Rohrmotor (`0x49`) and SX5 (`0x4E`) get dedicated `obstacle` and `block` binary sensor entities, usable directly as State triggers in automations. The SX5 additionally gets a `light_curtain` entity. Other cover types may support this too but are unverified - open an issue if your device reports obstacle/block in FHEM. No real frames available yet.
- **RolloTron obstacle detection** - RolloTron Standard/Comfort Slave/Comfort Master (`0x40`/`0x41`/`0x61`) get a dedicated `obstacle` binary sensor entity, usable as a State trigger. Not part of FHEM - derived from real device frames on a Comfort Master (`0x61`). No `block` entity yet - no confirmed bit position for blockage detection on this device family.
- **SX5 Light Curtain** - the SX5 garage door (0x4E) additionally gets a `light_curtain` binary sensor entity
- **Firmware version** - shown in device info after first status frame
- **Battery state** - shown as attribute where applicable

### Switch Entities (Universalaktor, Steckdosenaktor)

- **On / Off** - standard switch commands
- **Universalaktor (0x43)** - creates two separate devices in HA, one per channel ("Channel 01" and "Channel 02"), each with its own switch entity
- **All automation flags as attributes** - `dawnAutomatic`, `duskAutomatic`, `sunAutomatic`,
  `timeAutomatic`, `manualMode`, `sunMode`, `stairwellFunction`, `stairwellTime`, `modeChange`
- **Bewegungsmelder (0x65) / Wandtaster 6fach 230V (0x74) - actor sub-channel "01"** - both devices
  additionally register a switch-actor sub-device (`%setsSwitchActor` in FHEM), separate from their
  event sub-channel "00" (motion detection / button presses - see
  [Binary Sensor Entities](#binary-sensor-entities-motion-smoke-contact) and
  [Remote Control Event Entities](#remote-control-event-entities)):
  - The actor sub-channel has to be paired with the stick separately from the event sub-channel, otherwise it does not react to commands from Home Assistant
  - **On / Off switch**, plus **Dusk / Dawn buttons** (see [Per-Device Buttons](#per-device-buttons))
  - **Stairwell Time number** (0-3200 s)
  - **Automation switches**: `dawnAutomatic`, `duskAutomatic`, `manualMode`, `sunAutomatic`,
    `timeAutomatic`, `sunMode`, `modeChange`, `stairwellFunction`
  - No reset buttons - like the Umweltsensor's actor channel, `%setsSwitchActor` has no
    `reset:settings,full` command, unlike every other switch/cover type

### Light Entities (Dimmers)

- **On / Off** - full on / full off
- **Brightness control** - HA brightness (0-255) mapped to DuoFern level (0-100)
- **All automation flags as attributes** - `dawnAutomatic`, `duskAutomatic`, `sunAutomatic`,
  `timeAutomatic`, `manualMode`, `sunMode`, `stairwellFunction`, `stairwellTime`,
  `intermediateMode`, `intermediateValue`, `saveIntermediateOnStop`, `runningTime`

### Climate Entities (Thermostats & Radiator Valves)

- **Target temperature** - set desired temperature (4.0-28.0 °C for HSA and 4.0-40.0 °C for Raumthermostat in 0.5 °C steps)
- **Current temperature** - measured temperature from the device
- **HVAC modes** - HEAT and OFF
- **All readings as attributes** - `temperatureThreshold1-4`, `actTempLimit`, `output`,
  `manualMode`, `timeAutomatic`; for the Heizkörperantrieb additionally: `sendingInterval`
- **Manual Mode / Time Automatic switches** - `manualMode` and `timeAutomatic` are exposed as
  configuration switch entities for both the Raumthermostat (0x73) and Heizkörperantrieb (0xE1),
  matching the same switch pattern used for cover and switch devices
- **Temperature zone buttons** - four buttons ("Activate Zone 1-4") on the Raumthermostat (0x73)
  device card activate one of the four stored temperature threshold zones. Usable in automations
  via `button.press`. The threshold values are configurable via the four number sliders
  (`temperatureThreshold1-4`, 4.0-40.0 °C)
- **Valve Position sensor** - dedicated sensor entity (0-100 %) for the Heizkörperantrieb (`0xE1`), visible on the device card
- **Battery sensor** - dedicated diagnostic sensor entity for the Heizkörperantrieb (`0xE1`), reads `batteryPercent` from the status frame and persists the last known value across restarts
- **Window Open Signal switch** - tells the Heizkörperantrieb a window is open, immediately forcing the valve to the setback temperature (4 °C). The switch reflects the **live device state** - the device echoes the last-set value back in every status frame
- **Boost Mode** - rapidly heats a room by fully opening the valve for a configurable duration:
  - **Boost switch** - activates / deactivates boost mode
  - **Boost Duration number** (4-60 min) - configure the duration before activating; moving the slider alone sends nothing to the device
  - **Boost Started sensor** (timestamp) - shows when the last boost was activated, rendered by HA as "13 minutes ago"; persists across restarts
- **Values restored on startup** - all `0xE1` entities (climate temperatures, valve position, sending interval, boost duration) show their last known values immediately after HA restarts. Battery devices can take several minutes before their first status frame - no more `unknown` on the device card

### Binary Sensor Entities (Motion, Smoke, Contact)

- **Bewegungsmelder (0x65)** - `motion` device class, state updated via `duofern_event`; lives on sub-channel "00" (sub-channel "01" is a switch actor, see [Switch Entities](#switch-entities-universalaktor-steckdosenaktor))
- **Rauchmelder (0xAB)** - `smoke` device class, state updated via `duofern_event`; battery level is persisted across HA restarts
- **Fenster-Tür-Kontakt (0xAC)** - `opening` device class; two entities per device: `opened` and `tilted`
- **Battery sensor** - battery-powered sensors (Bewegungsmelder `0x65`, Rauchmelder `0xAB`, Fenster-Tür-Kontakt `0xAC`) get a dedicated **Battery** diagnostic sensor entity (0-100 %) visible on the device card. The last known value persists across HA restarts. `battery_state` (ok/low) is exposed as an attribute on the battery entity

### Binary Sensor Entities (Obstacle & Block Detection)

Covers with obstacle detection hardware get two dedicated binary sensor entities each:

| Entity | Device Class | Triggered when |
|--------|-------------|----------------|
| Obstacle | `problem` | Device detected an obstacle during movement |
| Block | `problem` | Device is blocked and cannot move |

The SX5 garage door (0x4E) additionally gets:

| Entity | Device Class | Triggered when |
|--------|-------------|----------------|
| Light Curtain | `safety` | The safety light curtain is active |

Devices with confirmed obstacle detection: Rohrmotor (`0x49`), SX5 (`0x4E`). Other cover types (Rohrmotor-Aktor `0x42`, Connect-Aktor `0x4B`, Troll Basis `0x4C`, Troll Comfort `0x70`) may support obstacle/block but are unverified - open an issue if your device reports these in FHEM.

RolloTron Standard/Comfort Slave/Comfort Master (`0x40`/`0x41`/`0x61`) get their own dedicated `obstacle` entity too, but no `block` entity - this device family isn't in FHEM's protocol reference at all for obstacle/block, so this was derived purely from real device frames on a Comfort Master (`0x61`) and only a single confirmed test case exists. Open an issue if you can help confirm this on your device, or if you find the bit position for blockage detection.

These entities are **fully triggerable** in HA automations as State triggers - see the [Automations](../README.md#automations) section.

### Binary Sensor Entities (Sun & Wind)

Environmental sensor devices expose one or two binary sensor entities depending on their capabilities:

| Device | Code | Sun sensor | Wind sensor |
|--------|------|:----------:|:-----------:|
| RolloTron Comfort Master (built-in) | `0x61` | ✅ | - |
| Sonnensensor | `0xA5` / `0xAF` | ✅ | - |
| Sonnen-/Windsensor | `0xA9` | ✅ | ✅ |
| Markisenwaechter | `0xAA` | - | ✅ |

Sun and wind sensor states are preserved across HA restarts via `RestoreEntity`.

### Weather Station Entities (Umweltsensor 0x69)

The Umweltsensor exposes two sub-devices: the weather station sub-channel ("00", read-only sensors + config) and the actor sub-channel ("01", a Rohrmotor/Troll-style output driven by the wind/rain/sun/dusk/dawn triggers).

#### Sub-Channel "00" - Weather Station

One sensor entity per measurement, updated from the weather frame:

| Sensor | Unit | Device Class |
|--------|------|-------------|
| Brightness (Helligkeit) | lux | `illuminance` |
| Temperature (Temperatur) | °C | `temperature` |
| Wind Speed | m/s | `wind_speed` |
| Sun Direction (Sonnenrichtung) | ° | - |
| Sun Height (Sonnenhöhe) | ° | - |

- **Rain Detected** - `moisture` binary sensor. Updated from the `isRaining` bit in every weather frame AND from `startRain`/`endRain` sensorMsg threshold events (same Grenzwert-bitmask mechanism as below). The verified weather-frame bit always wins: it force-clears any threshold-event state whenever it reports no rain, so the sensor can never get stuck "raining" for longer than one weather-frame interval (~1 min).
- **Active-Grenzwerte sensors (Sun / Wind / Temperature)** - three sensors report which of the up to 5 configured trigger thresholds ("Grenzwerte") are currently active, as a comma-joined list (e.g. `"1,3"`), decoded from the sensorMsg channel bitmask. Use a template condition in automations to filter by a specific Grenzwert, e.g. `{{ '3' in states('sensor...wind_grenzwerte').split(',') }}` - or use the per-Grenzwert **device automation triggers** described below instead, which don't need a template.
- **Dawn/Dusk event entity** - a single `Dawn/Dusk` event entity fires `dawn` or `dusk` when the corresponding sensorMsg (0713/0709) arrives; FHEM has no "end" message for these two, so they're a momentary event rather than a persistent sensor. Which Grenzwert(e) fired is included as event data (`grenzwerte: "1,3"`).
- **Device Date / Device Time** - diagnostic sensors populated by pressing the **Get Time** button; reflect the Umweltsensor's own internal clock.
- **Buttons** - **Get Weather**, **Get Time**, **Get Config**, **Write Config**, **Set Time** (pushes the current HA time to the device).

**Automation triggers for Sonne/Wind/Temperatur/Morgendämmerung/Abenddämmerung**: each of these five groups offers 5 (or 10, for the start/end pairs) dedicated device automation triggers - one per Grenzwert slot, clearly labelled e.g. "Wind Grenzwert 3 - Start", "Temperatur Grenzwert 1 - Überschritten", "Morgendämmerung Grenzwert 2 - Ausgelöst". Pick "Device" as the trigger type in the automation editor, select the Umweltsensor's weather-station device, then choose the specific Grenzwert/subtype combination from the dropdown - no template needed. Regen only has a flat Start/Ende trigger (no Grenzwert list, matching Homepilot's own single on/off toggle for rain).

Config entities (read via **Get Config**, written to the device via the **Write Config** button):

| Entity | Type | Description |
|--------|------|-------------|
| Transmit Interval | Select | How often the device sends weather frames, or "off" |
| DCF Time Sync | Switch | Enable/disable DCF77 time synchronisation |
| Trigger Rain | Switch | Enable/disable the rain trigger |
| Latitude / Longitude | Number | Location used for sun position calculation |
| Timezone Offset | Number | Timezone offset (0-23) used for sun calculations |
| Grenzwert Slot (Wind / Temperature / Dawn / Dusk / Sun) | Select | Picks which of the 5 trigger slots the controls below act on - a local HA UI concept, not written to the device |
| Trigger Active | Switch | Enable/disable the currently selected Grenzwert slot (per group) |
| Target Value (Wind speed / Temperature / Dawn brightness / Dusk brightness / Sun brightness / Sun detection delay / Shadow detection delay / Sun minimum temperature) | Number | The threshold value for the currently selected Grenzwert slot |
| Sun Direction Target Angle / Width, Sun Height Target / Width | Select | Fixed, Homepilot-confirmed discrete options for the currently selected Sun Grenzwert slot |
| Sun Link Temperature | Switch | Couples the Sun trigger to a minimum temperature ("Mit Temperatur verknüpfen") |

#### Sub-Channel "01" - Actor

Behaves like a Rohrmotor/Troll cover output, driven by the sub-channel "00" triggers:

| Entity | Type | Description |
|--------|------|-------------|
| Running Time | Number | Motor running time (0-100 s) |
| Sun Position / Ventilating Position | Number | Target positions (0-100 %) |
| Wind Direction / Rain Direction | Select | Movement direction (`up`/`down`) on wind/rain trigger |
| Wind Automatic / Rain Automatic / Wind Mode / Rain Mode / Reversal | Switch | Wind/rain automation flags |
| Manual Mode / Time Automatic / Dawn Automatic / Dusk Automatic / Sun Automatic / Sun Mode / Ventilating Mode | Switch | Standard cover automation flags |

### Per-Device Buttons

| Button | Devices | What it does |
|--------|---------|-------------|
| **Dusk position** | All covers, dimmers, plus switch actors (Universalaktor, Steckdosenaktor, and the 0x65/0x74 actor sub-channel) | Move to stored dusk position |
| **Dawn position** | All covers, dimmers, plus switch actors (Universalaktor, Steckdosenaktor, and the 0x65/0x74 actor sub-channel) | Move to stored dawn position |
| **Toggle** | All covers | Reverse current movement / change direction |
| **Reset settings** | Covers, switches, dimmers, Raumthermostat. Once per physical device: on channel 01 of the Universalaktor (0x43) and on the "00" device of Umweltsensor (0x69), Bewegungsmelder (0x65) and Wandtaster 6fach 230V (0x74) | Reset device settings (keeps pairing) |
| **Full reset** | Covers, switches, dimmers, Raumthermostat. Once per physical device: on channel 01 of the Universalaktor (0x43) and on the "00" device of Umweltsensor (0x69), Bewegungsmelder (0x65) and Wandtaster 6fach 230V (0x74) | Factory reset (loses pairing) |
| **Remote pair** | All actuators | Initiate remote pairing |
| **Remote unpair** | All actuators | Remove remote pairing |
| **Stop remote pairing** | All actuators | End remote pair/unpair window early |
| **Get status** | All actuators | Request current status from this device |
| **Activate Zone 1-4** | Raumthermostat (0x73) | Activate one of the four temperature threshold zones (`actTempLimit`) |

### Remote Control Event Entities

Each paired Handsender or Wandtaster gets a dedicated **EventEntity** in HA. When a button is pressed, the entity fires with the action (`up`, `stop`, `down`, `stepUp`, `stepDown`, `pressed`, `on`, `off`) and channel number, making it directly usable in automations via the **Device trigger** UI - no YAML required. For the Wandtaster 6fach 230V (0x74), this lives on event sub-channel "00"; all 6 buttons are individually selectable as device triggers.

---

## AI disclaimer
Yes, this project does make use of LLMs and coding agents, and this will likely continue going forward. AI is integrated deliberately and with care.

If you use AI tools, please do so responsibly and transparently.

On a personal note: the use of AI tools doesn’t mean this project was quick or effortless to build. A lot of time and dedication went into it.