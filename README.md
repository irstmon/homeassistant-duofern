# Rademacher DuoFern Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A custom Home Assistant integration for **Rademacher DuoFern** devices via the DuoFern USB stick.  
Communicates directly with the USB stick using the native serial protocol — **no cloud, no gateway, fully local**.

Forked from @MSchenkl and extensively rewritten to aim for a complete re-implementation based on the FHEM modules `10_DUOFERNSTICK.pm` and `30_DUOFERN.pm`, aiming for near-complete feature parity with the FHEM DuoFern module.

---

## Supported Devices

### Covers (Roller Shutters & Garage Doors)

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| RolloTron Standard | `0x40` | `cover` | ❌ |
| RolloTron Comfort Slave | `0x41` | `cover` | ❌ |
| Rohrmotor-Aktor | `0x42` | `cover` | ❌ |
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
| Universalaktor (2-channel) | `0x43` | `switch` | ❌ |
| Steckdosenaktor (also Universalaktor 1-Channel) | `0x46` | `switch` | ✅ |
| Troll Comfort DuoFern (Lichtmodus) | `0x71` | `switch` | ❌ |

### Lights / Dimmers

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Dimmaktor | `0x48` | `light` | ❌ |
| Dimmer (9476-1) | `0x4A` | `light` | ❌ |

### Climate / Heating

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Raumthermostat | `0x73` | `climate` | ❌ |
| Heizkörperantrieb | `0xE1` | `climate` | ❌ |

### Sensors & Detectors

| Description | Code | HA Platform | Tested |
|-------------|------|-------------|:------:|
| Bewegungsmelder | `0x65` | `binary_sensor` | ❌ |
| Rauchmelder | `0xAB` | `binary_sensor` | ✅ |
| Fenster-Tür-Kontakt | `0xAC` | `binary_sensor` | ❌ |
| Umweltsensor | `0x69` | `sensor` | ❌ |
| Sonnensensor | `0xA5` | `sensor` | ❌ |
| Sonnen-/Windsensor | `0xA9` | `sensor` | ❌ |
| Markisenwaechter | `0xAA` | `sensor` | ❌ |

### Remote Controls & Wall Buttons (event-only)

| Description | Code | Notes |
|-------------|------|-------|
| Wandtaster | `0xA4` | Fires `duofern_event` on the HA event bus |
| Wandtaster 6fach 230V | `0x74` | Fires `duofern_event` on the HA event bus |
| Wandtaster 6fach Bat | `0xAD` | Fires `duofern_event` on the HA event bus |
| Funksender UP | `0xA7` | Fires `duofern_event` on the HA event bus |
| Handsender (6 Gruppen / 48 Geräte) | `0xA0` | Fires `duofern_event` on the HA event bus |
| Handsender (1 Gruppe / 48 Geräte) | `0xA1` | Fires `duofern_event` on the HA event bus |
| Handsender (6 Gruppen / 1 Gerät) | `0xA2` | Fires `duofern_event` on the HA event bus |
| Handsender (1 Gruppe / 1 Gerät) | `0xA3` | Fires `duofern_event` on the HA event bus |
| HomeTimer | `0xA8` | Fires `duofern_event` on the HA event bus |
| Handzentrale | `0xE0` | Fires `duofern_event` on the HA event bus |

**USB Stick:** Rademacher DuoFern USB-Stick 7000 and 9000 (VID: `0x0403`, PID: `0x6001`)

---

## Features

### Cover Entities (Roller Shutters)

- **Open / Close / Stop** — standard movement commands
- **Set Position** — move to any position (0–100 %)
- **Dusk position button** — move to the device's programmed dusk position. This uses the device's built-in dusk speed profile, which can be slower and quieter than a direct position command. Equivalent to `set DEVICE dusk` in FHEM.
- **Dawn position button** — move to the device's programmed dawn position. Equivalent to `set DEVICE dawn` in FHEM.
- **Push-based state updates** — position and moving state update in real time as status frames arrive from the device
- **All automation flags as entity attributes** — visible on the entity detail card and usable in automations:
  `dawnAutomatic`, `duskAutomatic`, `sunAutomatic`, `timeAutomatic`, `manualMode`, `sunMode`,
  `ventilatingMode`, `ventilatingPosition`, `sunPosition`, `windAutomatic`, `rainAutomatic`,
  `windMode`, `rainMode`, `windDirection`, `rainDirection`, `blindsMode`, `slatPosition`,
  `slatRunTime`, `tiltInSunPos`, `tiltInVentPos`, `reversal`, `motorDeadTime`, `runningTime`,
  and more — depending on device type and status format
- **Firmware version** — shown in device info after first status frame
- **Battery state** — shown as attribute where applicable

### Switch Entities (Universalaktor, Steckdosenaktor)

