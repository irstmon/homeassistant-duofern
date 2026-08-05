# Changelog

## [v2.3.5]

- **Fixed: optimistic on/off state after a switch command silently no-op'd for channel-carrying switch types** — `_set_level()`'s optimistic pre-status-frame state update looked the device up by bare `hex`, but `DuoFernSwitch` instances for channel-carrying device types (`0x43`'s channels, and `0x65`/`0x74`'s channel "01" actor) are keyed by `full_hex` (hex + channel) in `self.data.devices`. The lookup by bare `hex` found nothing, so the switch briefly showed the wrong state until the next real status frame arrived. Same class of bug as `_set_moving()`, already fixed the same way in v2.3.4 for covers. `DuoFernSwitch` now also carries the channel-qualified device code so the fix actually applies; channel-less switch types (`0x46`/`0x71`) are unaffected since `full_hex` equals `hex` for them.

## [v2.3.4] — 2026-08-04

- **Fixed: `triggerSunDirection` angle encoding was wrong for most angle/width combinations** — the formula (translated from FHEM's `wCmds` set handler) used plain integer truncation and a reduction-style clamp for values that overflow the 4-bit angle field. Both were incorrect: Python's `int()` truncates negative intermediate values differently than positive ones (collapsing 22.5° and 45° onto the same internal index), and the real device uses natural 4-bit wraparound, not FHEM's clamp — confirmed by decoding real captured register byte for 22.5°/width 90° (`0xA1`), which the old clamp logic would have corrupted into `0xAD` (292.5°). Fixed with `math.floor()` instead of `int()`, and `& 0x0F` wraparound instead of the clamp. Verified against all 14 confirmed valid Homepilot angles × 4 confirmed valid widths (56 combinations) with zero mismatches, plus all 3 previously-captured real device bytes.
- **Fixed: several Umweltsensor value ranges were wrong or unconfirmed** — "Sonne erkennen nach" / "Schatten erkennen nach" corrected from 1–30 to the confirmed 1–32 (an off-by-two error in the original bit-width derivation). "Sonnenrichtung" target angle converted from a continuous Number (0–337.5° in 22.5° steps — which would have silently allowed invalid values) to a Select with exactly 14 confirmed Homepilot values. All other previously-unconfirmed ranges (Sun brightness 1–100, Wind, Temperature, Dawn/Dusk brightness, "Ab Temperatur von") are now confirmed correct against real Homepilot sliders — see README for the updated table.
- **Removed 7 dead coordinator methods** — the original space-separated string setters (`async_set_trigger_wind/temperature/dawn/dusk/sun/sun_direction/sun_height`) that backed the now-removed `text.py` trigger entities had zero callers left after the structured GUI (v2.3.3) replaced them, including a live copy of the angle-encoding bug above. Removed instead of left as unused dead code.
- **Fixed: several new Umweltsensor entities showed only the device name ("Wetterstation") with no distinguishing label** — the three Active-Grenzwerte sensors, the Dawn/Dusk event entity, and all of the new Grenzwert Number/Switch/Select entities had `translation_key` set but no matching `strings.json`/`en.json`/`de.json` entry, so Home Assistant fell back to showing just the device name. The fix went through two iterations: an explicit `_attr_name` fallback was added first, which stopped the blank names but — since HA's `Entity.name` resolution checks `_attr_name` *before* `translation_key` and uses it directly whenever it's a non-`None` string (see home-assistant/core#98993 and HA's own dev docs on this) — silently made the newly-added `strings.json`/`en.json`/`de.json` translations dead code, always showing English regardless of HA's configured language. Corrected by removing every explicit `_attr_name` on these entities and relying on `translation_key` + the translation files alone, which is what is actually needed (German HA language, German names).
- **Fixed: the two "Sonne erkennen nach" / "Schatten erkennen nach" Grenzwert numbers had no working min/max, step, unit, or read/write wiring** — while correcting their range to the confirmed 1–32 (see above), the entries lost their `native_step`, `native_unit_of_measurement`, `get_method`, and `set_method` fields, which have no defaults on `DuoFernGrenzwertNumberDescription`. Restored: 1-minute steps, `min` unit, and wired to `get_trigger_sun_slot` / `async_set_trigger_sun_slot_sun_minutes` (resp. `..._shadow_minutes`) so the two sliders actually read and write the device.
- **New: per-Grenzwert-slot automation triggers** — Sonne, Wind, Temperatur, Morgendämmerung, and Abenddämmerung each now offer 5 (or 10, for the start/end pairs) dedicated device automation triggers, one per Grenzwert slot, clearly labelled (e.g. "Wind Grenzwert 3 – Start", "Temperatur Grenzwert 1 – Überschritten", "Morgendämmerung Grenzwert 2 – Ausgelöst") so a specific slot can be picked directly from the automation editor's dropdown — no template needed. Device triggers add no new entities (they're automation-editor metadata only), so this doesn't add anything to the device card.
  - Implementation note: Home Assistant's standard device-trigger delegation (`event_trigger.async_attach_trigger`) only supports exact-match on event data, not "is bit N of this bitmask set" — the coordinator's `_handle_sensor_event` was extended to additionally fire one exact-matchable `duofern_grenzwert_event` per currently-active Grenzwert slot (alongside the existing `duofern_event`, which is completely unchanged), so the new triggers can use the standard, documented delegation pattern instead of a custom event-bus listener.
  - Regen keeps its existing flat Start/Ende trigger (no per-slot expansion) — Homepilot's own "Regen" screen has only a single on/off toggle, no Grenzwert 1–5 list like the other four groups.
  - Non-Umweltsensor sensor devices (0x61/`0xA5`/`0xAF`/`0xA9`/`0xAA`) are unaffected — they keep their original flat Sun/Wind triggers, since they have no Grenzwert/multi-slot concept at all.

- **New: Bewegungsmelder (`0x65`) and Wandtaster 6fach 230V (`0x74`) now support their second sub-channel** — both device types were only registered under channel "01" (the pre-declared actor/relay sub-device), so their `sensorMsg` events (motion start/end, the 6 button presses) never reached an entity, since `30_DUOFERN.pm` actually redirects them onto a separate "00" sub-device — the same pattern already fixed for the Umweltsensor (`0x69`) in a previous release. `DEVICE_CHANNELS` now registers `["00", "01"]` for both, and `_handle_sensor_event`'s "00"-redirect now covers all three device types (`if($code =~ m/^(65|69|74).*/)`, mirroring FHEM exactly) instead of only `0x69`.
  - Channel "01" (`%setsSwitchActor` in FHEM) is now also exposed as a proper switch actor: on/off (`switch`), Dusk/Dawn buttons, a Stairwell Time number (0–3200 s), and 7 automation switches (Dawn/Dusk Automatic, Manual Mode, Sun Automatic/Mode, Time Automatic, Mode Change, Stairwell Function). Reset settings/Full reset buttons are correctly excluded for this channel, matching `30_DUOFERN.pm`'s `%setsSwitchActor` (which — like the Umweltsensor's actor channel — has no reset commands, unlike every other switch/cover type).
  - `DuoFernId.is_switch`/`is_binary_sensor`/`is_remote` are now channel-aware for `0x65`/`0x74`, the same way `is_cover` already was for `0x69`: channel "01" resolves as a switch actor, channel "00" (or a channel-less id) as the sensor/remote.
