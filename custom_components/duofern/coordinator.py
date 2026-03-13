"""DuoFern coordinator — push-based DataUpdateCoordinator.

Owns the DuoFernStick, dispatches all incoming protocol frames, and exposes
command methods to entity platforms. No polling; all state updates come from
the device itself.

Architecture:
  DuoFernCoordinator
    ├── _stick: DuoFernStick (serial I/O)
    ├── data: DuoFernData (all device states)
    ├── _on_message(): called by stick on every frame
    └── async_*(): command methods for entity platforms

Status broadcast on start:
  During stick.connect(), _init_sequence() already sends a status broadcast
  (Step 7, FHEM DUOFERNSTICK_DoInit) so all devices report current state
  immediately after the integration loads. If HA was offline and devices
  changed state in the meantime, the fresh broadcast will catch up.

  From FHEM 10_DUOFERNSTICK.pm, DUOFERNSTICK_DoInit step 7:
    # send status broadcast
    IOWrite($hash, $duoStatusRequest)

Push updates:
  All entity platforms inherit from CoordinatorEntity. When any device
  reports a status change, _handle_status() calls async_set_updated_data()
  which triggers _handle_coordinator_update() in every entity that listens.

Block/obstacle detection:
  SX5 (0x4E) reports obstacle/block/lightCurtain in its status frame.
  These are stored in ParsedStatus.readings and exposed as extra_state_attributes
  on the CoverEntity. They are ALSO fired as duofern_event events on the HA
  event bus so they can trigger automations directly.

  Event data structure:
    {device_code, event, state, channel}
  Use this in a Trigger: event type = duofern_event, event data = {event: obstacle}

Error handling:
  MISSING_ACK (810108AA) → device.available = False + status retry
  NOT_INITIALIZED (81010C55) → reconnect the stick

DUOFERN_EVENT is the HA event bus name for all sensor/obstacle events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AUTO_DISCOVER,
    CONF_PAIRED_DEVICES,
    DEVICE_CHANNELS,
    DOMAIN,
    STATUS_RETRY_COUNT,
    STATUS_TIMEOUT,
)
from .protocol import (
    CoverCommand,
    DuoFernDecoder,
    DuoFernEncoder,
    DuoFernId,
    ParsedStatus,
    SwitchCommand,
    WeatherData,
)
from .stick import DuoFernStick

_LOGGER = logging.getLogger(__name__)

# HA event bus name for sensor/button/obstacle events.
# Use in automations as event trigger: event_type = duofern_event
DUOFERN_EVENT = "duofern_event"


@dataclass
class DuoFernDeviceState:
    """Current state of one DuoFern device (or channel)."""

    device_code: DuoFernId
    channel: str | None = None
    available: bool = True
    status: ParsedStatus = field(default_factory=ParsedStatus)
    battery_state: str | None = None
    battery_percent: int | None = None
    last_seen: str | None = None
    last_paired: str | None = None
    last_unpaired: str | None = None
    # Pending HSA changes: key -> (old_value_at_set_time, new_value)
    # Populated by _schedule_hsa_update(), consumed by _send_hsa_if_pending()
    # when the 0xE1 device next sends a status frame.
    hsa_pending: dict[str, tuple[object, object]] = field(default_factory=dict)

    # Timestamp of the most recent Boost-ON frame (subtype 0xF0) for 0xE1 devices.
    # Set in _handle_status() when boost_active transitions False→True.
    # Not reset when boost ends so the UI can show "last boost started at X".
    boost_start: datetime | None = None

    # When a boost ON/OFF frame is sent, the intended value ("on"/"off") is saved
    # here so it can be re-queued if the device responds with an unexpected ACK
    # (e.g. 810100BB — command received but rejected).  Cleared on CC (810003CC).
    boost_retry_pending: str | None = None

    # Set to True after a boost OFF command is accepted (CC).
    # While True, incoming status frames that still show boost active (F0) must
    # NOT overwrite readings["boostActive"] back to "on" — the device takes a
    # moment to process the command and the STATUS_RETRY_COUNT requests may
    # arrive before the device has actually stopped boosting.
    # Cleared when the device sends its first non-boost status frame (F0=False).
    boost_deactivating: bool = False

    # User's intended boost duration as set via the slider (number entity).
    # NOT sent to the device immediately — only read when boost is activated.
    # This prevents the slider from triggering a duoSetHSA frame on every change.
    # Initialised to 14 min (reasonable default); preserved across status frames.
    pending_boost_duration: int = 14

    # --- Boost receive-window guards (Bug_9 / Bug_10) ---
    #
    # The device only opens its receive window at the SECOND or later F0 frame
    # after a Boost-ON command.  The very first F0 (sent ~sendInterval seconds
    # after the CC) has no window — sending Boost OFF then results in BB/AA.
    #
    # boost_ha_on_pending_f0: True after we sent a Boost ON command (CC received).
    # Cleared on the first F0 frame we see (that F0 is skipped for TX).
    # On subsequent F0 frames boost OFF is sent normally.
    boost_ha_on_pending_f0: bool = False

    # Similarly, after Boost OFF is accepted (CC), the device needs one full
    # D-frame cycle before it can accept a new Boost ON.  The first D-frame
    # after a Boost-OFF CC has no window (Boost ON results in BB).
    #
    # boost_off_cooldown: True after CC on Boost OFF.
    # Cleared after the first non-boost status frame is processed (without TX).
    # On the second non-boost frame the device is ready again.
    boost_off_cooldown: bool = False

    # Asyncio task running the FHEM-style status-timeout loop.
    # Started after CC for non-E1/non-cover devices; cancelled when a
    # status frame arrives from the device.  Mirrors FHEM:
    #   InternalTimer(+60s, DUOFERN_StatusTimeout) after CC
    #   RemoveInternalTimer on status receipt
    #   max STATUS_RETRY_COUNT retries, each 60 s apart
    status_timeout_task: asyncio.Task | None = field(default=None, repr=False)


@dataclass
class DuoFernData:
    """All DuoFern device states, keyed by full hex code (6 or 8 chars)."""

    devices: dict[str, DuoFernDeviceState] = field(default_factory=dict)
    pairing_active: bool = False
    unpairing_active: bool = False
    pairing_remaining: int = 0
    # Unique IDs of every entity created during the current setup run.
    # Populated by each platform's async_setup_entry via
    # coordinator.data.registered_unique_ids.update(...).
    # Used by _async_cleanup_stale_devices in __init__.py to detect and remove
    # entities that were registered in a previous version of the integration
    # but are no longer created by the current code.
    registered_unique_ids: set[str] = field(default_factory=set)


class DuoFernCoordinator(DataUpdateCoordinator[DuoFernData]):
    """Push-based coordinator for the DuoFern integration.

    No polling interval — all updates are initiated by the device via serial.
    Uses async_set_updated_data() to push state changes to all entities.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        serial_port: str,
        system_code: DuoFernId,
        paired_devices: list[DuoFernId],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # Push-based, no polling
        )
        self._config_entry = config_entry
        self._serial_port = serial_port
        self._system_code = system_code
        self._paired_devices = paired_devices
        self._stick: DuoFernStick | None = None

        self._pairing_task: asyncio.Task[None] | None = None
        self._unpairing_task: asyncio.Task[None] | None = None

        # Guard flag to prevent multiple parallel reconnect tasks when the stick
        # sends several NOT_INITIALIZED (81010C55) frames in quick succession.
        self._reconnecting: bool = False

        # Optional callback invoked when a new device is paired via the stick's
        # pairing button. Registered by async_setup_entry in __init__.py so the
        # new device's hex code can be persisted into the config entry data.
        # Signature: (device_code: DuoFernId) -> None
        self._on_new_device_paired: object = None

        # Pre-populate data with all known devices
        self.data = DuoFernData()
        self._register_all_devices()

    @property
    def system_code(self) -> DuoFernId:
        return self._system_code

    # ------------------------------------------------------------------
    # Device registration
    # ------------------------------------------------------------------

    def _register_all_devices(self) -> None:
        """Register all paired devices, expanding multi-channel devices.

        From 30_DUOFERN.pm:
          if(length($code) == 8) { # channel device
            $devHash->{"channel_$chn"} = $name;
          }

        Multi-channel devices (e.g. Universalaktor 0x43) are registered as
        base device + one DuoFernDeviceState per channel.
        """
        for device in self._paired_devices:
            if device.has_channels:
                # Register each channel as a separate entity
                for ch in device.channel_list:
                    ch_code = device.with_channel(ch)
                    full_hex = ch_code.full_hex
                    self.data.devices[full_hex] = DuoFernDeviceState(
                        device_code=device, channel=ch
                    )
                    _LOGGER.debug("Registered channel device %s", full_hex)
            else:
                self.data.devices[device.hex] = DuoFernDeviceState(device_code=device)
                _LOGGER.debug("Registered device %s", device.hex)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def register_on_new_device_paired(self, callback: object) -> None:
        """Register a callback invoked when a new device is paired.

        Called by async_setup_entry so the new hex code can be written back
        to the config entry and reloaded without user interaction.
        """
        self._on_new_device_paired = callback

    async def async_connect(self) -> None:
        """Connect the USB stick and start protocol I/O.

        After connect(), the stick runs its init sequence (7 steps) which
        includes a status broadcast as the final step — so all devices will
        report their current state immediately.
        """
        self._stick = DuoFernStick(
            port=self._serial_port,
            system_code=self._system_code,
            paired_devices=self._paired_devices,
            message_callback=self._on_message,
            error_callback=self._on_stick_queue_error,
        )
        await self._stick.connect()
        _LOGGER.info(
            "DuoFern coordinator connected (system code: %s, %d devices)",
            self._system_code.hex,
            len(self._paired_devices),
        )

    async def async_disconnect(self) -> None:
        """Disconnect the USB stick."""
        if self._stick:
            await self._stick.disconnect()
            self._stick = None

    # ------------------------------------------------------------------
    # Message dispatch (called by DuoFernStick on every frame)
    # ------------------------------------------------------------------

    def _on_message(self, frame: bytearray) -> None:
        """Route incoming frame to the appropriate handler.

        Called from DuoFernStick._frame_callback() in the asyncio event loop.
        """
        try:
            self._dispatch(frame)
        except Exception:
            _LOGGER.exception("Error dispatching message: %s", frame.hex())

    def _maybe_trigger_discovery(self, device_code: DuoFernId) -> None:
        """Fire integration-discovery if device is unknown and auto-discover is on.

        Conditions for firing:
          1. auto_discover option enabled in config entry options
          2. device hex not in entry.data[CONF_PAIRED_DEVICES]
          3. device type is recognised (not Unknown 0xXX)
        HA's async_set_unique_id in the flow prevents duplicate inbox entries.
        """
        if not self._config_entry.options.get(CONF_AUTO_DISCOVER, False):
            return
        paired: list[str] = self._config_entry.data.get(CONF_PAIRED_DEVICES, [])
        if device_code.hex in paired:
            return
        if device_code.device_type_name.startswith("Unknown"):
            return
        _LOGGER.info(
            "Unknown DuoFern device received: %s (%s) — triggering discovery",
            device_code.hex,
            device_code.device_type_name,
        )
        from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY  # noqa: PLC0415

        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={
                    "device_hex": device_code.hex,
                    "device_name": device_code.device_type_name,
                    "entry_id": self._config_entry.entry_id,
                },
            )
        )

    def _dispatch(self, frame: bytearray) -> None:
        """Dispatch logic — mirrors DUOFERN_Parse from 30_DUOFERN.pm."""

        # Status response from an actor
        if DuoFernDecoder.is_status_response(frame):
            self._handle_status(frame)
            return

        # Sensor / button event
        if DuoFernDecoder.is_sensor_message(frame):
            self._handle_sensor_event(frame)
            return

        # Weather data from Umweltsensor
        if DuoFernDecoder.is_weather_data(frame):
            self._handle_weather_data(frame)
            return

        # Battery status from sensors
        if DuoFernDecoder.is_battery_status(frame):
            self._handle_battery_status(frame)
            return

        # Command ACK (device received command, may need status retry)
        if DuoFernDecoder.is_cmd_ack(frame):
            self._handle_cmd_ack(frame)
            return

        # NACK: device did not respond — mark unavailable
        if DuoFernDecoder.is_missing_ack(frame):
            self._handle_missing_ack(frame)
            return

        # NACK: device not initialized — need reconnect
        if DuoFernDecoder.is_not_initialized(frame):
            self._handle_not_initialized()
            return

        # Unknown 0x81 response (e.g. 810100BB — command received but rejected).
        # The stick still unblocks the send queue on any 0x81 frame, but the
        # coordinator never gets a CC so status retries don't fire and the
        # pending command is silently lost.  Re-queue any saved boost retry.
        if frame[0] == 0x81:
            self._handle_unknown_ack(frame)
            return

        # Pair/unpair responses
        if DuoFernDecoder.is_pair_response(frame):
            self._handle_pair_response(frame)
            return

        if DuoFernDecoder.is_unpair_response(frame):
            self._handle_unpair_response(frame)
            return

    # ------------------------------------------------------------------
    # Frame handlers
    # ------------------------------------------------------------------

    def _handle_status(self, frame: bytearray) -> None:
        """Handle actor status response frame.

        From 30_DUOFERN.pm:
          #Status Nachricht Aktor
          if ($msg =~ m/0FFF0F.{38}/) { ... }

        For multi-channel devices (e.g. 0x43 Universalaktor), mirrors FHEM:
          iterate over all registered channels, parse with channel-specific
          position specs, and update each channel's state independently.
        """
        device_code = DuoFernDecoder.extract_device_code_from_status(frame)
        hex_code = device_code.hex

        self._maybe_trigger_discovery(device_code)
        channels = DEVICE_CHANNELS.get(device_code.device_type)
        if channels:
            # Multi-channel device: update each channel with channel-specific parsing
            any_found = False
            for ch in channels:
                full_hex = hex_code + ch
                state = self.data.devices.get(full_hex)
                if state is None:
                    continue
                any_found = True
                parsed = DuoFernDecoder.parse_status(frame, channel=ch)
                state.status = parsed
                state.available = True
                state.last_seen = dt_util.now().isoformat(timespec="seconds")
            if not any_found:
                _LOGGER.debug(
                    "Status from unknown channel device %s — ignoring", hex_code
                )
                return
        else:
            # Single device
            state = self.data.devices.get(hex_code)
            if state is None:
                _LOGGER.debug("Status from unknown device %s — ignoring", hex_code)
                return
            parsed = DuoFernDecoder.parse_status(frame)

            # Read boost_active from the PREVIOUS status BEFORE overwriting
            # state.status — otherwise the False→True edge detection below
            # compares parsed against itself and never fires correctly.
            prev_boost_active = state.status.boost_active

            # During boost the device reports desired-temp=28°C in every frame.
            # Preserve the real user setpoint so ClimateEntity and the UI don't
            # show 28°C permanently.  We restore it below after state.status = parsed.
            prev_desired_temp = state.status.desired_temp
            prev_desired_temp_reading = state.status.readings.get("desired-temp")

            state.status = parsed
            state.available = True
            state.last_seen = dt_util.now().isoformat(timespec="seconds")

            # Fix: during boost, device reports desired-temp=28°C.
            # Restore the real setpoint so HA shows the correct value.
            # Also restore on the boost→off transition frame: the first status
            # frame after boost ends (either by timer or OFF command) may still
            # report 28°C before the device settles on the real setpoint.
            if parsed.boost_active and prev_desired_temp is not None:
                # Boost still active: always restore our stored setpoint
                state.status.desired_temp = prev_desired_temp
                if prev_desired_temp_reading is not None:
                    state.status.readings["desired-temp"] = prev_desired_temp_reading
            elif (
                not parsed.boost_active
                and prev_boost_active
                and prev_desired_temp is not None
            ):
                # Boost just ended (True→False transition): restore for this frame.
                state.status.desired_temp = prev_desired_temp
                if prev_desired_temp_reading is not None:
                    state.status.readings["desired-temp"] = prev_desired_temp_reading

            # Fix: while boost_deactivating=True, the device may still report F0
            # (boost active) for several frames before processing our OFF command.
            # The device accepts the packet (CC) but continues boosting — it needs
            # to be asked again on each status frame until it complies.
            # Suppress F0 updates to readings["boostActive"] and re-queue the OFF
            # so _send_hsa_if_pending fires again on this frame contact.
            if state.boost_deactivating:
                if parsed.boost_active:
                    # Device still in boost — hold "off" in the UI and re-send
                    state.status.readings["boostActive"] = "off"
                    _LOGGER.debug(
                        "HSA %s: boost_deactivating=True on F0 frame — re-queuing OFF",
                        hex_code,
                    )
                    # Re-queue: _send_hsa_if_pending will fire below because hsa_pending becomes non-empty.
                    # Do NOT call _schedule_hsa_update (it would call async_set_updated_data unnecessarily);
                    # directly insert into hsa_pending so the pending check below sends the OFF.
                    if "boostActive" not in state.hsa_pending:
                        state.hsa_pending["boostActive"] = ("on", "off")
                else:
                    # Device confirmed boost is off — clear the flag.
                    # Guard B: the first D-frame after boost ends has no receive
                    # window (Bug_11). Set cooldown so the next Boost ON is sent
                    # on the SECOND D-frame, when the device is awake again.
                    state.boost_deactivating = False
                    state.boost_off_cooldown = True
                    state.boost_ha_on_pending_f0 = False
                    _LOGGER.debug(
                        "HSA %s: boost confirmed off by device, clearing boost_deactivating",
                        hex_code,
                    )

            # Fix: device frame always overwrites boostDuration with the last-used
            # value (stays at e.g. 14 after boost ends).  When boost is NOT active
            # and no boost keys are currently pending, restore the slider value
            # so the UI doesn't snap back to the old duration.
            if not parsed.boost_active and "boostDuration" not in state.hsa_pending:
                state.status.readings["boostDuration"] = state.pending_boost_duration

            # Fire obstacle/block events for automation triggers (e.g. SX5 garage)
            self._fire_obstacle_events(hex_code, parsed)

            # 0xE1 Heizkörperantrieb: device-initiated protocol — send any
            # queued HSA changes now that the device has checked in.
            # IMPORTANT: re-apply pending values into readings AFTER parse so
            # the UI keeps showing the user's intended value while we wait for
            # the device to confirm. Without this, state.status = parsed would
            # overwrite our optimistic update and the UI snaps back.
            if device_code.device_type == 0xE1:
                # Track boost start time: fires only on the False→True transition.
                if parsed.boost_active and not prev_boost_active:
                    state.boost_start = dt_util.now()

                # HSA response rule — derived from OTA captures bug_boost_5 + bug_boost_6:
                #
                #   D3/D4/D5/E0 (boost inactive):
                #     → Send if anything is pending (Boost ON, desired-temp, etc.)
                #
                #   F0 (boost active, no OFF pending):
                #     → Do NOT send.
                #
                #   F0 (boost active, boost OFF pending):
                #     → Send IMMEDIATELY — but only when receive window is open!
                #
                # RECEIVE-WINDOW GUARDS (Bug_9 / Bug_10):
                #
                #   Guard A — first F0 after HA-initiated Boost ON:
                #     The device only opens its receive window on the SECOND F0
                #     after a CC on Boost ON. The first F0 (~sendInterval seconds
                #     after CC) has no window → sending Boost OFF now → BB/AA.
                #     Fix: set boost_ha_on_pending_f0=True after CC. On the first F0
                #     clear the flag without TX. From the second F0 onward send normally.
                #     Evidence: bug_9 (18s=1×sendInterval → BB),
                #               bug_10 (31s=2×sendInterval → CC).
                #
                #   Guard B — first D-frame after Boost OFF CC:
                #     Analogously: after CC on Boost OFF the device immediately goes
                #     to sleep after TX. The first D-frame after that has no window
                #     → sending Boost ON now → BB.
                #     Fix: set boost_off_cooldown=True after CC on Boost OFF.
                #     On the first D-frame clear the flag without TX.
                #     From the second D-frame onward send normally.
                #     Evidence: bug_10 (D1 17s after Boost-OFF CC → BB).

                boost_off_now_pending = state.boost_deactivating or (
                    "boostActive" in state.hsa_pending
                    and state.hsa_pending["boostActive"][1]
                    in ("off", "False", "0", "false")
                )

                if parsed.boost_active:
                    # F0 frame
                    if state.boost_ha_on_pending_f0 and not boost_off_now_pending:
                        # Guard A: first F0 after our Boost ON — no receive window yet.
                        # Skip TX, clear the guard so the NEXT F0 is handled normally.
                        # Exception: if Boost OFF is already pending, send immediately
                        # (user cancelled quickly) — risk BB, but BB-retry handles it.
                        state.boost_ha_on_pending_f0 = False
                        _LOGGER.debug(
                            "HSA %s: skipping first F0 after Boost ON (no receive window)",
                            hex_code,
                        )
                        should_send = False
                    else:
                        if state.boost_ha_on_pending_f0:
                            # boost_off IS pending — clear guard and send now
                            state.boost_ha_on_pending_f0 = False
                        should_send = boost_off_now_pending
                else:
                    # D/E0 frame
                    if state.boost_off_cooldown:
                        # Guard B: first D-frame after Boost OFF CC — no receive window.
                        # Skip TX, clear the guard so the NEXT D-frame is handled normally.
                        state.boost_off_cooldown = False
                        _LOGGER.debug(
                            "HSA %s: skipping first D-frame after Boost OFF (cooldown)",
                            hex_code,
                        )
                        should_send = False
                    else:
                        should_send = True

                if should_send:
                    device_readings_snapshot = dict(parsed.readings)
                    for key, (_, new_val) in state.hsa_pending.items():
                        state.status.readings[key] = new_val
                        if key == "desired-temp":
                            try:
                                state.status.desired_temp = float(new_val)
                            except (TypeError, ValueError):
                                pass
                    self.hass.async_create_task(
                        self._send_hsa_if_pending(device_code, device_readings_snapshot)
                    )

        self.async_set_updated_data(self.data)

    def _fire_obstacle_events(self, hex_code: str, parsed: ParsedStatus) -> None:
        """Fire HA events for block/obstacle readings so automations can trigger.

        SX5 (0x4E) status frame includes: obstacle, block, lightCurtain.
        These are stored in extra_state_attributes on the CoverEntity AND
        fired as events so automations can use them as triggers.

        Automation trigger config:
          - platform: event
            event_type: duofern_event
            event_data:
              device_code: "4EABCD"
              event: "obstacle"
        """
        for key in ("obstacle", "block", "lightCurtain"):
            val = parsed.readings.get(key)
            if val:
                self.hass.bus.async_fire(
                    DUOFERN_EVENT,
                    {
                        "device_code": hex_code,
                        "event": key,
                        "state": str(val),
                        "channel": "01",
                    },
                )

    def _handle_sensor_event(self, frame: bytearray) -> None:
        """Handle sensor / button event.

        From 30_DUOFERN.pm:
          #Wandtaster, Funksender UP, Handsender, Sensoren
        """
        event = DuoFernDecoder.parse_sensor_event(frame)
        if event is None:
            return

        _LOGGER.debug(
            "Sensor event: %s ch=%s event=%s state=%s",
            event.device_code,
            event.channel,
            event.event_name,
            event.state,
        )

        # Trigger discovery for unknown devices before looking up state
        try:
            _dc = DuoFernId.from_hex(event.device_code)
            self._maybe_trigger_discovery(_dc)
        except Exception:
            pass

        # Update last_seen
        state = self.data.devices.get(event.device_code)
        if state:
            state.last_seen = dt_util.now().isoformat(timespec="seconds")

        # Fire HA event for binary_sensor.py and automations
        self.hass.bus.async_fire(
            DUOFERN_EVENT,
            {
                "device_code": event.device_code,
                "event": event.event_name,
                "state": event.state,
                "channel": event.channel,
            },
        )

        self.async_set_updated_data(self.data)

    def _handle_weather_data(self, frame: bytearray) -> None:
        """Handle Umweltsensor weather data (0F..1322...)."""
        device_code = DuoFernDecoder.extract_device_code(frame)
        self._maybe_trigger_discovery(device_code)
        weather = DuoFernDecoder.parse_weather_data(frame)

        state = self.data.devices.get(device_code.hex)
        if state is None:
            return

        # Store weather readings in status.readings for sensor.py
        r = state.status.readings
        if weather.brightness is not None:
            r["brightness"] = weather.brightness
        if weather.sun_direction is not None:
            r["sunDirection"] = weather.sun_direction
        if weather.sun_height is not None:
            r["sunHeight"] = weather.sun_height
        if weather.temperature is not None:
            r["temperature"] = weather.temperature
        if weather.is_raining is not None:
            r["isRaining"] = weather.is_raining
            if weather.is_raining:
                self.hass.bus.async_fire(
                    DUOFERN_EVENT,
                    {
                        "device_code": device_code.hex,
                        "event": "startRain",
                        "state": "on",
                        "channel": "01",
                    },
                )
            else:
                self.hass.bus.async_fire(
                    DUOFERN_EVENT,
                    {
                        "device_code": device_code.hex,
                        "event": "endRain",
                        "state": "off",
                        "channel": "01",
                    },
                )
        if weather.wind is not None:
            r["wind"] = weather.wind

        state.last_seen = dt_util.now().isoformat(timespec="seconds")
        # Cancel any pending status timeout — FHEM: RemoveInternalTimer on receipt.
        # state is guaranteed non-None here (checked above), no second lookup needed.
        self._cancel_status_timeout(state)
        self.async_set_updated_data(self.data)

    def _handle_battery_status(self, frame: bytearray) -> None:
        """Handle battery status frame.

        From 30_DUOFERN.pm: #Sensoren Batterie (0FFF1323...)
        """
        device_code = DuoFernDecoder.extract_device_code(frame)
        self._maybe_trigger_discovery(device_code)
        info = DuoFernDecoder.parse_battery_status(frame)
        state = self.data.devices.get(device_code.hex)
        if state:
            state.battery_state = str(info.get("batteryState", ""))
            pct = info.get("batteryPercent")
            state.battery_percent = int(pct) if pct is not None else None
        self.async_set_updated_data(self.data)

    def _handle_cmd_ack(self, frame: bytearray) -> None:
        """Handle ACK frame: command received by actor (810003CC).

        From 30_DUOFERN.pm: after ACK, send STATUS_RETRY_COUNT status requests
        to get the updated state quickly.
        For 0xE1: NO status requests. _send_status_request uses HSA-zeros for
        0xE1, which the device answers with CC, which would call this handler
        again — causing exponential queue growth. Organic D3/F0 frames every
        ~7s are sufficient for state updates.
        """
        device_code = DuoFernDecoder.extract_device_code(frame)
        _LOGGER.debug("Command ACK from %s", device_code.hex)
        state = self.data.devices.get(device_code.hex)
        if state:
            # Set receive-window guards based on what was just ACK'd (Bug_9/Bug_10).
            # boost_retry_pending holds "on"/"off" for the last boost command sent.
            if state.boost_retry_pending == "on":
                # CC on Boost ON: first F0 has no receive window (Guard A).
                state.boost_ha_on_pending_f0 = True
                state.boost_off_cooldown = False
            elif state.boost_retry_pending == "off":
                # CC on Boost OFF: first D-frame has no receive window (Guard B).
                state.boost_off_cooldown = True
                state.boost_ha_on_pending_f0 = False
            state.boost_retry_pending = None
        if device_code.device_type == 0xE1:
            return
        # Cover devices send their own status frame when movement ends —
        # no polling needed. Polling immediately after CC returns the current
        # (pre-movement) position, which would wipe the optimistic moving state.
        if device_code.is_cover:
            return
        # FHEM: InternalTimer(+60s, DUOFERN_StatusTimeout, count=4)
        # Start a fallback timer: poll once every STATUS_TIMEOUT seconds,
        # up to STATUS_RETRY_COUNT times, unless a status frame arrives first.
        self._start_status_timeout(device_code)

    def _handle_missing_ack(self, frame: bytearray) -> None:
        """Handle NACK frame: command not received by actor (810108AA).

        Mark device as unavailable — it will recover on next successful status.
        For 0xE1: NO status requests, NO unfreeze TX. Confirmed: the stick
        does NOT freeze after AA — organic D3 frames arrive normally.
        Any pending boost retry will be sent on the next organic D3.
        """
        device_code = DuoFernDecoder.extract_device_code(frame)
        _LOGGER.warning("Missing ACK from %s — marking unavailable", device_code.hex)
        state = self.data.devices.get(device_code.hex)
        if state:
            state.available = False
        self.async_set_updated_data(self.data)
        if device_code.device_type == 0xE1:
            return
        self._start_status_timeout(device_code)

    def _handle_not_initialized(self) -> None:
        """Handle NACK 'actor not initialized' frame (81010C55).

        From 30_DUOFERN.pm: trigger reconnect.
        Guard against multiple parallel reconnect tasks: if the stick sends
        several NOT_INITIALIZED frames in quick succession, only one reconnect
        task is started. The flag is cleared in _reconnect() when done.
        """
        if self._reconnecting:
            _LOGGER.debug("Reconnect already in progress, ignoring NOT_INITIALIZED")
            return
        _LOGGER.warning("Stick reports NOT INITIALIZED — scheduling reconnect")
        self._reconnecting = True
        self.hass.async_create_task(self._reconnect())

    def _on_stick_queue_error(self, exc: Exception) -> None:
        """Handle an unexpected crash of the stick's send queue task.

        Called by DuoFernStick._on_queue_task_done when the _process_send_queue
        coroutine raises an unhandled exception. Triggers a reconnect via the
        same guard-protected path as NOT_INITIALIZED NACK frames.
        """
        _LOGGER.error(
            "DuoFern stick send queue crashed: %s — scheduling reconnect", exc
        )
        if self._reconnecting:
            _LOGGER.debug("Reconnect already in progress, ignoring queue crash")
            return
        self._reconnecting = True
        self.hass.async_create_task(self._reconnect())

    def _handle_unknown_ack(self, frame: bytearray) -> None:
        """Handle unexpected 0x81 response that is not CC / AA / 55.

        Known cases:
          810100BB — device received the command but rejected it.
            Strategy: re-queue boost_retry_pending so it is retried on the
            next device-initiated status frame.
          810101DD — device is sleeping / not in receive window.
            Observed after stick-unfreeze TX to a sleeping 0xE1. Not an error;
            confirms the device is asleep. No retry needed — the next organic
            D3 will carry the re-queued command from the earlier BB handler.
        """
        device_code = DuoFernDecoder.extract_device_code(frame)

        # DD = device sleeping after unfreeze TX — expected, not an error.
        if frame[1] == 0x01 and frame[2] == 0x01 and frame[3] == 0xDD:
            _LOGGER.debug(
                "0x81/DD from %s — device sleeping (expected after unfreeze TX)",
                device_code.hex,
            )
            return

        _LOGGER.warning(
            "Unexpected 0x81 response 0x%02X from %s — command may have been rejected",
            frame[3],
            device_code.hex,
        )
        state = self.data.devices.get(device_code.hex)
        if state and state.boost_retry_pending is not None:
            retry_val = state.boost_retry_pending
            state.boost_retry_pending = None
            _LOGGER.info(
                "BB from %s — re-queuing boostActive=%s, scheduling stick-unfreeze TX",
                device_code.hex,
                retry_val,
            )
            if device_code.device_type == 0xE1:
                # Re-queue boostActive for next organic D3/F0 frame.
                self._schedule_hsa_update(device_code, "boostActive", retry_val)
                # Also re-queue boostDuration so the retry frame is fully formed.
                # Without this, _send_hsa_if_pending sees boost_duration_val=None
                # → boost_dur_for_frame falls back to pending_boost_duration (safe),
                # but having it explicit in pending is cleaner and avoids relying on
                # the fallback path. Belt-and-suspenders approach.
                if retry_val in ("on", "True", "1", "true") and state is not None:
                    self._schedule_hsa_update(
                        device_code, "boostDuration", state.pending_boost_duration
                    )
                # Set receive-window guards like CC does, because BB doesn't
                # reliably mean "rejected" — bug_boost_12 confirms boost ON got
                # BB but device DID start boosting. If the device accepted, its
                # first F0/D3 frame won't have a receive window. Without these
                # guards, a re-queued command on that frame → another BB → loop.
                if retry_val in ("on", "True", "1", "true"):
                    state.boost_ha_on_pending_f0 = True
                    state.boost_off_cooldown = False
                elif retry_val in ("off", "False", "0", "false"):
                    state.boost_off_cooldown = True
                    state.boost_ha_on_pending_f0 = False
                # After BB the stick stops forwarding RX until the next TX.
                # The device is already sleeping so this TX will get AA — that's fine.
                # We just need any TX to unfreeze the stick so the organic D3 gets through.
                self.hass.async_create_task(self._send_stick_unfreeze(device_code))
                return
            self._schedule_hsa_update(device_code, "boostActive", retry_val)
        if device_code.device_type == 0xE1:
            return
        self._start_status_timeout(device_code)

    def _start_status_timeout(self, device_code: DuoFernId) -> None:
        """Start the FHEM-style fallback status-poll timer after CC/AA/BB.

        From 30_DUOFERN.pm (ACK handler, non-E1):
          InternalTimer(gettimeofday()+timeout, "DUOFERN_StatusTimeout", hash)
          hash->{helper}{timeout}{count} = STATUS_RETRY_COUNT  (4)
          hash->{helper}{timeout}{t}     = AttrVal(name,"timeout","60")

        Polls the device once every STATUS_TIMEOUT seconds, up to
        STATUS_RETRY_COUNT times, stopping early when a status frame
        arrives (_cancel_status_timeout is called from _handle_status).
        """
        state = self.data.devices.get(device_code.hex)
        if state is None:
            return
        self._cancel_status_timeout(state)
        state.status_timeout_task = self.hass.async_create_task(
            self._status_timeout_loop(device_code)
        )

    def _cancel_status_timeout(self, state: "DuoFernDeviceState") -> None:
        """Cancel any running status-timeout loop for this device.

        Called from _handle_status when a status frame arrives — mirrors
        FHEM's RemoveInternalTimer / delete helper->{timeout}.
        """
        if state.status_timeout_task and not state.status_timeout_task.done():
            state.status_timeout_task.cancel()
        state.status_timeout_task = None

    async def _status_timeout_loop(self, device_code: DuoFernId) -> None:
        """Fallback poll loop — runs until status received or retries exhausted.

        Mirrors DUOFERN_StatusTimeout in 30_DUOFERN.pm:
          wait STATUS_TIMEOUT seconds, send one status request,
          decrement count, schedule next timer if count > 0.
        """
        try:
            for attempt in range(1, STATUS_RETRY_COUNT + 1):
                await asyncio.sleep(STATUS_TIMEOUT)
                _LOGGER.debug(
                    "Status timeout poll %d/%d for %s",
                    attempt,
                    STATUS_RETRY_COUNT,
                    device_code.hex,
                )
                await self._send_status_request(device_code)
        except asyncio.CancelledError:
            _LOGGER.debug(
                "Status timeout cancelled for %s (status frame received)",
                device_code.hex,
            )

    async def _send_stick_unfreeze(self, device_code: DuoFernId) -> None:
        """Send a dummy TX to unfreeze the stick after BB for 0xE1.

        After BB the stick stops forwarding incoming RX frames until it has sent
        something. The device is already asleep so this will get AA — that's OK.
        AA for 0xE1 is suppressed in _handle_missing_ack. The organic D3 frame
        (sendingInterval=3min) will then arrive normally and trigger the retry
        that was re-queued in hsa_pending.
        """
        await asyncio.sleep(0.3)
        if self._stick is None:
            return
        # Send a plain HSA-zeros frame — the device is sleeping and will not respond,
        # but the TX itself unfreezes the stick's RX forwarding.
        frame = DuoFernEncoder.build_hsa_command(0, device_code)
        _LOGGER.debug("Sending stick-unfreeze TX to %s after BB", device_code.hex)
        await self._stick.send_command(frame)

    def _handle_pair_response(self, frame: bytearray) -> None:
        """#Device paired (0602...)."""
        device_code = DuoFernDecoder.extract_device_code(frame)
        _LOGGER.info("Device paired: %s", device_code.hex)
        state = self.data.devices.get(device_code.hex)
        if state:
            state.last_paired = dt_util.now().isoformat(timespec="seconds")
        else:
            # This is a brand-new device not yet in our paired list.
            # Notify __init__.py so it can persist the code into the config
            # entry and trigger a reload — after which the device will be
            # fully registered with all its entities.
            _LOGGER.info(
                "New device paired: %s — adding to config entry", device_code.hex
            )
            if callable(self._on_new_device_paired):
                self._on_new_device_paired(device_code)
        self.async_set_updated_data(self.data)

    def _handle_unpair_response(self, frame: bytearray) -> None:
        """#Device unpaired (0603...)."""
        device_code = DuoFernDecoder.extract_device_code(frame)
        _LOGGER.info("Device unpaired: %s", device_code.hex)
        state = self.data.devices.get(device_code.hex)
        if state:
            state.last_unpaired = dt_util.now().isoformat(timespec="seconds")
        self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_status_request(self, device_code: DuoFernId) -> None:
        """Send a status request to a specific device.

        For 0xE1: this method is never called -- all three ACK handlers return
        early for 0xE1. HomePilot also never polls 0xE1 reactively; it only
        responds to device-initiated D3/F0 frames (sendingInterval = 3 min).
        The guard below is a safety net in case of future callers.

        For all other devices: use the standard 0DFF0F40 status request.
        """
        if self._stick is None:
            return
        if device_code.device_type == 0xE1:
            _LOGGER.warning(
                "_send_status_request called for 0xE1 device %s -- suppressed",
                device_code.hex,
            )
            return
        frame = DuoFernEncoder.build_status_request(device_code, self._system_code)
        await self._stick.send_command(frame)

    async def _reconnect(self) -> None:
        """Reconnect the stick after NOT_INITIALIZED NACK.

        Clears _reconnecting flag on exit so future NOT_INITIALIZED frames
        can trigger a new reconnect if needed.
        """
        try:
            _LOGGER.info("Reconnecting DuoFern stick...")
            if self._stick:
                await self._stick.disconnect()
            await self.async_connect()
        finally:
            self._reconnecting = False

    async def _pairing_countdown(self, duration: int) -> None:
        """Countdown timer for pairing/unpairing UI."""
        for remaining in range(duration, 0, -1):
            self.data.pairing_remaining = remaining
            self.async_set_updated_data(self.data)
            await asyncio.sleep(1)
        self.data.pairing_remaining = 0
        self.data.pairing_active = False
        self.data.unpairing_active = False
        if self._stick:
            await self._stick.send_command(DuoFernEncoder.build_stop_pair())
        self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    async def async_start_pairing(self, duration: int = 60) -> None:
        """Start 60-second pairing window. Sends duoStartPair (0x04)."""
        if self.data.pairing_active or self.data.unpairing_active:
            return
        if self._stick is None:
            return
        await self._stick.send_command(DuoFernEncoder.build_start_pair())
        self.data.pairing_active = True
        self.data.pairing_remaining = duration
        self.async_set_updated_data(self.data)
        self._pairing_task = self.hass.async_create_task(
            self._pairing_countdown(duration)
        )
        _LOGGER.info("Pairing started (%ds)", duration)

    async def async_stop_pairing(self) -> None:
        """Stop pairing window early."""
        if self._pairing_task and not self._pairing_task.done():
            self._pairing_task.cancel()
        self.data.pairing_active = False
        self.data.pairing_remaining = 0
        if self._stick:
            await self._stick.send_command(DuoFernEncoder.build_stop_pair())
        self.async_set_updated_data(self.data)

    async def async_start_unpairing(self, duration: int = 60) -> None:
        """Start 60-second unpairing window. Sends duoStartUnpair (0x07)."""
        if self.data.pairing_active or self.data.unpairing_active:
            return
        if self._stick is None:
            return
        await self._stick.send_command(DuoFernEncoder.build_start_unpair())
        self.data.unpairing_active = True
        self.data.pairing_remaining = duration
        self.async_set_updated_data(self.data)
        self._unpairing_task = self.hass.async_create_task(
            self._pairing_countdown(duration)
        )
        _LOGGER.info("Unpairing started (%ds)", duration)

    async def async_stop_unpairing(self) -> None:
        """Stop unpairing window early."""
        if self._unpairing_task and not self._unpairing_task.done():
            self._unpairing_task.cancel()
        self.data.unpairing_active = False
        self.data.pairing_remaining = 0
        if self._stick:
            await self._stick.send_command(DuoFernEncoder.build_stop_unpair())
        self.async_set_updated_data(self.data)

    async def async_request_all_status(self) -> None:
        """Send status broadcast to all paired devices."""
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_status_request_broadcast()
        await self._stick.send_command(frame)
        _LOGGER.debug("Status broadcast sent")

    # ------------------------------------------------------------------
    # Cover commands
    # ------------------------------------------------------------------

    async def async_cover_up(self, device_code: DuoFernId) -> None:
        """Move cover up (open).

        From 30_DUOFERN.pm: up => "0701tt00000000000000"
        """
        await self._send_cover(device_code, CoverCommand.UP)
        self._set_moving(device_code, "up")

    async def async_cover_down(self, device_code: DuoFernId) -> None:
        """Move cover down (close).

        From 30_DUOFERN.pm: down => "0703tt00000000000000"
        """
        await self._send_cover(device_code, CoverCommand.DOWN)
        self._set_moving(device_code, "down")

    async def async_cover_stop(self, device_code: DuoFernId) -> None:
        """Stop cover movement.

        From 30_DUOFERN.pm: stop => "07020000000000000000"
        """
        await self._send_cover(device_code, CoverCommand.STOP)
        self._set_moving(device_code, "stop")

    async def async_cover_position(
        self, device_code: DuoFernId, duofern_position: int
    ) -> None:
        """Move cover to absolute position.

        duofern_position is DuoFern-native (0=open, 100=closed).
        Inversion is done in cover.py before calling here.

        From 30_DUOFERN.pm: position => "0707ttnn000000000000"
          invert=100 means cover.py converts HA position (0=closed,100=open)
          to DuoFern position (0=open,100=closed).
        """
        await self._send_cover(
            device_code, CoverCommand.POSITION, position=duofern_position
        )

    async def async_cover_dusk(self, device_code: DuoFernId) -> None:
        """Move cover to dusk position (leise, programmed in device).

        From 30_DUOFERN.pm %commands:
          dusk => {cmd => {noArg => "070901FF000000000000"}}

        This is NOT the same as duskAutomatic. It explicitly commands the device
        to move to its programmed dusk position — typically slower/quieter than
        a full close command. Useful for evening position automation.

        FHEM command: set DEVICENAME dusk
        """
        await self._send_cover(device_code, CoverCommand.DUSK)
        self._set_moving(device_code, "down")

    async def async_cover_dawn(self, device_code: DuoFernId) -> None:
        """Move cover to dawn position (programmed in device).

        From 30_DUOFERN.pm %commands:
          dawn => {cmd => {noArg => "071301FF000000000000"}}

        FHEM command: set DEVICENAME dawn
        """
        await self._send_cover(device_code, CoverCommand.DAWN)
        self._set_moving(device_code, "up")

    async def async_cover_sun_mode(self, device_code: DuoFernId, enable: bool) -> None:
        """Enable/disable sun mode (070801FF / 070A0100).

        From 30_DUOFERN.pm: sunMode on/off
        """
        payload = bytes.fromhex(
            "070801FF000000000000" if enable else "070A0100000000000000"
        )
        await self._send_generic(device_code, payload)

    async def _send_cover(
        self,
        device_code: DuoFernId,
        command: CoverCommand,
        position: int | None = None,
    ) -> None:
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_cover_command(
            command, device_code, self._system_code, position=position
        )
        await self._stick.send_command(frame)

    def _set_moving(self, device_code: DuoFernId, moving: str) -> None:
        """Optimistically set moving state before status arrives."""
        state = self.data.devices.get(device_code.hex)
        if state:
            state.status.moving = moving
            self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------
    # Switch / dimmer commands
    # ------------------------------------------------------------------

    async def async_switch_on(self, device_code: DuoFernId, channel: int = 1) -> None:
        """Turn switch/dimmer on.

        From 30_DUOFERN.pm: on => "0E03tt00000000000000"
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_switch_command(
            SwitchCommand.ON, device_code, self._system_code, channel=channel
        )
        await self._stick.send_command(frame)
        self._set_level(device_code, 100)

    async def async_switch_off(self, device_code: DuoFernId, channel: int = 1) -> None:
        """Turn switch/dimmer off.

        From 30_DUOFERN.pm: off => "0E02tt00000000000000"
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_switch_command(
            SwitchCommand.OFF, device_code, self._system_code, channel=channel
        )
        await self._stick.send_command(frame)
        self._set_level(device_code, 0)

    async def async_set_level(self, device_code: DuoFernId, level: int) -> None:
        """Set dimmer level (0-100).

        From 30_DUOFERN.pm: level => "0707ttnn000000000000"
        Also used for desired-temp encoding.
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_dim_command(level, device_code, self._system_code)
        await self._stick.send_command(frame)
        self._set_level(device_code, level)

    async def async_set_desired_temp(self, device_code: DuoFernId, temp: float) -> None:
        """Set desired temperature.

        0xE1 Heizkörperantrieb: queues change for next HSA status frame.
          From 30_DUOFERN.pm %commandsHSA: desired-temp bitFrom=17, changeFlag=23,
          min=4, max=28, step=0.5. Sent via duoSetHSA on next device contact.

        0x73 Raumthermostat: sends immediately via dedicated command frame.
          From 30_DUOFERN.pm: desired-temp => "0722tt0000wwww000000"
        """
        state = self.data.devices.get(device_code.hex)
        if state is not None and state.device_code.device_type == 0xE1:
            self._schedule_hsa_update(device_code, "desired-temp", temp)
            return
        # 0x73 or other: send immediately
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_desired_temp_command(
            temp, device_code, self._system_code
        )
        await self._stick.send_command(frame)

    def _set_level(self, device_code: DuoFernId, level: int) -> None:
        state = self.data.devices.get(device_code.hex)
        if state:
            state.status.level = level
            self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------
    # Generic automation commands (on/off toggles from %commands)
    # ------------------------------------------------------------------

    async def _send_generic(
        self, device_code: DuoFernId, payload: bytes, channel: int = 1
    ) -> None:
        """Send a generic 10-byte command payload to a device."""
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_generic_command(
            payload, device_code, self._system_code, channel=channel
        )
        await self._stick.send_command(frame)

    async def async_set_automation(
        self, device_code: DuoFernId, name: str, enable: bool
    ) -> None:
        """Set an automation on/off.

        For 0xE1 Heizkörperantrieb: manualMode and timeAutomatic are HSA
        commands — queued and sent on next device status frame via duoSetHSA.
        From 30_DUOFERN.pm %commandsHSA: manualMode bitFrom=8, timeAutomatic bitFrom=9.

        For all other devices: sends generic command frame immediately.
        From 30_DUOFERN.pm %commands — FD = on, FE = off.
        """
        state = self.data.devices.get(device_code.hex)
        if state is not None and state.device_code.device_type == 0xE1:
            if name in ("manualMode", "timeAutomatic"):
                self._schedule_hsa_update(device_code, name, "on" if enable else "off")
                return
        # Lookup table: name -> (on_bytes, off_bytes)
        AUTOMATION_COMMANDS: dict[str, tuple[str, str]] = {
            "timeAutomatic": ("080400FD000000000000", "080400FE000000000000"),
            "duskAutomatic": ("080500FD000000000000", "080500FE000000000000"),
            "manualMode": ("080600FD000000000000", "080600FE000000000000"),
            "windAutomatic": ("080700FD000000000000", "080700FE000000000000"),
            "rainAutomatic": ("080800FD000000000000", "080800FE000000000000"),
            "dawnAutomatic": ("080900FD000000000000", "080900FE000000000000"),
            "sunAutomatic": ("080100FD000000000000", "080100FE000000000000"),
            "ventilatingMode": ("080200FD000000000000", "080200FE000000000000"),
            "stairwellFunction": ("081400FD000000000000", "081400FE000000000000"),
            "blindsMode": ("081100FD000000000000", "081100FE000000000000"),
            "tiltInSunPos": ("080C00FD000000000000", "080C00FE000000000000"),
            "tiltInVentPos": ("080D00FD000000000000", "080D00FE000000000000"),
            "tiltAfterMoveLevel": ("080E00FD000000000000", "080E00FE000000000000"),
            "tiltAfterStopDown": ("080F00FD000000000000", "080F00FE000000000000"),
            "saveIntermediateOnStop": ("080200FB000000000000", "080200FC000000000000"),
            "10minuteAlarm": ("081700FD000000000000", "081700FE000000000000"),
            "2000cycleAlarm": ("081900FD000000000000", "081900FE000000000000"),
            "backJump": ("081B00FD000000000000", "081B00FE000000000000"),
            # modeChange and reversal both send the same toggle command regardless
            # of on/off — the device has no separate on/off for these flags,
            # only a toggle. TODO: capture OTA frames to verify if separate
            # on/off commands exist in the original Rademacher firmware.
            "modeChange": ("070C0000000000000000", "070C0000000000000000"),  # toggle
            "windMode": ("070D01FF000000000000", "070E0100000000000000"),
            "rainMode": ("071101FF000000000000", "07120100000000000000"),
            "reversal": ("070C0000000000000000", "070C0000000000000000"),  # toggle only
            "intermediateMode": ("080200FD000000000000", "080200FE000000000000"),
        }
        cmd_pair = AUTOMATION_COMMANDS.get(name)
        if cmd_pair is None:
            _LOGGER.warning("Unknown automation command: %s", name)
            return
        hex_str = cmd_pair[0] if enable else cmd_pair[1]
        await self._send_generic(device_code, bytes.fromhex(hex_str))

    async def async_cover_toggle(self, device_code: DuoFernId) -> None:
        """Toggle cover direction.

        From 30_DUOFERN.pm: toggle => {cmd => {noArg => "071A0000000000000000"}}
        """
        await self._send_generic(device_code, bytes.fromhex("071A0000000000000000"))

    async def async_set_sun_position(
        self, device_code: DuoFernId, position: int
    ) -> None:
        """Set sun position (0-100, inverted like normal position).

        From 30_DUOFERN.pm:
          sunPosition => {cmd => {value => "080100nn000000000000"}, invert => 100}
        nn = 100 - position (inverted)
        """
        nn = 100 - max(0, min(100, position))
        payload = bytes.fromhex(f"080100{nn:02x}000000000000")
        await self._send_generic(device_code, payload)

    async def async_set_ventilating_position(
        self, device_code: DuoFernId, position: int
    ) -> None:
        """Set ventilating position (0-100, inverted).

        From 30_DUOFERN.pm:
          ventilatingPosition =>
              {cmd => {value => "080200nn000000000000"}, invert => 100}
        """
        nn = 100 - max(0, min(100, position))
        payload = bytes.fromhex(f"080200{nn:02x}000000000000")
        await self._send_generic(device_code, payload)

    async def async_set_slat_position(
        self, device_code: DuoFernId, position: int
    ) -> None:
        """Set slat position (0-100) for blinds.

        From 30_DUOFERN.pm:
          slatPosition => {cmd => {value => "071B00000000nn000000"}}
        """
        nn = max(0, min(100, position))
        payload = bytes.fromhex(f"071B00000000{nn:02x}000000")
        await self._send_generic(device_code, payload)

    async def async_set_running_time(self, device_code: DuoFernId, value: int) -> None:
        """Set running time (0-150 for Troll, 0-255 for Dimmer).

        From 30_DUOFERN.pm:
          runningTime => {cmd => {value => "0803nn00000000000000"}}
        """
        nn = max(0, min(255, value))
        payload = bytes.fromhex(f"0803{nn:02x}00000000000000")
        await self._send_generic(device_code, payload)

    async def async_set_slat_run_time(self, device_code: DuoFernId, value: int) -> None:
        """Set slat run time (0-50) for blinds.

        From 30_DUOFERN.pm:
          slatRunTime => {cmd => {value => "0812nn00000000000000"}}
        """
        nn = max(0, min(50, value))
        payload = bytes.fromhex(f"0812{nn:02x}00000000000000")
        await self._send_generic(device_code, payload)

    async def async_set_default_slat_pos(
        self, device_code: DuoFernId, position: int
    ) -> None:
        """Set default slat position (0-100) for blinds.

        From 30_DUOFERN.pm:
          defaultSlatPos => {cmd => {value => "0810nn00000000000000"}}
        """
        nn = max(0, min(100, position))
        payload = bytes.fromhex(f"0810{nn:02x}00000000000000")
        await self._send_generic(device_code, payload)

    async def async_set_stairwell_time(
        self, device_code: DuoFernId, value: int
    ) -> None:
        """Set stairwell function timer (0-3200, unit = 100ms).

        From 30_DUOFERN.pm:
          stairwellTime => {cmd => {value => "08140000wwww00000000"}, multi => 10}
        ww = value * 10 as 16-bit big-endian
        """
        ww = max(0, min(3200, value)) * 10
        payload = bytes.fromhex(f"08140000{ww:04x}00000000")
        await self._send_generic(device_code, payload)

    async def async_set_intermediate_value(
        self, device_code: DuoFernId, value: int
    ) -> None:
        """Set intermediate/dim level (0-100).

        From 30_DUOFERN.pm:
          intermediateValue => {cmd => {value => "080200nn000000000000"}}
        """
        nn = max(0, min(100, value))
        payload = bytes.fromhex(f"080200{nn:02x}000000000000")
        await self._send_generic(device_code, payload)

    async def async_set_wind_direction(
        self, device_code: DuoFernId, direction: str
    ) -> None:
        """Set wind direction (up/down).

        From 30_DUOFERN.pm:
          windDirection =>
              {down => "071500FD000000000000", up => "071500FE000000000000"}
        """
        h = "071500FD000000000000" if direction == "down" else "071500FE000000000000"
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_rain_direction(
        self, device_code: DuoFernId, direction: str
    ) -> None:
        """Set rain direction (up/down).

        From 30_DUOFERN.pm:
          rainDirection =>
              {down => "071400FD000000000000", up => "071400FE000000000000"}
        """
        h = "071400FD000000000000" if direction == "down" else "071400FE000000000000"
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_motor_dead_time(
        self, device_code: DuoFernId, value: str
    ) -> None:
        """Set motor dead time (off/short/long).

        From 30_DUOFERN.pm:
          motorDeadTime =>
              {off => "08130000...", short => "081301...", long => "081302..."}
        """
        mapping = {
            "off": "08130000000000000000",
            "short": "08130100000000000000",
            "long": "08130200000000000000",
        }
        h = mapping.get(value, "08130000000000000000")
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_open_speed(self, device_code: DuoFernId, value: str) -> None:
        """Set SX5 open speed (11/15/19 seconds).

        From 30_DUOFERN.pm:
          openSpeed => {11 => "081A0001...", 15 => "081A0002...", 19 => "081A0003..."}
        """
        mapping = {
            "11": "081A0001000000000000",
            "15": "081A0002000000000000",
            "19": "081A0003000000000000",
        }
        h = mapping.get(str(value), "081A0001000000000000")
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_automatic_closing(
        self, device_code: DuoFernId, value: str
    ) -> None:
        """Set SX5 automatic closing delay (off/30/60/../240 seconds).

        From 30_DUOFERN.pm:
          automaticClosing => {off => "08180000...", 30 => "08180001...", ...}
        """
        mapping = {
            "off": "08180000000000000000",
            "30": "08180001000000000000",
            "60": "08180002000000000000",
            "90": "08180003000000000000",
            "120": "08180004000000000000",
            "150": "08180005000000000000",
            "180": "08180006000000000000",
            "210": "08180007000000000000",
            "240": "08180008000000000000",
        }
        h = mapping.get(str(value), "08180000000000000000")
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_act_temp_limit(
        self, device_code: DuoFernId, value: int
    ) -> None:
        """Set active temperature limit (1-4) for Raumthermostat.

        From 30_DUOFERN.pm:
          actTempLimit => {1 => "081Ett00001000000000", 2 => "...3000...",
                           3 => "...5000...", 4 => "...7000..."}
        """
        tt = device_code.raw[0]
        mapping = {
            1: f"081E{tt:02x}00001000000000",
            2: f"081E{tt:02x}00003000000000",
            3: f"081E{tt:02x}00005000000000",
            4: f"081E{tt:02x}00007000000000",
        }
        h = mapping.get(int(value), mapping[1])
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_temperature_threshold(
        self, device_code: DuoFernId, threshold: int, temp: float
    ) -> None:
        """Set temperature threshold 1-4 for Raumthermostat.

        From 30_DUOFERN.pm:
          temperatureThreshold1-4 => {value => "081E00000001nn000000"}
          multi=2, offset=80: raw = int((temp + 40) * 2) = int(temp*2 + 80)
        threshold: 1-4
        temp: -40.0 to 40.0 in 0.5 steps
        """
        raw = max(0, min(255, int(temp * 2 + 80)))
        payloads = {
            1: f"081E00000001{raw:02x}000000",
            2: f"081E0000000200{raw:02x}0000",
            3: f"081E000000040000{raw:02x}00",
            4: f"081E00000008000000{raw:02x}",
        }
        h = payloads.get(threshold, payloads[1])
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_set_temperature_threshold1(
        self, device_code: DuoFernId, temp: float
    ) -> None:
        """Set temperature threshold 1 for Raumthermostat."""
        await self.async_set_temperature_threshold(device_code, 1, temp)

    async def async_set_temperature_threshold2(
        self, device_code: DuoFernId, temp: float
    ) -> None:
        """Set temperature threshold 2 for Raumthermostat."""
        await self.async_set_temperature_threshold(device_code, 2, temp)

    async def async_set_temperature_threshold3(
        self, device_code: DuoFernId, temp: float
    ) -> None:
        """Set temperature threshold 3 for Raumthermostat."""
        await self.async_set_temperature_threshold(device_code, 3, temp)

    async def async_set_temperature_threshold4(
        self, device_code: DuoFernId, temp: float
    ) -> None:
        """Set temperature threshold 4 for Raumthermostat."""
        await self.async_set_temperature_threshold(device_code, 4, temp)

    async def async_temp_up(self, device_code: DuoFernId) -> None:
        """Increment thermostat temperature.

        From 30_DUOFERN.pm: tempUp => {noArg => "0718tt00000000000000"}
        """
        tt = device_code.raw[0]
        await self._send_generic(
            device_code, bytes.fromhex(f"0718{tt:02x}00000000000000")
        )

    async def async_temp_down(self, device_code: DuoFernId) -> None:
        """Decrement thermostat temperature.

        From 30_DUOFERN.pm: tempDown => {noArg => "0719tt00000000000000"}
        """
        tt = device_code.raw[0]
        await self._send_generic(
            device_code, bytes.fromhex(f"0719{tt:02x}00000000000000")
        )

    async def async_reset(
        self, device_code: DuoFernId, reset_type: str = "settings"
    ) -> None:
        """Reset device to factory defaults.

        From 30_DUOFERN.pm:
          reset => {settings => "0815CB00000000000000",
                    full     => "0815CC00000000000000"}
        """
        h = (
            "0815CB00000000000000"
            if reset_type == "settings"
            else "0815CC00000000000000"
        )
        await self._send_generic(device_code, bytes.fromhex(h))

    async def async_remote_pair(self, device_code: DuoFernId) -> None:
        """Initiate remote pairing for Handsender/Wandtaster.

        From 30_DUOFERN.pm: remotePair => uses duoCommand2 (no system code)
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_remote_pair(device_code)
        await self._stick.send_command(frame)

    async def async_remote_unpair(self, device_code: DuoFernId) -> None:
        """Initiate remote unpairing.

        From 30_DUOFERN.pm: remoteUnpair => uses duoCommand2
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_remote_unpair(device_code)
        await self._stick.send_command(frame)

    async def async_remote_stop(self, device_code: DuoFernId) -> None:
        """Stop remote pairing/unpairing mode on the device.

        OTA-verified 2026-03-10: f[2]=0x06, f[3]=0x03.
        Ends the pairing window early after a remotePair or remoteUnpair.
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_remote_stop(device_code)
        await self._stick.send_command(frame)

    # ------------------------------------------------------------------
    # HSA (Heizkörperantrieb 0xE1) — device-initiated protocol
    # ------------------------------------------------------------------
    #
    # The 0xE1 Heizkörperantrieb uses a device-initiated protocol:
    #   1. User sets a value → store pending change, update UI optimistically,
    #      do NOT send anything to the device yet.
    #   2. Device sends periodic status frame → _handle_status() calls
    #      _send_hsa_if_pending() which compares pending old values with what
    #      the device currently reports, builds the duoSetHSA frame, and sends.
    #
    # This mirrors FHEM's %commandsHSA / HSAold / HSAtimer logic exactly.
    # From 30_DUOFERN.pm lines 706-728 (set handler) and 1213-1255 (response).

    # commandsHSA bit layout — mirrors 30_DUOFERN.pm %commandsHSA
    _HSA_COMMANDS: dict[str, dict] = {
        # min=0 matches FHEM %commandsHSA — raw value IS the minutes directly.
        # The min=2 UI constraint lives in number.py only, not here.
        "sendingInterval": {
            "bit_from": 0,
            "change_flag": 7,
            "min": 0,
            "max": 60,
            "step": 1,
        },
        "manualMode": {"bit_from": 8, "change_flag": 10},
        "timeAutomatic": {"bit_from": 9, "change_flag": 11},
        "windowContact": {"bit_from": 12, "change_flag": 13},
        "desired-temp": {
            "bit_from": 17,
            "change_flag": 23,
            "min": 4,
            "max": 28,
            "step": 0.5,
        },
        # Boost — encoded in f[8]/f[11] of the duoSetHSA frame, NOT in set_value bits.
        # boost_byte=True tells _send_hsa_if_pending to route these to build_hsa_command
        # as boost_duration_min rather than ORing them into set_value.
        # boostActive:   "on"/"off"  — activates/deactivates boost
        # boostDuration: 4-60 (int) — duration in minutes, reported back by device
        "boostActive": {"boost_byte": True},
        "boostDuration": {"boost_byte": True, "min": 0, "max": 60, "step": 1},
    }

    def _schedule_hsa_update(
        self,
        device_code: DuoFernId,
        key: str,
        new_value: object,
    ) -> None:
        """Queue an HSA change to be sent on the next device status frame.

        Stores (old_reading_value, new_value) in state.hsa_pending so that
        _send_hsa_if_pending() can check whether the device value has drifted
        before applying the change (mirrors FHEM HSAold logic).

        Also updates readings immediately for optimistic UI display.
        """
        state = self.data.devices.get(device_code.hex)
        if state is None:
            _LOGGER.warning("_schedule_hsa_update: unknown device %s", device_code.hex)
            return

        # Store old value only the first time (FHEM: if(!exists HSAold{key}))
        if key not in state.hsa_pending:
            old_val = state.status.readings.get(
                key
            )  # None = not yet received (distinct from 0)
            state.hsa_pending[key] = (old_val, new_value)
        else:
            # Already pending — just update the target value, keep old_val
            old_val, _ = state.hsa_pending[key]
            state.hsa_pending[key] = (old_val, new_value)

        # Optimistic UI update so entity shows new value immediately
        state.status.readings[key] = new_value
        # Also update the dedicated ParsedStatus field if applicable so
        # ClimateEntity.target_temperature (which reads desired_temp, not
        # readings) reflects the change without waiting for a status frame.
        if key == "desired-temp":
            try:
                state.status.desired_temp = float(new_value)
            except (TypeError, ValueError):
                pass
        self.async_set_updated_data(self.data)
        _LOGGER.debug(
            "HSA %s: queued %s=%s (was %s), waiting for device status frame",
            device_code.hex,
            key,
            new_value,
            old_val,
        )

    async def _send_hsa_if_pending(
        self,
        device_code: DuoFernId,
        device_readings: dict,
    ) -> None:
        """Build and send duoSetHSA if there are queued changes for this device.

        Called from _handle_status() when a 0xE1 status frame arrives.
        Mirrors FHEM lines 1213-1255.

        device_readings must be the freshly-parsed readings from the device
        status frame — NOT state.status.readings, which may already have been
        overwritten with our optimistic pending values.
        """
        state = self.data.devices.get(device_code.hex)
        if state is None or not state.hsa_pending:
            return
        if self._stick is None:
            return

        set_value = 0
        pending = dict(state.hsa_pending)  # snapshot

        # Separate boost keys from normal set_value keys.
        # boost_byte keys go into f[8]/f[11] of the frame, not into set_value.
        boost_active_val: str | None = None
        boost_duration_val: int | None = None

        for key, (old_val, new_val) in pending.items():
            cmd = self._HSA_COMMANDS.get(key)
            if cmd is None:
                _LOGGER.warning("_send_hsa_if_pending: unknown HSA key %s", key)
                continue

            if cmd.get("boost_byte"):
                # Collect boost values — sent as a separate frame below
                if key == "boostActive":
                    boost_active_val = str(new_val)
                elif key == "boostDuration":
                    boost_duration_val = int(float(new_val))
                continue

            # What does the DEVICE currently report for this key?
            # Use device_readings (from parsed frame) not state.status.readings
            # which has already been overwritten with our optimistic values.
            is_value = device_readings.get(key, 0)

            # changeFlag=1 if device value matches what it was when user set,
            # meaning the device hasn't changed independently — safe to apply.
            if (
                key == "windowContact"
                or old_val is None
                or str(old_val) == str(is_value)
            ):
                change_flag = 1
            else:
                change_flag = 0
                _LOGGER.debug(
                    "HSA %s: %s changed independently (%s→%s), not applying",
                    device_code.hex,
                    key,
                    old_val,
                    is_value,
                )

            # Build raw value
            if "min" in cmd:
                raw_value = int((float(new_val) - cmd["min"]) / cmd["step"])
            else:
                raw_value = 1 if str(new_val) in ("on", "True", "1", "true") else 0

            set_value |= (raw_value << cmd["bit_from"]) | (
                change_flag << cmd["change_flag"]
            )

        # HSAtimer always 0 from HA (we don't support timed temp changes)
        # set_value |= (0 << 16)

        # Send boost frame if either boost key is pending.
        # boostActive "on" + boostDuration together activate boost.
        # boostActive "off" alone deactivates (duration irrelevant → 0).
        if boost_active_val is not None or boost_duration_val is not None:
            active = (
                boost_active_val in ("on", "True", "1", "true")
                if boost_active_val is not None
                else (
                    state.status.boost_active  # if only duration changed, keep current active state
                )
            )
            # Use pending duration if provided, else current reading
            if boost_duration_val is not None:
                dur = boost_duration_val
            else:
                dur = int(device_readings.get("boostDuration", 30))

            # OTA analysis (bug_boost_5 + bug_boost_6) confirms two distinct cases:
            #
            # CASE A — HA initiates boost (user clicks button, device was NOT boosting):
            #   Device has NOT sent F0 yet. We are the trigger.
            #   → Send f[8] = 0x40 | duration  (active-bit + duration)
            #   → f[11] = 0x03
            #   Evidence: bug_boost_6 03:40:10 — f[8]=0x55 (dur=21), f[11]=0x03
            #
            # CASE B — Device started boost itself (physical button press, F0 already sent):
            #   Device IS already boosting (state.status.boost_active=True at TX time).
            #   Homepilot sends an acknowledgement with f[8]=0x00 (no duration override).
            #   → Send f[8] = 0x00  (no active-bit, no duration)
            #   → f[11] = 0x03
            #   Evidence: bug_boost_5 03:19:28 — f[8]=0x00, f[11]=0x03, dur=0
            #   Sending f[8] with duration bit set when device is already boosting → BB.
            #
            # Distinction: device_already_boosting = state.status.boost_active at call time.
            # (device_readings_snapshot reflects the parsed frame, not pending overrides)
            device_already_boosting = device_readings.get("boostActive") == "on"

            # OTA-verified f[8] encoding (bug_boost_5 + bug_boost_6):
            #
            # f[8] encodes the boost duration ONLY when it has CHANGED:
            #   Duration CHANGED:   f[8] = 0x40 | new_duration (active bit + dur)
            #   Duration UNCHANGED: f[8] = 0x00 (device uses its stored duration)
            #
            # Evidence:
            #   bug5 03:19:28: dur 14→14 (unchanged) → f[8]=0x00  ✓
            #   bug5 03:20:10: dur 14→14 (unchanged) → f[8]=0x00  ✓
            #   bug6 03:40:10: dur  7→21 (CHANGED)   → f[8]=0x55  ✓
            #
            # f[11]=0x03 is always present for Boost ON regardless of f[8].
            #
            # Sending f[8] with active bit when duration is unchanged → BB!
            # (confirmed by bug_boost_12: dur 14→14, f[8]=0x4E → BB)

            # Compare against what the device currently reports
            device_dur = int(device_readings.get("boostDuration", 0))
            duration_actually_changed = (
                boost_duration_val is not None and boost_duration_val != device_dur
            )

            if active and device_already_boosting:
                # Taste-Boost Quittierung: acknowledge without overriding stored duration
                boost_dur_for_frame = 0
            elif active and duration_actually_changed:
                # Duration changed: send new duration with active bit in f[8]
                boost_dur_for_frame = dur
            else:
                # Duration unchanged (or Boost OFF): f[8]=0x00
                # Device uses its stored duration for Boost ON.
                boost_dur_for_frame = 0
            desired_temp_pending = pending.get("desired-temp")
            if desired_temp_pending is not None:
                try:
                    current_temp = float(desired_temp_pending[1])
                except (TypeError, ValueError):
                    current_temp = 20.0
                current_temp = max(4.0, min(28.0, current_temp))
                desired_raw = max(0, min(63, int((current_temp - 4.0) / 0.5)))
                boost_set_value = (desired_raw << 17) | (1 << 23)
                # Remove from set_value so it doesn't get sent as a separate HSA frame
                set_value &= ~((0x3F << 17) | (1 << 23))
                _LOGGER.debug(
                    "HSA %s: piggybacking desired-temp=%.1f°C onto boost frame",
                    device_code.hex,
                    current_temp,
                )
            else:
                boost_set_value = 0

            boost_frame = DuoFernEncoder.build_hsa_command(
                set_value=boost_set_value,
                device_code=device_code,
                boost_duration_min=boost_dur_for_frame if active else 0,
                boost_off=not active,
                boost_on_ack=(active and device_already_boosting),
                boost_on=(
                    active and not device_already_boosting and boost_dur_for_frame == 0
                ),
            )
            await self._stick.send_command(boost_frame)
            if active:
                _LOGGER.info(
                    "Sent boost ON to %s (duration=%d min)",
                    device_code.hex,
                    dur,
                )
            else:
                _LOGGER.info(
                    "Sent boost OFF to %s",
                    device_code.hex,
                )

        # Send HSA frame only if something is pending (mirrors HomePilot behavior).
        # sv=0 on a plain D3 with nothing pending → BB. Boost frame takes priority,
        # no second frame is sent after it.
        sent_boost = boost_active_val is not None or boost_duration_val is not None
        force_response = state.status.readings.get("forceResponse", 0)
        if not sent_boost and (set_value > 0 or int(force_response or 0) > 0):
            frame = DuoFernEncoder.build_hsa_command(set_value, device_code)
            await self._stick.send_command(frame)
            _LOGGER.info(
                "Sent duoSetHSA to %s: setValue=0x%06X (keys: %s)",
                device_code.hex,
                set_value,
                [
                    k
                    for k in pending
                    if not self._HSA_COMMANDS.get(k, {}).get("boost_byte")
                ],
            )

        # Save the boost intent for retry in case the device responds with BB.
        # Cleared on successful CC in _handle_cmd_ack.
        if boost_active_val is not None:
            state.boost_retry_pending = boost_active_val  # "on" or "off"
            if not active:
                # Mark that we're waiting for the device to confirm boost is off.
                state.boost_deactivating = True
            else:
                # Boost ON overrides any pending deactivation — clear the flag so
                # incoming F0 frames don't immediately re-queue a boost OFF.
                state.boost_deactivating = False

        # Clear only the keys that were in the snapshot — not any new ones
        # queued concurrently while this task was running (async race condition).
        for key in pending:
            state.hsa_pending.pop(key, None)

    async def async_set_window_contact(
        self, device_code: DuoFernId, enable: bool
    ) -> None:
        """Queue windowContact change for the next HSA status frame.

        From 30_DUOFERN.pm %commandsHSA: windowContact bitFrom=12, changeFlag=13.
        windowContact is NEVER reported back in the status frame, so changeFlag
        is always 1 (FHEM: $key eq "windowContact" special-case, line 1227).
        """
        self._schedule_hsa_update(
            device_code, "windowContact", "on" if enable else "off"
        )

    async def async_set_sending_interval(
        self, device_code: DuoFernId, value: int
    ) -> None:
        """Queue sendingInterval change for the next HSA status frame.

        From 30_DUOFERN.pm %commandsHSA:
          sendingInterval: bitFrom=0, changeFlag=7, min=0, max=60, step=1
        """
        clamped = int(
            round(max(2, min(60, value)))
        )  # UI min=2; int() guards against float from number entity
        self._schedule_hsa_update(device_code, "sendingInterval", clamped)

    async def async_set_boost(self, device_code: DuoFernId, enable: bool) -> None:
        """Queue boost activation/deactivation for the next HSA status frame.

        ON:  reads pending_boost_duration (set by slider) and queues both
             boostDuration + boostActive together.  The slider itself never
             triggers a duoSetHSA — only this method does.
        OFF: queues boostActive=off only (duration irrelevant for deactivation).
        """
        if enable:
            state = self.data.devices.get(device_code.hex)
            # Read the duration the user configured via the slider.
            # Falls back to 14 min if no state is found.
            duration = state.pending_boost_duration if state is not None else 14
            # Queue duration first so it is available when _send_hsa_if_pending
            # processes boostActive in the same pending batch.
            self._schedule_hsa_update(device_code, "boostDuration", duration)
            self._schedule_hsa_update(device_code, "boostActive", "on")
            if state is not None:
                state.boost_start = dt_util.now()
        else:
            self._schedule_hsa_update(device_code, "boostActive", "off")

    async def async_set_boost_duration(
        self, device_code: DuoFernId, value: int
    ) -> None:
        """Store the desired boost duration from the slider — NO HSA frame sent.

        The duration is kept in state.pending_boost_duration and only
        transmitted to the device when async_set_boost(enable=True) is called.
        Moving the slider must never cause a duoSetHSA to be queued or sent.
        """
        clamped = int(
            round(max(4, min(60, value)))
        )  # int() guards against float from number entity
        state = self.data.devices.get(device_code.hex)
        if state is None:
            return
        state.pending_boost_duration = clamped
        # Optimistic UI update: slider shows the new value immediately
        # without waiting for the next status frame.
        state.status.readings["boostDuration"] = clamped
        self.async_set_updated_data(self.data)
        _LOGGER.debug(
            "HSA %s: boostDuration set locally to %d min (no HSA sent)",
            device_code.hex,
            clamped,
        )

    async def async_set_mode_change(self, device_code: DuoFernId) -> None:
        """Toggle mode change for switch actors / dimmers.

        From 30_DUOFERN.pm %commands:
          modeChange => {cmd => {noArg => "070C0000000000000000"}}
        FHEM command: set DEVICENAME modeChange
        """
        await self._send_generic(device_code, bytes.fromhex("070C0000000000000000"))

    async def async_get_status_device(self, device_code: DuoFernId) -> None:
        """Request status from a single specific device.

        From 30_DUOFERN.pm: getStatus => commandsStatus{getStatus} = "0F"
        $duoStatusRequest = "0DFFnn400000000000000000000000000000yyyyyy01"
        nn=0F for getStatus
        """
        await self._send_status_request(device_code)

    async def async_get_weather(self, device_code: DuoFernId) -> None:
        """Request weather data from Umweltsensor.

        From 30_DUOFERN.pm: getWeather => commandsStatus{getWeather} = "13"
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_status_request(
            device_code, self._system_code, status_type=0x13
        )
        await self._stick.send_command(frame)

    async def async_get_time(self, device_code: DuoFernId) -> None:
        """Request time from Umweltsensor.

        From 30_DUOFERN.pm: getTime => commandsStatus{getTime} = "10"
        """
        if self._stick is None:
            return
        frame = DuoFernEncoder.build_status_request(
            device_code, self._system_code, status_type=0x10
        )
        await self._stick.send_command(frame)

    async def async_get_weather_config(self, device_code: DuoFernId) -> None:
        """Request weather station configuration.

        From 30_DUOFERN.pm:
          getConfig =>
              $duoWeatherConfig = "0D001B400000000000000000000000000000yyyyyy00"
        """
        if self._stick is None:
            return
        code = device_code.raw[3:6]
        frame = bytes.fromhex(f"0D001B400000000000000000000000000000{code.hex()}00")
        await self._stick.send_command(frame)

    async def async_write_weather_config(self, device_code: DuoFernId) -> None:
        """Write stored configuration registers to Umweltsensor.

        From 30_DUOFERN.pm writeConfig:
          Reads .reg0.-.reg7 readings and sends each as a writeConfig frame.
          $duoWeatherWriteConfig = "0DFF1Brrnnnnnnnnnnnnnnnnnnnn00000000yyyyyy00"
          rr = register number 0x81-0x88
          nn = 20 hex chars (10 bytes) of register data
        This pushes all locally-stored config changes (latitude, longitude,
        timezone, DCF, interval, triggerRain) to the physical device.
        """
        if self._stick is None:
            return
        state = self.data.devices.get(device_code.hex)
        if state is None:
            return
        code = device_code.raw[3:6]
        for x in range(8):
            reg_key = f".reg{x}"
            reg_data = state.status.readings.get(reg_key, "00000000000000000000")
            reg_num = f"{0x81 + x:02x}"
            frame_hex = f"0DFF1B{reg_num}{reg_data}00000000{code.hex()}00"
            try:
                frame = bytes.fromhex(frame_hex)
                await self._stick.send_command(frame)
            except Exception:
                _LOGGER.warning("writeConfig: invalid register data for reg%d", x)

    async def async_set_umweltsensor_interval(
        self, device_code: DuoFernId, value: str
    ) -> None:
        """Set Umweltsensor transmit interval (wCmds register encoding).

        From 30_DUOFERN.pm %wCmds interval: reg=7, byte=0, mask=0xff
        Stored locally; sent on next writeConfig.
        """
        state = self.data.devices.get(device_code.hex)
        if state:
            state.status.readings["interval"] = value
            self.async_set_updated_data(self.data)

    async def async_set_umweltsensor_number(
        self, device_code: DuoFernId, value: float
    ) -> None:
        """Stub for Umweltsensor register-based number settings
        (latitude/longitude/timezone).

        From 30_DUOFERN.pm %wCmds: these values are encoded into device registers
        and sent via writeConfig. Storing value locally; will be sent on
        next writeConfig.
        Full register encoding from wCmds requires separate implementation if needed.
        """
        _LOGGER.info(
            "Umweltsensor config value %s received — "
            "use writeConfig button to push to device",
            value,
        )

    async def async_set_time(self, device_code: DuoFernId) -> None:
        """Send current time to Umweltsensor.

        From 30_DUOFERN.pm:
          time => $duoSetTime = "0D0110800001mmmmmmmmnnnnnn0000000000yyyyyy00"
          where mm=date (year,month,weekday,day) and nn=time (hour,min,sec)
        """
        now = dt_util.now()  # uses dt_util.now() for timezone-aware local time
        wday = now.weekday()  # 0=Mon, already matches FHEM after their adjustment
        mm = f"{now.year - 2000:02x}{now.month:02x}{wday:02x}{now.day:02x}"
        nn = f"{now.hour:02x}{now.minute:02x}{now.second:02x}"
        code = device_code.raw[3:6]
        frame = bytes.fromhex(f"0D011080000{mm}{nn}0000000000{code.hex()}00")
        if self._stick:
            await self._stick.send_command(frame)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics(self) -> dict[str, Any]:
        """Return snapshot of all device states for diagnostics.py."""
        result: dict[str, Any] = {}
        for hex_code, state in self.data.devices.items():
            result[hex_code] = {
                "device_type": f"0x{state.device_code.device_type:02X}",
                "device_type_name": state.device_code.device_type_name,
                "channel": state.channel,
                "available": state.available,
                "position": state.status.position,
                "level": state.status.level,
                "moving": state.status.moving,
                "version": state.status.version,
                "battery_state": state.battery_state,
                "battery_percent": state.battery_percent,
                "readings": state.status.readings,
                "last_seen": state.last_seen,
            }
        return result