- **On / Off** — standard switch commands
- **Universalaktor (0x43)** — creates two separate switch entities (one per channel: 01 and 02), both grouped under the same device in HA
- **All automation flags as attributes** — `dawnAutomatic`, `duskAutomatic`, `sunAutomatic`,
  `timeAutomatic`, `manualMode`, `sunMode`, `stairwellFunction`, `stairwellTime`, `modeChange`

### Light Entities (Dimmers)

- **On / Off** — full on / full off
- **Brightness control** — HA brightness (0–255) mapped to DuoFern level (0–100)
- **All automation flags as attributes** — `dawnAutomatic`, `duskAutomatic`, `sunAutomatic`,
  `timeAutomatic`, `manualMode`, `sunMode`, `stairwellFunction`, `stairwellTime`,
  `intermediateMode`, `intermediateValue`, `saveIntermediateOnStop`, `runningTime`

### Climate Entities (Thermostats & Radiator Valves)

- **Target temperature** — set desired temperature (4.0–30.0 °C in 0.5 °C steps)
- **Current temperature** — measured temperature from the device
- **HVAC modes** — HEAT and OFF
- **All readings as attributes** — `temperatureThreshold1–4`, `actTempLimit`, `output`,
  `manualMode`, `timeAutomatic`; for the Heizkörperantrieb additionally: `valvePosition`,
  `sendingInterval`, `batteryPercent`

### Binary Sensor Entities (Motion, Smoke, Contact)