- **Fixed: Wandtaster 6fach 230V (`0x74`) only had a device automation trigger for 1 of its 6 buttons** — `_REMOTE_CHANNELS` listed only `["01"]` for `0x74`; the identical `0xAD` (Wandtaster 6fach Bat) already correctly listed all 6. Corrected to `["01", "02", "03", "04", "05", "06"]`.
- **New: the Umweltsensor's actor sub-channel ("01") is now recognized as its own distinct cover type** instead of being lumped in with the generic Rohrmotor/Troll cover set. `30_DUOFERN.pm` gives it the plain RolloTron-style command set (`%setsDefaultRollerShutter` + `%setsUmweltsensor01`), which — unlike every other cover type — has no `reset:settings,full` command; the reset buttons are now correctly excluded for it. `DuoFernId.is_cover` and the cover/button setup loops are channel-aware for `0x69` the same way they already are for the weather-station/actor split elsewhere.
  - Fixed: `_set_moving()`'s optimistic pre-status-frame state update looked the device up by bare hex code, which for the Umweltsensor actor (registered as `<hex>01`) meant the cover briefly showed the wrong moving state until the next real status frame arrived. Now uses the channel-qualified `full_hex`.
- **Fixed: an entity could survive a domain migration and become an orphan** — the stale-entity cleanup in `__init__.py` compared bare `unique_id` strings, but `unique_id` is only unique *within* a domain in HA's entity registry. When `sun_direction_angle` was migrated from a `number` entity to a `select` entity reusing the same `unique_id` string (see above), the orphaned `number.xxx_sun_direction_angle` was never removed, because `select.py`'s new entity contributed the same bare string and made the cleanup check think the old one was still current. All 11 platforms now register `(domain, unique_id)` tuples instead of bare strings; the cleanup keeps a legacy bare-string fallback for safety.
- **New: the paired device codes field in the config flow is now optional** — a from-scratch setup with no FHEM export and no Homepilot access can now complete with an empty device list, then add devices afterwards via the physical pairing button (auto-added on success) or **Configure**/Options. Previously the field was required and setup couldn't be completed without at least one already-known device code.
- **Documentation: added guidance for picking a System Code from scratch** — for users with no FHEM history and no way to read the code back out of current Homepilot firmware, README now explains the `6F`-prefixed 6-hex-digit pattern the stick accepts, and the trade-offs of re-pairing every device by hand vs. bridging via Homepilot's own remote-pairing first.
- **Fixed: Fenster-Tür-Kontakt (`0xAC`) "opened" and "tilted" binary sensors could get stuck on** — each sensor only turned itself off on a `closed` event (`_EVENTS_OFF = {"closed"}`); if the window went directly from `opened` to `tilted` (or vice versa) without an intervening `closed` event, the sibling sensor never received an off event and stayed stuck `on` alongside the new one, even though a window can only be in exactly one of the three states at a time. Both sensors now recompute their state from scratch on every relevant event (`opened`/`closed`/`tilted`), so the correct sensor is always the only one left `on`.
- **Fixed: Umweltsensor (0x69): brightness mantissa mask was 1 bit too narrow.** -  `parse_weather_data()` decodes brightness as a 16-bit raw value split into a scale flag (bit 10, `0x0400`: ×1 or ×1000) and a mantissa. The mask used to extract the mantissa was `0x01FF` (9 bits, 0–511) — identical to FHEM's `30_DUOFERN.pm` (`$brightness = (hex(...) & 0x01FF) * $brightnessExp`). Real RX frames captured across full dawn/dusk transitions show the raw mantissa rising smoothly past 511 while the scale flag is still unset. The 9-bit mask silently discarded bit 9, so any value in the 512–1023 range wrapped around to a small bogus reading right at that boundary — visible as a sharp brightness dip in the low-brightness range around 511 lx. Changed the mask to `0x03FF` (10 bits, 0–1023), matching the scale flag's own bit position. This is a deliberate deviation from FHEM's formula — very likely a long-standing, unnoticed bug there too. Verified against ~40 real weather frames from a live device, spanning both the low range (up to 898, no discontinuity) and the ×1000 range (six independent readings from 2,000 to 63,000 lx, forming a physically plausible daily brightness curve). No other device type or reading is affected — this mask/flag pair is used in exactly one place in the codebase.

