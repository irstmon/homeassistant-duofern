# Rademacher DuoFern Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/HA%20Version-%3E%202026.8-18bcf2)](https://github.com/cg-ite/homeassistant-duofern/blob/3b4f84bc6b66122fcf202dac7292ebd7518ff20d/CHANGELOG.md#fixed)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=irstmon&repository=homeassistant-duofern&category=integration)

A custom Home Assistant integration for **Rademacher DuoFern** devices via the DuoFern USB stick.
Communicates directly with the USB stick using the native serial protocol - via local USB or a network serial server - **no cloud, no gateway, fully local**.

Forked from @MSchenkl and extensively rewritten to aim for a complete re-implementation based on the FHEM modules `10_DUOFERNSTICK.pm` and `30_DUOFERN.pm`, aiming for near-complete feature parity with the FHEM DuoFern module and the Homepilot / SmartHome Box.

📋 **[Supported Devices & Features](docs/devices.md)** - full device matrix and per-platform entity reference
🔧 **[Protocol Reference](docs/protocol.md)** - frame format, init sequence, boost/pairing internals

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

- **Serial Connection** - select a local USB stick (e.g., `/dev/ttyUSB0`) from the dropdown, or type a `ser2net` network URL such as `socket://192.168.1.20:2000` or `rfc2217://192.168.1.20:2000`
- **System Code** - the 6-digit hex dongle serial (starts with `6F`, e.g., `6F1A2B`). Find it in your previous FHEM config (`ATTR dongle CODE`) or on the stick label. To preserve all existing pairings you need to use the same code as before! Otherwise all devices have to be re-paired

#### I don't have FHEM and can't find my System Code anywhere

Older Homepilot versions showed the system code somewhere in their settings, but as far as we know, **current Homepilot firmware no longer exposes it anywhere in the UI**. If you never used FHEM and can't find the code in an old export, you can't recover the *original* code your devices are currently paired to - there is no way around that.

