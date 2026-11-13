# Release v2.3.11

- **Fixed:** Umweltsensor (`0x69`) weather values and configuration no longer disappear after every status frame of its actor channel.
- **Fixed:** Wandtaster 6fach 230V (`0x74`): status frames of an unknown format no longer overwrite the relay state with wrong values. Unknown status formats are now ignored for all devices.
- **Fixed:** Universalaktor (`0x43`) channel 2: automation switches, stairwell time and the dusk/dawn buttons now act on channel 2 instead of channel 1.
- **Fixed:** switch and dimmer actors are no longer polled several more times after every command.
- **Fixed:** service `pair_device_by_code` failed after a successful pairing and stopped working after the first reload.
- **Fixed:** the serial port is closed again if the stick does not answer during startup.
- **Fixed:** Umweltsensor rain triggers fire only when rain starts or stops, not every minute.
- **Fixed:** slat run time is now sent and shown in seconds (0.1-5.0 s).
- **Fixed:** changing the serial port (reconfigure) no longer uses a Home Assistant function that stops working in 2026.12; the integration also reloads only once after pairing or unpairing.
- **Fixed:** Umweltsensor "Write Config" refuses to write until the configuration has been read from the device, instead of overwriting unread settings with zeros.
- **Fixed:** a platform that fails to load no longer causes its entities to be deleted from the registry.
- **Fixed:** motor dead time select shows "short"/"long" instead of "unknown".
- **Fixed:** Wandtaster actor device no longer offers button triggers that can never fire.
- **Fixed:** missing names for the rain sensor and the device date/time sensors.
- **Changed:** Umweltsensor "active Grenzwerte" sensors start as "unknown" after a restart until the first event arrives, instead of showing a possibly outdated list.