Thanks a lot to @geraldeberle1234 for helping and testing!

## [v2.3.3] — 2026-08-01

- **Structured trigger GUI for Umweltsensor (0x69) replaces the 7 text-input fields** — the previous "Wind Trigger", "Temperature Trigger", "Dawn Trigger", "Dusk Trigger", "Sun Direction Trigger", "Sun Height Trigger" text entities each packed all 5 Grenzwert (trigger slot) values into one space-separated string (e.g. `off 15 off off off`), matching FHEM's raw `wCmds` input format but awkward to edit in the HA UI. They're removed and replaced with a proper per-slot control set:
  - A **Grenzwert Slot selector** (1–5) per trigger group (Wind, Temperature, Dawn, Dusk, Sun) picks which of the 5 slots the other controls below act on. This selection is a local HA UI concept only, not written to the device.
  - A **Number** entity per group shows/edits the target value (e.g. wind speed, temperature) for the currently selected slot, with min/max/step sourced from FHEM's `wCmds` table where confirmed, or derived from the register's bit width where not yet confirmed against a real device.
  - A **Switch** entity per group toggles the currently selected slot active/inactive ("Aktiv"/"nutzen" in FHEM).
  - New dedicated selects for the sun-direction/-height fields with fixed, Homepilot-confirmed discrete options: **Sun Direction Angle** target, **Sun Direction Width** (0/45/90/135/180°), **Sun Height Target**, and **Sun Height Width**.
  - All of these still write into the same underlying config registers and `writeConfig` push as before — only the GUI representation changed.

- **Known limitation** — several of the new fields' min/max ranges (Sun brightness/delay, "Ab Temperatur von") are derived from the register's bit width rather than confirmed against a real Homepilot slider, and may need widening/narrowing once verified on real hardware.

## [v2.3.2] — 2026-08-01

- **Umweltsensor dawn/dusk trigger events** — two new event entities ("Dawn"/"Dusk") fire on the "00" sub-channel when the device's `dawn`/`dusk` sensorMsg (0713/0709) is received. Unlike Sun/Wind/Temperature/Rain, FHEM's `30_DUOFERN.pm` has no corresponding "end" message for these two, so they're modeled as momentary `EventEntity` triggers rather than a persistent on/off sensor. The active Grenzwert slot(s) (1–5) are decoded from the event's channel bitmask and passed as extra event data.

- **Active-Grenzwerte sensors for Sun/Wind/Temperature** — three new sensors per Umweltsensor report which of the up to 5 configured trigger thresholds ("Grenzwerte") are currently active, as a comma-joined list (e.g. `"1,3"`), instead of a plain boolean. Previously these were basic on/off binary sensors; `30_DUOFERN.pm` actually encodes the sensorMsg channel byte as a 5-bit bitmask of triggered slots, not a device channel, so a plain toggle couldn't represent multiple simultaneously active thresholds correctly.

- **Rain binary sensor now also reacts to threshold events** — the "Rain Detected" sensor previously only read the continuous `isRaining` bit from weather frames. It now also decodes `startRain`/`endRain` sensorMsg threshold events (same Grenzwert-bitmask mechanism as above) and combines both sources with OR. The verified weather-frame bit always takes precedence: whenever it reports no rain, any threshold-event state is force-cleared too, so an unverified/missing `endRain` frame can never leave the sensor stuck on "raining" for more than one weather-frame interval (~1 min).

- **Coordinator fix: Umweltsensor sensorMsg events now redirect to the "00" sub-channel** — `30_DUOFERN.pm` routes all Umweltsensor (and Wetterstation/Raumthermostat-family, device types `0x65`/`0x69`/`0x74`) sensorMsg readings onto the channel-"00" device object regardless of the frame's raw channel byte. The coordinator previously looked these events up (and fired them) under the bare device code, so they never reached the "00" sub-channel entities. Only `0x69` was fixed in this release; `0x65`/`0x74` likely have the same issue but are left untouched pending separate investigation.