You can **pick a new System Code yourself and re-pair every device.** A code is valid as long as it follows the same pattern Rademacher itself uses for its dongles: 6 hex characters, starting with `6F`, followed by 4 arbitrary hex digits - e.g. `6FA51C`, `6F0001`, `6FDEAD`. Any value matching that pattern is accepted. **This will not be the same code your devices are already paired to**, so every single device will need to be re-paired from scratch ([physical pair-button press](#pair-by-set-button-connect-10-digit-covers), or [Pair by Code](#pair-by-code-code-pairing) if you know the device's own 6-digit code - this does not work for 10-digit codes!) before it responds to this integration.

**If Homepilot is still running and you can access it**, you can use remote-pairing for most devices instead of re-pairing everything by hand. Put a device into remote-pairing mode via Homepilot, then - once the stick is set up in HA - put the stick into pairing mode too and add devices one by one this way. A few devices don't have a remote-pair button at all, and even fewer devices don't support being bound to two hubs at once - the Heizkörperantrieb is one such exception. This way, a device ends up paired to both codes you control while Homepilot is still running, before you retire it.

Either way, re-pairing itself is safe and reversible - it doesn't require FHEM and doesn't touch anything else on the device. See [Migrating from FHEM](#migrating-from-fhem) below if you *do* have an existing code and just want to reuse it without re-pairing.


### Step 2: Paired Devices

Enter the 6-digit hex codes of your paired DuoFern devices, separated by commas:

```
406B2D, 4090AE, 40B690, 436C1A
```

You can find the device codes in your FHEM configuration (`ATTR device CODE`) or on the enclosed labels. If you have (paired) devices with 10 digits, take only the first 6 digits.

This field is optional - you can leave it empty and finish setup with zero devices, then add them
afterwards via **Settings → Devices & Services → DuoFern → Configure**, [physical pairing](#pair-by-set-button-connect-10-digit-covers), or
[Pair by Code](#pair-by-code-code-pairing). Useful for a from-scratch setup with no FHEM export or
Homepilot access to read existing codes from - see [I don't have FHEM and can't find my System
Code anywhere](#i-dont-have-fhem-and-cant-find-my-system-code-anywhere) above.

### Managing Devices After Setup

Go to **Settings → Devices & Services → DuoFern → Configure** to add or remove device codes at any time. The integration reloads automatically.

### Changing the Serial Connection

To change the serial port or network URL after initial setup, go to **Settings → Devices & Services → DuoFern → ⋮ → Reconfigure**. The form pre-fills the current value and validates the new connection before saving. The system code and paired device list are not affected.

### Network Serial (ser2net)

If your DuoFern USB stick is connected to a different machine than the one running Home Assistant (e.g. a Proxmox host while HA runs in a VM), you can expose it over the network using `ser2net`.

A minimal `ser2net.yaml` for a raw TCP connection:

```yaml
connection: &duofern
  accepter: tcp,2000
  connector: serialdev,/dev/ttyUSB0,115200n81,local
  options:
    kickolduser: true
```

Then enter the following in the **Serial Connection** field during setup:

```
socket://192.168.1.20:2000
```

For RFC2217, change the accepter to `telnet(rfc2217),tcp,2000` and use:

```
rfc2217://192.168.1.20:2000
```

Raw TCP (`socket://`) is recommended - it uses the same fast async transport as a direct USB connection. Only one client should access the stick at a time. The examples above do not add encryption or authentication; keep the connection on a trusted network.

### Automatic Device Discovery

If you enable **"Automatically discover unknown devices"** in the options, any DuoFern device that sends a frame but is not yet in your paired list will automatically appear in **Settings → Devices & Services → Discovered**:

- The device is only shown if its type is recognized (known Rademacher device - not radio noise)
- Click **Add** to add it to your paired list and reload the integration
- Click **Ignore** to permanently suppress it - HA handles this natively and it will never reappear

This is useful if you forgot to add a device code during setup, or want to discover the hex code of a device without looking it up in FHEM.

---

## Migrating from FHEM

1. Note your system code and all device codes from FHEM (`list TYPE=DUOFERN`)
2. Install this integration and enter the same codes during setup
3. Device pairing is stored in the DuoFern devices themselves and tied to the system code - **as long as you use the same system code during setup, all previously paired devices will respond without re-pairing. No re-pairing needed**
4. All device states are refreshed automatically via the startup status broadcast

---

## Additional Features

### Stick Control Buttons

These buttons appear on the **DuoFern Stick device card**:

| Button | What it does |
|--------|-------------|
| **Start pairing** | Opens a 60-second pairing window. Press the pair button on a new DuoFern device to add it. The device is auto-added to the config on success. |
| **Start unpairing** | Opens a 60-second unpairing window. Press the unpair button on a paired device to remove it. The device is auto-removed from the config on success. |
| **Stop Pairing/Unpairing** | Stops the active pairing or unpairing window early. Only available when a window is open. |
| **Status Broadcast** | Sends a broadcast status request to all paired devices, refreshing all states in HA. |

### Pair by Code (Code-Pairing)

Pair DuoFern devices by entering their 6-digit device code - **no physical button press required**. This replicates the Rademacher Homepilot "Code anmelden" functionality.

**How to use:**

1. Put the device in pairing mode (within 2 hours of power-on, or set to RemotePair)
2. Enter the 6-digit hex code (printed on the device) in the **"Pair by Code"** text field on the stick device card
3. Press the **"Pair by Code"** button
4. If successful, the device is added automatically and the integration reloads

Only 6-digit device codes are supported. 10-digit (2020+) devices must be paired using button press method.

### Pair by set button (connect 10-digit covers)

1. Press the physical **set button** on the motor
2. Press the **"Start pairing"** button  on the **DuoFern Stick device card**
3. The motor moves up and down briefly to acknowledge the connction

### General

- **Push-based, no polling** - devices push status updates; HA reflects changes immediately
- **Status broadcast on startup** - on integration load, a full status broadcast ensures all device states are current
- **USB auto-discovery** - the stick is detected automatically via USB VID/PID when plugged in
- **Network serial support** - connect via `ser2net` using `socket://host:port` (recommended) or `rfc2217://host:port` URLs; useful for virtualised HA environments where the USB stick is on another machine
- **Battery sensor entity** - all battery-powered devices get a dedicated **Battery** diagnostic sensor entity on the device card. The last known value persists across HA restarts
- **Last Seen sensor** - every device gets a `Last Seen` timestamp sensor that updates whenever a frame is received, with `RestoreEntity` persistence
- **Automatic device discovery** *(opt-in)* - unknown devices that send frames but are not yet in your paired list automatically appear in the HA Discovered inbox. Enable under **Settings → Devices & Services → DuoFern → Configure**. See [Automatic Device Discovery](#automatic-device-discovery) above
- **Auto-add on pairing** - when a new device is learned via the stick's pairing button, its hex code is automatically written into the config and the integration reloads. No more digging through logs
- **Auto-remove on unpairing** - when a device is unpaired during an active unpairing window, it is automatically removed from the config and the integration reloads
- **Pair by Code** - pair devices by entering their 6-digit code directly in the UI, no button press on the device required. Replicates the Homepilot "Code anmelden" functionality

See [Per-Device Buttons](docs/devices.md#per-device-buttons) and [Remote Control Event Entities](docs/devices.md#remote-control-event-entities) in the devices reference for the full per-device button and event-entity list.


---

## Automations

### Obstacle detection (any cover with obstacle hardware)

```yaml
trigger:
  - platform: state
    entity_id: binary_sensor.duofern_rohrmotor_xxxxxx_obstacle
    to: "on"
action:
  - service: cover.open_cover
    target:
      entity_id: cover.duofern_rohrmotor_xxxxxx
  - service: notify.notify
    data:
      message: "Obstacle detected - shutter re-opened."
```

### React to remote control button presses (event trigger)

```yaml
trigger:
  - platform: event
    event_type: duofern_event
    event_data:
      device_code: "A0XXXX"
      event: "up"
      channel: "01"
```

Or use the **Device trigger** UI in the automation editor - no YAML needed.

### Check whether an automation flag is active

```yaml
condition:
  - condition: template
    value_template: >
      {{ state_attr('cover.rollotron_living_room', 'sunAutomatic') == 'on' }}
```

---

## AI disclaimer
Yes, this project does make use of LLMs and coding agents, and this will likely continue going forward. AI is integrated deliberately and with care.

If you use AI tools, please do so responsibly and transparently.

On a personal note: the use of AI tools doesn’t mean this project was quick or effortless to build. A lot of time and dedication went into it.

---

## License

MIT License - see [LICENSE](LICENSE) for details.