- **Bewegungsmelder (0x65)** — `motion` device class, state updated via `duofern_event`
- **Rauchmelder (0xAB)** — `smoke` device class, state updated via `duofern_event`
- **Fenster-Tür-Kontakt (0xAC)** — `opening` device class, state updated via `duofern_event`
- **Battery state** — `battery_state` (ok/low) and `battery_percent` shown as attributes
- **SX5 Obstacle / Block / Light Curtain** — three dedicated binary sensor entities per SX5 garage door, updated push-based from every status frame:

  | Entity | Device Class | Triggered when |
  |--------|-------------|----------------|
  | Obstacle | `problem` | SX5 detected an obstacle during movement |
  | Block | `problem` | SX5 is blocked and cannot move |
  | Light Curtain | `safety` | The safety light curtain is active |

  These are **fully triggerable** in HA automations as State triggers — see the [Automations](#automations) section.

### Sensor Entities (Weather Station)

One sensor entity per measurement per device:

| Sensor | Unit | Device Class |
|--------|------|-------------|
| Helligkeit (Brightness) | lux | `illuminance` |
| Temperatur | °C | `temperature` |
| Wind | m/s | `wind_speed` |
| Sonnenrichtung (Sun Direction) | ° | — |
| Sonnenhöhe (Sun Elevation) | ° | — |

### Stick Control Buttons

Three buttons appear on the **DuoFern Stick device card**:

| Button | What it does |
|--------|-------------|
| **Start pairing** | Opens a 60-second pairing window. During this time, press the pair button on a new DuoFern device to add it to the stick. The button is automatically disabled while another pairing or unpairing is already in progress. |
| **Start unpairing** | Opens a 60-second unpairing window. Press the pair button on a paired device to remove it from the stick. |
| **Status Broadcast** | Sends a broadcast status request to all paired devices, refreshing all states in HA. Useful after an HA restart or after making changes outside of HA. |

### Cover Dusk / Dawn Buttons

Two additional buttons appear on **each cover device card**:

| Button | What it does |
|--------|-------------|
| **Dusk position** | Commands the cover to move to its stored dusk position using the device's built-in speed profile. This is typically slower and quieter than using Set Position directly — ideal for evening closing routines. Equivalent to `set DEVICE dusk` in FHEM. |
| **Dawn position** | Commands the cover to move to its stored dawn (open) position. Equivalent to `set DEVICE dawn` in FHEM. |

> **Note:** Dusk/Dawn *position* buttons are different from `duskAutomatic` / `dawnAutomatic` attributes. The buttons are explicit one-time movement commands. The attributes control whether the device's built-in time-based automation is active.

### General

- **Push-based, no polling** — devices push status updates; HA reflects changes immediately
- **Status broadcast on startup** — on integration load, a full status broadcast is sent automatically (Step 7 of the init sequence), ensuring all device states are current even if HA was offline while changes were made
- **USB auto-discovery** — the stick is detected automatically via USB VID/PID when plugged in
- **Battery visibility** — all battery-powered devices show `battery_state` and `battery_percent` as entity attributes
- **Automations on obstacle** — SX5 obstacle/block/lightCurtain are individual binary sensor entities, not just attributes, so they can be used as State triggers directly

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three-dots menu → **Custom repositories**
3. Add `https://github.com/irstmon/homeassistant-duofern` with category **Integration**
4. Search for "Rademacher DuoFern" and install
5. Restart Home Assistant

### Manual

Copy the `custom_components/duofern/` folder to your HA config directory:
```
/config/custom_components/duofern/
```
Then restart Home Assistant.

---

## Configuration

### Step 1: Connection

Go to **Settings → Devices & Services → Add Integration → DuoFern**

- **Serial Port** — select your DuoFern USB stick (e.g., `/dev/ttyUSB0`)
- **System Code** — the 6-digit hex dongle serial (starts with `6F`, e.g., `6F1A2B`). Find it in your previous FHEM config (`ATTR dongle CODE`) or on the stick label.

### Step 2: Paired Devices

Enter the 6-digit hex codes of your paired DuoFern devices, separated by commas:

```
406B2D, 4090AE, 40B690, 436C1A
```

These are the device codes from your FHEM configuration (`ATTR device CODE`).

### Managing Devices After Setup

Go to **Settings → Devices & Services → DuoFern → Configure** to add or remove device codes at any time. The integration reloads automatically.

---

## Migrating from FHEM

1. Note your system code and all device codes from FHEM (`list TYPE=DUOFERN`)
2. Install this integration and enter the same codes during setup
3. Device pairing is stored in the USB stick — **no re-pairing needed**
4. All device states are refreshed automatically via the startup status broadcast

---

## Automations

### Obstacle detection (SX5 Garage Door)

```yaml
trigger:
  - platform: state
    entity_id: binary_sensor.duofern_sx5_xxxxxx_obstacle
    to: "on"
action:
  - service: cover.open_cover
    target:
      entity_id: cover.duofern_sx5_xxxxxx
  - service: notify.notify
    data:
      message: "Garage door obstacle detected — door re-opened."
```

### React to remote control button presses

```yaml
trigger:
  - platform: event
    event_type: duofern_event
    event_data:
      device_code: "A4XXXX"
      event: "pressed"
```

### Check whether an automation is active

All automation flags are entity attributes, usable in conditions:

```yaml
condition:
  - condition: template
    value_template: >
      {{ state_attr('cover.rollotron_living_room', 'sunAutomatic') == 'on' }}
```

---

## CLI Tools

The `tools/` directory contains standalone Python scripts for testing and device management without Home Assistant.

> **Important Note:** The HA integration must be stopped while using CLI tools — only one process can hold the serial port at a time.

### Requirements

```bash
pip install pyserial pyserial-asyncio-fast
```

> **HAOS (Home Assistant OS) Note:** On HAOS the system Python is externally managed. You need to run:
> ```bash
> apk add py3-pip
> pip install --break-system-packages pyserial-asyncio-fast
> ```
> This is only needed for the CLI tools. The integration itself installs dependencies automatically via `manifest.json`.

### test_duofern.py — Test Script

Control roller shutters directly from the command line:

```bash
python3 tools/test_duofern.py 4053B8 up           # Open one shutter
python3 tools/test_duofern.py 4053B8 down          # Close one shutter
python3 tools/test_duofern.py 4053B8 stop          # Stop one shutter
python3 tools/test_duofern.py 4053B8 position 50   # Set one to 50%
python3 tools/test_duofern.py 4053B8 status        # Status of one device
python3 tools/test_duofern.py up                   # Open ALL shutters
python3 tools/test_duofern.py down                 # Close ALL shutters
python3 tools/test_duofern.py position 50          # Set ALL to 50%
python3 tools/test_duofern.py status               # Status of ALL devices
python3 tools/test_duofern.py statusall            # Broadcast status request
```

### pair_duofern.py — Pairing Tool

Pair and unpair DuoFern devices without FHEM:

```bash
python3 tools/pair_duofern.py pair              # Start pairing (60s window)
python3 tools/pair_duofern.py unpair            # Start unpairing
python3 tools/pair_duofern.py list              # List all devices with status
python3 tools/pair_duofern.py pair --timeout 120 -v  # Extended timeout + debug
```

---

## Protocol

- **Frame format**: Fixed 22-byte (44 hex char) frames over UART at 115200 baud
- **Init sequence**: 7-step handshake (Init1 → Init2 → SetDongle → Init3 → SetPairs → InitEnd → StatusBroadcast)
- **ACK-gated send queue**: One command in-flight at a time, 5-second timeout
- **Push-based updates**: Devices send status frames proactively; coordinator calls `async_set_updated_data()` on each received frame
- **Position convention**: DuoFern 0 = open / 100 = closed; HA 0 = closed / 100 = open (inverted transparently, matching the original HA addon)

Implementation based on `10_DUOFERNSTICK.pm` and `30_DUOFERN.pm` from the FHEM project.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