- **Known limitation** — the Umweltsensor dawn/dusk and active-Grenzwerte features are translated directly from `30_DUOFERN.pm` but have not yet been verified against a real device (no live 0711/0712/0713/0709/0708/070A/070D/070E/071C/071D frame has been captured to confirm the bitmask decoding).

## [v2.3.1] — 2026-08-01

- **Known limitation** — Umweltsensor device communication (reading/writing config registers) works correctly, but the GUI/entity presentation for its config is still rough and is being improved.

- **Device date/time sensors** — two new diagnostic sensors, "Device Date" and "Device Time", are populated on the Umweltsensor's "00" sub-channel when the **Get Time** button is pressed. Decoded from the BCD-encoded Zeit response frame (`0F..1020…`), translated from `30_DUOFERN.pm`.

- **Full config register writes for latitude/longitude/timezone/DCF/rain trigger** — these previously used a stub (`async_set_umweltsensor_number`) that only logged the value, or stored plain reading strings that were never encoded into the registers `writeConfig` actually sends. They now write directly into the correct register bits (`weather_config_registers`), matching the `%wCmds` bit layout in `30_DUOFERN.pm`.

- **`writeConfig` rewritten** — now reads from the per-channel `weather_config_registers` store on the "00" sub-channel (previously read stale `.reg0`–`.reg7` readings from the bare device code), with per-register length validation before sending.

- **7 new trigger-threshold text entities** — Wind, Temperature, Dawn, Dusk, Sun, Sun Direction, and Sun Height Triggers are now exposed as space-separated 5-channel text fields on channel "00", matching FHEM's native input format (e.g. `off 15 off off off`). Values are encoded straight into the config registers and pushed to the device via the writeConfig button.

- **Batched register updates** — new `_raw_update_reg_byte`/`_raw_update_reg_word32` + `_flush_weather_config` helpers let the 5-channel trigger setters update all bytes in memory first and fire a single coordinator/HA notification, instead of one per channel.

- **Umweltsensor actor sub-channel ("01") gains cover-style entities** — Sun Position and Ventilating Position numbers, plus Manual Mode, Time Automatic, Dawn Automatic, Dusk Automatic, Sun Automatic, Sun Mode, and Ventilating Mode automation switches, since the actor sub-channel behaves like a Rohrmotor/Troll cover.

- **Window/door contact sensor** — tilted position now working.

## [v2.3.0] — 2026-07-29

- **Rain binary sensor for Umweltsensor (0x69)** — a new `moisture` binary sensor ("Rain Detected") is created on the weather station sub-channel ("00"). It updates from the `isRaining` bit decoded in every ~1-minute weather frame and reacts instantly to `startRain`/`endRain` coordinator events. Last known state is restored across HA restarts.

- **Weather config register decode** — the coordinator now handles `getConfig` responses (`0FFF1B2[1-8]`). The device's 8 config register pages are accumulated and decoded after each arrival (translated from `DUOFERN_DecodeWeatherSensorConfig()` in `30_DUOFERN.pm`). Decoded values (interval, DCF, timezone, latitude, longitude, triggerRain/Wind/Temperature/Dawn/Dusk/Sun) land on the "00" sub-channel and immediately populate the corresponding config entities.

- **Actor sub-channel ("01") entities** — the Umweltsensor actor now has its own entity set matching `%setsUmweltsensor01`: Running Time number (0–100 s), Wind Direction / Rain Direction selects, and Wind Automatic / Rain Automatic / Wind Mode / Rain Mode / Reversal switches.

- **Channel separation (channel_filter)** — a `channel_filter` field was added to `DuoFernNumberDescription`, `DuoFernSelectDescription`, and `DuoFernAutomationSwitchDescription`. Umweltsensor config entities are now pinned to "00" and actor entities to "01", eliminating duplicates that previously appeared on both sub-channels.

- **Fix rain event channel** — `startRain` / `endRain` events from `_handle_weather_data()` were emitting `device_code = bare_hex` with `channel = "01"`. Corrected to `device_code = bare_hex + "00"` with `channel = "00"` so the rain binary sensor matches its own hex_code.

## [v2.2.9] — 2026-07-29

- **Fix Umweltsensor (0x69) weather readings and battery status** — battery level from sub-channel devices and weather data from Umweltsensor devices were being dropped because the coordinator looked them up under the bare device code instead of the channel-suffixed key ("00") these channel devices actually use. Weather data is now correctly matched to the "00" sub-channel, battery status is mirrored onto all of a channel device's sub-channels, and dead sensor entities are no longer created on the Umweltsensor's actor sub-channel ("01").

## [v2.2.8] — 2026-07-27

- **Reconfigurable serial connection** — the serial port or network URL can now be changed after initial setup via **Settings → Devices & Services → DuoFern → ⋮ → Reconfigure**. The form pre-fills the current value, shows discovered USB ports as suggestions, and validates the connection before saving. The system code and paired device list are unaffected.

## [v2.2.7] — 2026-07-27

- **Network serial support via ser2net** — the integration now accepts `socket://host:port` and `rfc2217://host:port` connection URLs alongside local serial paths (e.g. `/dev/ttyUSB0`). Useful for running Home Assistant in a VM while the DuoFern USB stick is connected to another machine on the local network. `socket://` uses the same fast async transport as a direct USB connection; `rfc2217://` uses a worker-thread transport to handle PySerial's blocking RFC2217 implementation. Existing USB setups are fully unaffected. The config flow serial field now shows discovered USB ports as dropdown suggestions while allowing a network URL to be typed freely. Thanks to [@MBj1703](https://github.com/MBj1703) for the original PR.

