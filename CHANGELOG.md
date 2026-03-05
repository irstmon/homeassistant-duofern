# Changelog

## [v2.0.2] — 2026-03-05

### New Features

#### Automatic Device Discovery (opt-in)
Unknown DuoFern devices that send frames but are not yet in your device list can now automatically appear in the Home Assistant **Discovered** inbox (`Settings → Devices & Services → Discovered`).

- Enable the feature under **Settings → Devices & Services → Rademacher DuoFern → Configure → Automatically discover unknown devices**
- A device only appears in the inbox if its type is recognized (i.e. it is a known Rademacher device type, not radio noise)
- Clicking **Add** adds the device code to your paired list and reloads the integration automatically
- Clicking **Ignore** permanently suppresses that device — Home Assistant handles this natively and it will never reappear

#### Auto-add Newly Paired Devices
When a new device is learned via the DuoFern stick's pairing button, its hex code is now automatically written into the integration's device list and the integration reloads. Previously you had to manually add the code via the options flow.

#### Battery Sensor Entity
Battery-powered devices (smoke detectors `0xAB`, window/door contacts `0xAC`, motion sensors `0x65`, and the `0xE1` Heizkörperantrieb) now get a dedicated **Battery** sensor entity visible on the device page under the *Diagnostic* section. The last known value is restored across Home Assistant restarts.

The `0x73` Raumthermostat is intentionally excluded from the static battery entity list because it exists in both battery-powered and 230V variants. It will receive a battery entity dynamically once a battery frame has been observed.

### Bug Fixes

- **Stale entity cleanup now works correctly** — entities that were removed in a previous integration version (e.g. buttons that no longer apply to a device type) are now properly deleted from the registry on startup. Previously the cleanup logic compared the registry against itself, so nothing was ever removed.
- **Binary sensors no longer show remote pairing / get-status buttons** — smoke detectors (`0xAB`), window contacts (`0xAC`), and motion sensors (`0x65`) are pure event senders with no set commands and now correctly have those buttons excluded.
- **`device_type_name` attribute error fixed** — receiving a frame from an unknown device no longer causes an `AttributeError` crash in the coordinator.

## [v2.0.1] - 2026-03-04

### Radiator Valve (0xE1) — Complete Rework

Communication with the Heizkörperantrieb has been fully reimplemented to match the actual device-initiated HSA protocol from the FHEM source code.

#### Protocol Fix: HSA device-initiated protocol

The radiator valve uses a special communication model: settings are **not** sent immediately, but queued until the device checks in with a status frame. Only then does the integration respond with a `duoSetHSA` frame containing all pending changes. This mirrors the FHEM implementation (`%commandsHSA` / `HSAold` / `HSAtimer`) exactly.

- **New:** `_schedule_hsa_update()` — changes are stored as pending, the UI is updated optimistically, and **nothing** is sent to the device immediately
- **New:** `_send_hsa_if_pending()` — called on the next incoming status frame from the device, builds and sends the `duoSetHSA` frame
- **New:** `build_hsa_command()` in `protocol.py` — correct frame layout `0D011D80nnnnnn...yyyyyy00` (no system code field, unlike other frame types)
- **Fix:** Temperature, sending interval, manual mode, and time automatic are now all correctly transmitted via the HSA mechanism
- **Fix:** `changeFlag` logic correctly implemented — values are only applied if the device still reports the expected old value (mirrors FHEM line 1227)
- **Fix:** `device_readings_snapshot` is taken **before** the optimistic re-apply so the `changeFlag` comparison is made against real device values, not our own stored ones

#### Set Temperature — Bug Fixes

- **Fix:** `async_set_temperature` was calling `async_set_level`, incorrectly encoding temperature as a 0–100% level value. Now correctly calls `async_set_desired_temp`
- **Fix:** `_schedule_hsa_update` now also updates `state.status.desired_temp` (not just `readings["desired-temp"]`), so the climate entity displays the new value immediately without snapping back
- **Fix:** When a new status frame arrives, pending values are re-applied to both `readings` and `desired_temp` after parsing, keeping the UI stable until the device confirms the change

#### Sending Interval — Bug Fix

- **Fix:** Encoding error fixed: `sendingInterval` was being encoded with `min=2` (`raw = value - 2`), but FHEM uses `min=0` (`raw = value`). This caused e.g. `3 min` to be transmitted as `raw=1`
- **Fix:** UI minimum set to 2 minutes

#### New Entities for 0xE1

- **New:** Sensor **"Valve Position"** (`valvePosition`, 0–100%) — read from format-29 StatusId 186, shown on the device card
- **New:** Sensor **"Battery"** — reads `batteryPercent` from the format-29 status frame (StatusId 185), with `RestoreEntity` for persistence across restarts
- **New:** Sensor **"Last Seen"** (`SensorDeviceClass.TIMESTAMP`) — shows when the last signal from the device was received, available for all device types, with `RestoreEntity`
- **New:** Switch **"Window Open"** (`windowContact`) — tells the device a window is open, forcing the valve to close (setback to 4 °C). Renamed from "Window Contact" to better reflect the actual function. Uses `RestoreEntity` since the device never reports this value back in its status frame

#### Button Cleanup

- **Fix:** `tempUp`/`tempDown` buttons are now only created for the 0x73 Raumthermostat, not the 0xE1 — the climate slider is the correct input method for the radiator valve
- **Fix:** `remotePair`, `remoteUnpair`, and `getStatus` buttons are no longer shown for the 0xE1 (these commands do not exist in `%setsHSA`)
- **Fix:** Buttons correctly excluded for smoke detectors (0xAB), window/door contacts (0xAC), and motion sensors (0x65) — these are pure event senders with no set commands

---

### General

#### Automatic Pairing of New Devices

- **New:** When a new device is paired via the USB stick's pairing button, its hex code is automatically written back into the config entry and the integration reloads. Previously the hex code had to be manually retrieved from the logs and entered by hand

#### Stale Entity Cleanup — Rework

- **Fix:** Stale entities (e.g. after removing a device from the config) were not reliably removed. The old implementation read the list of "current" entities from the registry itself — and therefore never deleted anything
- **New:** Each platform registers its created unique IDs into `coordinator.data.registered_unique_ids`. `_async_cleanup_stale_devices` compares this set against the registry and removes only truly stale entries
- **Removed:** Platform-specific cleanup code in `number.py` — replaced by the centralized mechanism

#### Other Fixes

- **Fix:** Second status broadcast 15 seconds after startup to reach devices that missed the first broadcast