# Release v2.4.1

- **Fixed:** Heizkörperantrieb (`0xE1`): a setpoint of 28 °C was taken as boost, and lower setpoints from Home Assistant (for example from a climate controller) never reached the device again. Boost is now detected from its own status bit.
- **Fixed:** Heizkörperantrieb (`0xE1`): a temperature changed during a boost is now applied by the device when the boost ends, instead of being ignored.
- **Changed:** Climate entities: 4 °C is a normal target temperature and no longer shown as "Off". "Off" is set only by selecting it, stays after a restart, and "Heat" brings back the temperature from before "Off".