## [v2.2.6] — 2026-05-18

- **Another try to fix 0x49 with firmware < 1.4 always reporting open** - completly ignoring 0x2C frames.

## [v2.2.5] — 2026-05-17

- **Fix 0x49 with firmware < 1.4 always reporting open** - looks like firmware versions
prior to 1.4 send a 0x2C frame after the movement stops without position bytes.


## [v2.2.4] — 2026-03-30

- **Fix cover running time range: now 2–255 seconds (matching Homepilot)**

- **Fix slat run time range: now 0.1–5 seconds in 0.1 s steps (matching Homepilot)**

## [v2.2.3] — 2026-03-27

- **Fix cover position settings not being applied correctly and inverted values**

- **Fix SunMode not working for covers**

## [v2.2.2] — 2026-03-26

This was just a re-publish of v2.2.1 with a fixed version number. A bug in the workflow did not update the version number

## [v2.2.1] — 2026-03-25

### Code Review & HACS Compliance Release + Raumthermostat Improvements

Full code review of the entire integration codebase across 3 sessions, with cross-validation by a second
independent reviewer. 23 findings identified, 17 resolved. All conformity improvements are non-functional
for existing devices. This release additionally includes functional improvements for the Raumthermostat
(0x73), based on first live device testing.

### Raumthermostat (0x73) — First Live Testing

- **Temperature range corrected** — target temperature slider now goes from 4.0 to 40.0 °C (was 28.0 °C),
  matching the original Rademacher GUI and the actual device range. The Heizkörperantrieb (0xE1) retains
  its previous 4.0–28.0 °C range unchanged.
- **Temperature threshold range corrected** — `temperatureThreshold1–4` sliders now range from 4.0 to
  40.0 °C (was −40.0 to 40.0 °C). Negative threshold values are not valid for this device.
- **`actTempLimit` replaced with 4 buttons** — the "Active Temp Limit" select entity (which always showed
  "unknown" because the device does not echo the selected value back) has been replaced by four dedicated
  buttons: "Activate Zone 1" through "Activate Zone 4". The underlying coordinator command
  (`async_set_act_temp_limit`) is unchanged — only the UI representation was replaced.
- **`manualMode` and `timeAutomatic` switches added** — OTA-verified via rtl_433: these are standard
  automation commands (`0x0806 FD/FE` and `0x0804 FD/FE`), identical to the Cover/Switch pattern. Both
  switches are now created for the Raumthermostat alongside the existing Heizkörperantrieb switches.
- **Temp +/− buttons removed** — the increment/decrement buttons have been removed. The target temperature
  slider is the correct input method, consistent with how the Heizkörperantrieb is handled.

### Improvements

- **ConfigEntryNotReady** — connection failures during setup now raise `ConfigEntryNotReady`, enabling
  HA's automatic retry with exponential backoff. Previously a generic exception was re-raised.
- **DataUpdateCoordinator lifecycle** — `config_entry` is now passed to `super().__init__()`, enabling
  automatic listener cleanup on unload (HA 2024.8+). All references updated from `self._config_entry`
  to `self.config_entry`.
- **Task cleanup on disconnect** — `async_disconnect()` now cancels all running tasks (pairing countdown,
  unpairing countdown, per-device status timeout loops) before disconnecting the stick. Previously these
  tasks could outlive the unload and cause asyncio warnings on integration reload.
- **USB discovery unique_id** — `async_step_usb` now sets a `unique_id` from the USB serial number,
  preventing duplicate discovery entries and correctly suppressing the discovery card when already
  configured.
- **Climate entity features** — added `ClimateEntityFeature.TURN_ON` and `TURN_OFF` to `supported_features`
  as required since HA 2024.2 for entities that offer `HVACMode.OFF`.
- **HomeAssistantError for pair-by-code** — all pair-by-code error handling now uses `HomeAssistantError`
  with `translation_key` instead of legacy `persistent_notification` service calls. Errors appear as
  translated toast messages in the HA UI.
- **Sun/Wind sensor state restore** — `DuoFernEnvBinarySensor` (sun and wind detection for external
  sensors and RolloTron Comfort Master) now inherits from `RestoreEntity`, preserving the last known
  state across HA restarts.
- **Migration guard** — `async_migrate_entry` now returns `False` for unknown future config versions
  (downgrade scenario) instead of silently accepting them.
- **Diagnostics privacy** — `CONF_PAIRED_DEVICES` (physical device codes) is now redacted in the
  diagnostics download alongside serial port and system code.
- **CI workflow** — new `release.yaml` GitHub Actions workflow that automatically updates the `version`
  field in `manifest.json` from the git release tag.

### Code Cleanup

- Removed 15 unused imports across 12 files (verified via AST analysis)
- Late imports with `# noqa: PLC0415` moved to top-level; duplicate `CONF_PAIRED_DEVICES` imports removed
- `services.yaml` reduced to schema only — `name` and `description` are now served exclusively from
  `strings.json` (HA 2024.4+ standard)
- Hardcoded German string `"Kanal"` replaced with `"Channel"` in multi-channel switch entity names
- `TYPE_CHECKING` block moved to end of import section (PEP 8 / isort convention)
- `import re` grouping fixed (no blank line between stdlib imports)
- USB discovery log level changed from INFO to DEBUG
- Callback type annotation improved from `object` to `Callable[[DuoFernId], None] | None`

---

## [v2.2.0] — 2026-03-24

### New Features

#### Code-Pairing (Pair by Code)

Pair DuoFern devices by entering their 6-digit device code directly in the Home Assistant UI — no
physical button press on the device required. This replicates the Rademacher Homepilot "Code anmelden"
functionality.

The device must be in its pairing window (RemotePair mode or within 2 hours of power-on). Only 6-digit
device codes are supported; 10-digit (2020+) devices require pairing via Homepilot first, then use
Auto-Discovery.

**Protocol details:** The implementation was reverse-engineered by comparing OTA radio captures between the
Homepilot and our integration using rtl_433 on 434.5 MHz. The key discovery was that USB frame byte 21
(the flags byte) controls `pay[0]` in the radio frame — setting it to `0x01` enables pairing mode. This
byte was undocumented in the FHEM reference implementation, which always uses `0x00`.

Complete pairing sequence: SetPairs (0x03) → StartPair (0x04) → CodePair ×2 (0x0D with f[1]=0xFF,
f[21]=0x01) → wait for 0x06 pair response → StopPair (0x05) → persist config → reload integration.

#### Auto-Unpair

When a device is unpaired during an active unpairing window, it is now automatically removed from the
config entry and the integration reloads — mirroring the auto-add behaviour of pairing. Previously the
device code had to be manually removed from the options flow.

Sequence: 0603 unpair response received → StopUnpair (0x08) → remove from config → reload.

#### Stop Pairing/Unpairing Button

New button on the USB stick device card that stops the active pairing or unpairing window early. Only
available (enabled) when a pairing or unpairing window is currently open.

#### Separate RemotePair and CodePair Commands

`build_remote_pair()` and `build_code_pair()` are now two distinct methods in `protocol.py`. RemotePair
(FHEM original: f[1]=0x01, f[21]=0x00) tells a device to enter pairing mode over radio. CodePair (new:
f[1]=0xFF, f[21]=0x01) pairs a device by code. Using the wrong flags byte caused RemotePair to fail —
discovered by OTA comparison.

### Bug Fixes

- **Legacy pair response frame dropped** — `0x06` pair response frames from 6-digit (legacy) devices were
  silently discarded. The serial parser expected 38-byte frames for all `0x06` messages (2020+ protocol),
  but legacy devices send 22-byte frames. The parser waited for 16 more bytes that never arrived, then
  flushed the buffer on timeout. Fixed with a fallback to 22 bytes when the buffer contains a complete
  legacy frame.
- **Pair-by-code race condition** — a successful code-pairing immediately triggered a config reload via
  `_on_new_device_paired()`, disconnecting the stick before `StopPair` could be sent. The stick remained
  in pairing mode until the next reconnect. Fixed by separating the code-pairing path: the `0602` pair
  response now only resolves the Future (no reload), and `async_pair_device_by_code` handles the full
  sequence — StopPair first, then persist config, then reload.
- **Double reload on pair and unpair** — both code-pairing and auto-unpair triggered the integration
  reload twice. The `_pairing_countdown` timer task continued running after the first reload, sending
  another StopPair and state update that triggered a second reload. Fixed by cancelling any active
  countdown tasks before triggering the reload.
- **Wrong stop command on unpairing timeout** — `_pairing_countdown` always sent `StopPair` (0x05) when
  the timer expired, even during unpairing. Should have sent `StopUnpair` (0x08). Fixed by adding an
  `unpairing` parameter to `_pairing_countdown` so the correct stop command is sent.

---

## [v2.1.0] and [v2.1.1] — 2026-03-13

### Code Review & Quality Release

Full code review of the entire integration codebase. 42 findings identified and resolved in the
first review pass, 10 additional issues caught and fixed in two follow-up review rounds. v2.1.1 is the
same release as v2.1.0 - only re-released after adding tests for HACS.

### Bug Fixes

- **Temperature slider lost 0.5°C precision** — `int(value)` in `number.py` truncated half-degree
  steps on the Raumthermostat (`0x73`). Setting 22.5°C silently became 22°C. Changed to `float(value)`.
- **HomeTimer (`0xA8`) and Handzentrale (`0xE0`) missing from `REMOTE_DEVICE_TYPES`** — both were
  incorrectly classified as actors. They received `remotePair`/`remoteUnpair`/`remoteStop` buttons
  (which don't exist on these devices) and their `duofern_event` events weren't handled properly
  by `event.py` and `device_trigger.py`.
- **5 phantom sensor entities per sun/wind sensor device** — `SENSOR_DEVICE_TYPES` included
  `0xA5`/`0xA9`/`0xAA`/`0xAF`, but only the Umweltsensor (`0x69`) actually sends weather data frames.
  All 5 sensor entities (brightness, temperature, wind, sunDirection, sunHeight) were permanently
  unavailable for the other types. Split into `SENSOR_DEVICE_TYPES = {0x69}` and documented why.
- **Umweltsensor (`0x69`) weather station buttons never created** — `DEVICE_CHANNELS[0x69]` only
  listed channel `"01"`. Channel `"00"` (the weather station) was never registered, so `getWeather`,
  `getTime`, `getConfig`, `writeConfig`, and `setTime` buttons were never created.
- **Options flow reloaded with stale data** — an explicit `async_reload` call before
  `async_create_entry` caused a double reload, the first with old options (auto_discover not yet saved).
- **HVAC mode showed OFF after restart** — `hvac_mode` derived from `self.target_temperature` which
  fell back to `TEMP_MIN` (4.0°C) before the first live frame. Now uses live data only and defaults
  to `HEAT` as the safe fallback.
- **Cover obstacle/block/lightCurtain shown twice** — these readings appeared both as dedicated
  `BinarySensorEntity` instances and as extra attributes on the cover entity.
- **Duplicate `modeChange` key in `AUTOMATION_COMMANDS`** — Python silently used the last entry.
  Both had identical payloads so it was harmless, but a latent risk for future edits.
- **Redundant state lookup in `_handle_weather_data`** — `state` was fetched twice from the same
  dictionary within the same function.
- **Timestamps displayed with wrong timezone offset** — `datetime.now()` produces naive local time,
  but `dt_util.as_local()` interpreted it as UTC. All timestamps (`last_seen`, `boost_start`) now use
  timezone-aware `dt_util.now()`.
- **Translation fixes:**
  - `boost_duration` was listed under `entity.select` in `de.json` instead of `entity.number`
  - `boost_duration` was completely missing from `en.json` and `strings.json`
  - 7 select entities (`motorDeadTime`, `windDirection`, `rainDirection`, `automaticClosing`,
    `openSpeed`, `actTempLimit`, `interval`) had no state translations — dropdowns showed raw values
  - `running_time_cover` and `running_time_dimmer` had identical display names
  - `window_contact_automatic` was named "Window open" (sounds like a state, not a setting) — renamed
    to "Window Open Signal"
  - Orphaned `window_contact` key removed from `entity.switch` translations

### Improvements

- **Reconnect guard** — added `_reconnecting` flag to prevent multiple parallel reconnect tasks when
  the stick sends several `NOT_INITIALIZED` (81010C55) frames in quick succession
- **Send queue crash detection** — `DuoFernStick` now uses a `done_callback` on the queue task.
  If `_process_send_queue` crashes, the error is logged immediately and the coordinator triggers a
  reconnect via `error_callback`. Previously a crash was completely silent — the integration appeared
  connected but nothing was sent
- **Stale entity cleanup safety** — if `registered_unique_ids` is empty after platform setup (likely
  a platform load failure), cleanup is skipped entirely with a warning instead of deleting all entities
- **Window/door contact sensor state restored on restart** — `DuoFernWindowSensor` (`0xAC`) now
  uses `RestoreEntity`. Previously it always showed "closed" after restart until the next event
- **Select entities restored on restart** — `DuoFernSelect` now uses `RestoreEntity` so the last
  known value is shown immediately instead of "unknown"
- **SetPairs failure summary** — devices that don't acknowledge during init are now tracked in a list
  and summarized in a single warning after the loop
- **`available` check in select entities** — now also checks `coordinator.last_update_success` so
  entities don't appear available when the serial connection is down
- **Device trigger warning** — `async_attach_trigger` now logs a warning when a device is not found,
  instead of silently returning a no-op trigger
- **All asyncio tasks tracked by HA lifecycle** — all bare `asyncio.create_task` calls replaced with
  `hass.async_create_task` for clean cancellation on integration unload
- **Late imports cleaned up** — `import datetime` inside `async_set_time`, `import os`/`import serial`
  inside `_check_serial_port`, and 4× `from homeassistant.util import dt` inside sensor properties
  all moved to module level
- **Unused code removed** — `entry_id` parameter in `DuoFernLight`, `DuoFernSwitch`, `DuoFernCover`;
  unused `dev_type` variable in `button.py`; duplicate `EVENT_ONLY_SENSOR_TYPES` set in `const.py`;
  duplicate `_ALL_COVERS`/`_TROLL_TYPES` definitions moved to `const.py`
- **All source code comments translated to English** — per project convention
- **Misleading comments corrected** — obstacle sensor docstring, frame template in button.py,
  `TROLL_COVER_TYPES` comment, `windowContact` status docstring

---

## [v2.0.5] — 2026-03-11

### Bug Fixes

- **Heizkörperantrieb Boost** — Boost now works as intended - thanks for the feedback. I tried
 to find all edge cases but someone found even more.


## [v2.0.4] — 2026-03-10

### Bug Fixes

- **Remote Unpair button threw `AttributeError` for all device types** — `build_remote_unpair()`
  was missing from `DuoFernEncoder` in `protocol.py`. Pressing "Remote Unpair" failed with
  `type object 'DuoFernEncoder' has no attribute 'build_remote_unpair'` regardless of device type.
  Fixed by implementing the method (`f[2]=0x06, f[3]=0x02`, from `30_DUOFERN.pm` `remoteUnpair`).

### New Features

#### Stop Remote Pairing Button

A new **"Stop Remote Pairing"** button is added to all devices that have Remote Pair / Remote Unpair
(all actuators except remotes, binary sensors, env sensors, and `0xE1`).

Pressing it ends the remote pairing or unpairing window early, without waiting for the timeout.
OTA-verified via RTL-SDR (device `4696E9`): `f[2]=0x06, f[3]=0x03`.

#### Window Contact Live Status (0xE1)

The `Window Open` switch for the Heizkörperantrieb (`0xE1`) now reflects the **live device state**
instead of relying solely on `RestoreEntity`. The device echoes the last `windowContact` value
set via `duoSetHSA` back in every status frame (Format 29, `byte[8] bit 5`).

New StatusId **188**: `pos=4, bits 5–5, map=onOff`. Verified via USB log + RTL-SDR:
`byte[8]=0x82` → off, `byte[8]=0xA2` → on. The device updates immediately after the CC ACK.

`RestoreEntity` remains as a safety net for the gap between HA start and the first frame.

### Improvements

#### Restore Last Known Values on Startup (0xE1)

Battery-powered devices like the Heizkörperantrieb can take several minutes before sending
their first status frame. All `0xE1` entities now show their last known values immediately
after an HA restart instead of displaying `unknown`:

| Entity | What is restored |
|--------|-----------------|
| Climate | Target temperature + current temperature |
| Valve Position sensor | Last position (%) |
| Sending Interval number | Last slider value |
| Boost Duration number | Last slider value |
| Battery, Last Seen, Boost Started | Already restored previously ✓ |
| manualMode, timeAutomatic, Window Open (switches) | Already restored previously ✓ |

Restored values are **display-only** — nothing is sent to the device based on them.
The first live frame from the device overwrites them.

`RestoreEntity` now applies to all `DuoFernNumber` entities (not just `0xE1`) — for
mains-powered devices this has no practical effect as live frames arrive quickly.

---

## [v2.0.3] — 2026-03-10

### New Features

#### Boost Mode for Heizkörperantrieb (0xE1) — Full Bidirectional Control

The radiator valve now supports **Boost Mode**: the valve opens fully for a configurable
duration to rapidly heat a room.

##### New Entities

Three new entities are added to all `0xE1` devices:

| Entity | Type | Description |
|--------|------|-------------|
| **Boost** | Switch | Activates / deactivates boost mode |
| **Boost Duration** | Number (4–60 min) | Duration to set before activating boost. Moving the slider alone does **not** send anything to the device — the value is only transmitted when the Boost switch is turned on |
| **Boost Started** | Sensor (Timestamp) | When the current (or last) boost was started. HA renders this as "13 minutes ago". Survives restarts via RestoreEntity |

##### Protocol (OTA-verified via RTl-SDR)

Boost frames were reverse-engineered from live Homepilot radio captures using:

```bash
rtl_433 -s 2.0M -f 434.5M -g 30 \
  -X "n=duofern,m=FSK_MC_ZEROBIT,s=10,r=100,preamble={10}fd4,invert" \
  -S known
```

| Frame | `f[8]` | `f[11]` | Notes |
|-------|--------|---------|-------|
| Boost ON  | `0x40 \| duration_min` | `0x03` | bit 6 = active flag, bits 5–0 = minutes (4–60) |
| Boost OFF | `0x00` | `0x02` | `f[11]=0x02` is critical — `0x00` causes the device to silently ignore the command |

The Boost ON frame also encodes the current `desired-temp` in `set_value` to prevent
the device from rejecting the command (`BB`) when the setpoint was changed externally
(e.g. via Homepilot).

##### Bug Fixes (all Boost-related)

- **Slider triggered HSA frames** — moving the duration slider no longer sends a
  `duoSetHSA` frame. Duration is stored locally and only transmitted when Boost is
  activated.
- **Desired temperature stuck at 28 °C** — during boost the device reports
  `desired-temp=28°C` in every frame. The real user setpoint is now preserved and
  restored correctly, including on the first frame after boost ends.
- **Boost ON rejected (BB) after external setpoint change** — `set_value=0` in the
  boost frame was accepted only if the device still held its initial setpoint. The
  current `desired-temp` is now always encoded in `set_value`.
- **Duration slider snapped back** — the device always reports the last-used boost
  duration in the status frame, overwriting the slider. The slider value is now
  preserved from `pending_boost_duration` when boost is inactive.
- **Display flickering ("bos" / normal / "bos")** — a second empty HSA frame was
  sent after the boost frame due to `forceResponse > 0`. Boost frames are now
  always sent alone, matching Homepilot behaviour exactly.
- **Boost OFF ignored** — `f[11]=0x00` caused the device to silently ignore the
  deactivation command. Corrected to `f[11]=0x02` (OTA-verified).
- **Boost switch jumped back to ON after OFF** — status requests sent after the
  OFF command triggered device responses that still showed boost active. A new
  `boost_deactivating` flag suppresses these F0 frames and re-queues the OFF
  until the device confirms it has stopped.
- **Rejected commands (BB) silently lost** — `0x81` frames other than CC/AA/55
  were not handled. A new `_handle_unknown_ack()` re-queues the boost command
  for retry on the next device contact.

---

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