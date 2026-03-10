"""DuoFern protocol encoder / decoder.

Pure protocol logic — no Home Assistant or asyncio dependencies.
All frame construction uses bytearray; no fragile string replacement.

Frame format: 22 bytes (44 hex characters)
  Byte 0:     Message type / command class
  Bytes 1-11: Payload (command-specific)
  Bytes 12-14: Reserved / zeros
  Bytes 15-17: Dongle serial (system code, "zzzzzz" in FHEM templates)
  Bytes 18-20: Device code ("yyyyyy" in FHEM templates)
  Byte 21:    Flags / channel / trailer

Position convention (important!):
  DuoFern native (from device): 0 = fully open, 100 = fully closed
  Home Assistant convention:    0 = fully closed, 100 = fully open

  FHEM has an optional "positionInverse" attribute (default off) that
  flips this. The existing HA addon (cover.py) always inverts, which
  matches the HA convention. We keep that behaviour: inversion is always
  applied, no per-device option needed.

  Concretely:
    - parse_status() stores position in DuoFern-native (0=open,100=closed)
    - cover.py converts on read:  ha_pos = 100 - duofern_pos
    - cover.py converts on write: duofern_pos = 100 - ha_pos

  This matches exactly what the existing HA addon did:
    current_cover_position -> return 100 - state.status.position
    async_set_cover_position -> duofern_position = 100 - ha_position

Reference: 10_DUOFERNSTICK.pm and 30_DUOFERN.pm from FHEM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

from .const import (
    BINARY_SENSOR_DEVICE_TYPES,
    BLINDS_DEVICE_TYPES,
    OBSTACLE_COVER_TYPES,
    BLIND_MODE_READINGS,
    CLIMATE_DEVICE_TYPES,
    COMMANDS_HSA,
    COVER_DEVICE_TYPES,
    DEVICE_CHANNELS,
    DEVICE_STATUS_FORMAT_OVERRIDE,
    DEVICE_TYPES,
    ENVIRONMENTAL_SENSOR_DEVICE_TYPES,
    FRAME_SIZE_BYTES,
    FRAME_SIZE_HEX,
    LIGHT_DEVICE_TYPES,
    REMOTE_DEVICE_TYPES,
    SENSOR_DEVICE_TYPES,
    SENSOR_MESSAGES,
    STATUS_FORMAT_DEFAULT,
    STATUS_GROUPS,
    STATUS_IDS,
    STATUS_MAPPING,
    SUN_SENSOR_DEVICE_TYPES,
    SWITCH_DEVICE_TYPES,
    WIND_SENSOR_DEVICE_TYPES,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuoFernId:
    """A 3-byte DuoFern identifier stored as bytes.

    Used for both device codes (e.g. 40ABCD) and system codes (e.g. 6F1234).
    Optionally carries a 2-char channel suffix (e.g. "01", "02") making it
    an 8-digit channel address as used by FHEM for multi-channel devices.

    From 30_DUOFERN.pm:
      if(length($code) == 8) { # define a channel
        $hash->{device} = $devName;         # readable ref to device name
        $hash->{chanNo} = $chn;             # readable ref to Channel
        $devHash->{"channel_$chn"} = $name; # reference in device as well
      }
    """

    raw: bytes
    channel: str | None = None  # "01", "02", ... or None for base device

    def __post_init__(self) -> None:
        if len(self.raw) != 3:
            raise ValueError(f"DuoFernId must be 3 bytes, got {len(self.raw)}")

    @classmethod
    def from_hex(cls, hex_str: str) -> "DuoFernId":
        h = hex_str.upper().strip()
        if len(h) != 6:
            raise ValueError(f"Expected 6 hex chars, got {len(h)}: {hex_str!r}")
        return cls(raw=bytes.fromhex(h))

    @classmethod
    def from_hex_with_channel(cls, hex_str: str) -> "DuoFernId":
        """Create from 8-character hex string like '43ABCD01'."""
        h = hex_str.upper().strip()
        if len(h) == 8:
            return cls(raw=bytes.fromhex(h[:6]), channel=h[6:8])
        if len(h) == 6:
            return cls(raw=bytes.fromhex(h))
        raise ValueError(f"Expected 6 or 8 hex chars, got {len(h)}: {hex_str!r}")

    def with_channel(self, channel: str) -> "DuoFernId":
        return DuoFernId(raw=self.raw, channel=channel)

    @property
    def hex(self) -> str:
        return self.raw.hex().upper()

    @property
    def full_hex(self) -> str:
        if self.channel:
            return self.hex + self.channel
        return self.hex

    @property
    def device_type(self) -> int:
        return self.raw[0]

    @property
    def device_type_name(self) -> str:
        return DEVICE_TYPES.get(self.raw[0], f"Unknown (0x{self.raw[0]:02X})")

    @property
    def is_cover(self) -> bool:
        return self.raw[0] in COVER_DEVICE_TYPES

    @property
    def is_blinds(self) -> bool:
        """Return True if this device supports slat/blinds mode."""
        return self.raw[0] in BLINDS_DEVICE_TYPES

    @property
    def is_obstacle_cover(self) -> bool:
        """Return True if this cover can report obstacle/block detection."""
        return self.raw[0] in OBSTACLE_COVER_TYPES

    @property
    def is_light(self) -> bool:
        return self.raw[0] in LIGHT_DEVICE_TYPES

    @property
    def is_switch(self) -> bool:
        return self.raw[0] in SWITCH_DEVICE_TYPES

    @property
    def is_climate(self) -> bool:
        return self.raw[0] in CLIMATE_DEVICE_TYPES

    @property
    def is_binary_sensor(self) -> bool:
        return self.raw[0] in BINARY_SENSOR_DEVICE_TYPES

    @property
    def is_sensor(self) -> bool:
        return self.raw[0] in SENSOR_DEVICE_TYPES

    @property
    def is_remote(self) -> bool:
        return self.raw[0] in REMOTE_DEVICE_TYPES

    @property
    def is_env_sensor(self) -> bool:
        """True for dedicated external environmental sensors (A5/AF/A9/AA).

        These have no get/set commands in FHEM — pure event senders.
        """
        return self.raw[0] in ENVIRONMENTAL_SENSOR_DEVICE_TYPES

    @property
    def is_sun_sensor(self) -> bool:
        """True if device sends startSun/endSun (sensorMsg 0708/070A).

        Includes 0x61 RolloTron Comfort Master (built-in brightness sensor).
        """
        return self.raw[0] in SUN_SENSOR_DEVICE_TYPES

    @property
    def is_wind_sensor(self) -> bool:
        """True if device sends startWind/endWind (sensorMsg 070D/070E)."""
        return self.raw[0] in WIND_SENSOR_DEVICE_TYPES

    @property
    def has_channels(self) -> bool:
        return self.raw[0] in DEVICE_CHANNELS

    @property
    def channel_list(self) -> list[str]:
        return DEVICE_CHANNELS.get(self.raw[0], [])

    def __repr__(self) -> str:
        return f"DuoFernId({self.full_hex})"

    def __hash__(self) -> int:
        return hash((self.raw, self.channel))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DuoFernId):
            return self.raw == other.raw and self.channel == other.channel
        return NotImplemented


@dataclass
class ParsedStatus:
    """Result of parsing a DuoFern status frame.

    Position convention (matches existing HA addon behaviour):
      position field is stored in DuoFern-native: 0 = open, 100 = closed.
      cover.py inverts on read/write: ha_pos = 100 - duofern_pos.

    From 30_DUOFERN.pm state determination after parsing:
      if ($format =~ m/^(21|23|23a|24|24a)/) {
        $state = $statusValue{position} if defined($statusValue{position});
        $state = "opened" if ($state eq "0");
        $state = "closed" if ($state eq "100");
      }
    """

    readings: dict[str, object] = field(default_factory=dict)
    position: int | None = None  # 0=open, 100=closed (DuoFern native)
    level: int | None = None  # 0-100
    moving: str = "stop"
    version: str | None = None

    measured_temp: float | None = None
    desired_temp: float | None = None

    # Boost mode fields — only populated for 0xE1 Heizkörperantrieb (format 29).
    # boost_active: True when frame subtype == 0xF0 (desired-temp = 28°C).
    # boost_duration_min: originally set duration in minutes (byte[12] & 0x3F).
    #   Does NOT count down — always shows the value from the last Boost-ON command.
    #   Value 9 is the factory default (no boost ever set).
    boost_active: bool = False
    boost_duration_min: int = 0

    missing_ack: bool = False  # NACK 810108AA
    not_initialized: bool = False  # NACK 81010C55

    device_code: str | None = None
    channel: str | None = None


@dataclass
class SensorEvent:
    """Sensor / button event message.

    From 30_DUOFERN.pm:
      #Wandtaster, Funksender UP, Handsender, Sensoren
    """

    device_code: str
    channel: str
    event_name: str
    state: str | None = None
    raw_msg_id: str = ""


@dataclass
class WeatherData:
    """Parsed weather data from the Umweltsensor (0x69).

    From 30_DUOFERN.pm:
      #Umweltsensor Wetter
    """

    brightness: float | None = None
    sun_direction: float | None = None
    sun_height: float | None = None
    temperature: float | None = None
    is_raining: bool | None = None
    wind: float | None = None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CoverCommand(IntEnum):
    """Cover command codes from 30_DUOFERN.pm %commands."""

    UP = 0x0701
    STOP = 0x0702
    DOWN = 0x0703
    POSITION = 0x0707
    TOGGLE = 0x071A
    DUSK = 0x0709  # dusk => "070901FF000000000000"
    DAWN = 0x0713  # dawn => "071301FF000000000000"


class SwitchCommand(IntEnum):
    """Switch / dimmer on/off from 30_DUOFERN.pm %commands."""

    OFF = 0x0E02
    ON = 0x0E03


class AutomationCommand(IntEnum):
    """Automation on/off command codes from 30_DUOFERN.pm %commands.

    Pattern: 0804/0805/0806/0807/0808/0809/0801/0802...
    on  = FD, off = FE suffix.
    """

    SUN_AUTOMATIC_ON = 0x0801
    VENTILATING_MODE_ON = 0x0802
    TIME_AUTOMATIC_ON = 0x0804
    DUSK_AUTOMATIC_ON = 0x0805
    MANUAL_MODE_ON = 0x0806
    WIND_AUTOMATIC_ON = 0x0807
    RAIN_AUTOMATIC_ON = 0x0808
    DAWN_AUTOMATIC_ON = 0x0809


class MessageType(IntEnum):
    """Top-level message type byte. From 10_DUOFERNSTICK.pm."""

    INIT1 = 0x01
    SET_PAIRS = 0x03
    START_PAIR = 0x04
    STOP_PAIR = 0x05
    PAIR_RESP = 0x06
    START_UNPAIR = 0x07
    STOP_UNPAIR = 0x08
    SET_DONGLE = 0x0A
    COMMAND = 0x0D
    INIT2 = 0x0E
    STATUS = 0x0F
    INIT_END = 0x10
    INIT3 = 0x14
    ACK = 0x81


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


class DuoFernEncoder:
    """Builds DuoFern protocol frames as bytearray.

    Frame template from 30_DUOFERN.pm:
      my $duoCommand = "0Dccnnnnnnnnnnnnnnnnnnnn000000zzzzzzyyyyyy00"
        cc     = channel byte
        nnn... = 10-byte command payload
        000000 = reserved
        zzzzzz = system code
        yyyyyy = device code
    """

    @staticmethod
    def _frame() -> bytearray:
        return bytearray(FRAME_SIZE_BYTES)

    # -- Init sequence (DUOFERNSTICK_DoInit) --

    @staticmethod
    def build_init1() -> bytearray:
        """duoInit1 = '01000000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x01
        return f

    @staticmethod
    def build_init2() -> bytearray:
        """duoInit2 = '0E000000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x0E
        return f

    @staticmethod
    def build_set_dongle(system_code: DuoFernId) -> bytearray:
        """duoSetDongle = '0Azzzzzz000100...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x0A
        f[1:4] = system_code.raw
        f[4] = 0x00
        f[5] = 0x01
        return f

    @staticmethod
    def build_init3() -> bytearray:
        """duoInit3 = '14140000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x14
        f[1] = 0x14
        return f

    @staticmethod
    def build_set_pair(index: int, device_code: DuoFernId) -> bytearray:
        """duoSetPairs = '03nnyyyyyy0000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x03
        f[1] = index & 0xFF
        f[2:5] = device_code.raw
        return f

    @staticmethod
    def build_init_end() -> bytearray:
        """duoInitEnd = '10010000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x10
        f[1] = 0x01
        return f

    @staticmethod
    def build_ack() -> bytearray:
        """duoACK = '81000000...'

        From DUOFERNSTICK_Parse: if not ACK -> send ACK back immediately.
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x81
        return f

    # -- Status requests --

    @staticmethod
    def build_status_request_broadcast() -> bytearray:
        """duoStatusRequest broadcast (FFFFFF).

        From 10_DUOFERNSTICK.pm:
          "0DFF0F400000000000000000000000000000FFFFFF01"
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = 0xFF
        f[2] = 0x0F
        f[3] = 0x40
        f[18] = 0xFF
        f[19] = 0xFF
        f[20] = 0xFF
        f[21] = 0x01
        return f

    @staticmethod
    def build_status_request(
        device_code: DuoFernId,
        system_code: DuoFernId,
        status_type: int = 0x0F,
    ) -> bytearray:
        """Per-device status request.

        From 30_DUOFERN.pm:
          $duoStatusRequest = "0DFFnn400000000000000000000000000000yyyyyy01"
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = 0xFF
        f[2] = status_type
        f[3] = 0x40
        f[18:21] = device_code.raw
        f[21] = 0x01
        return f

    # -- Cover / actor commands --

    @staticmethod
    def build_cover_command(
        command: CoverCommand,
        device_code: DuoFernId,
        system_code: DuoFernId,
        position: int | None = None,
        timer: bool = False,
        channel: int = 0x01,
    ) -> bytearray:
        """Build a cover command frame.

        From 30_DUOFERN.pm %commands:
          up    = "0701tt00000000000000"  tt = timer flag
          stop  = "07020000000000000000"
          down  = "0703tt00000000000000"
          pos   = "0707ttnn000000000000"  nn = position (0=open,100=closed)
          toggle= "071A0000000000000000"
          dusk  = "070901FF000000000000"  move to dusk position
          dawn  = "071301FF000000000000"  move to dawn position

        dusk/dawn are explicit position commands, not the same as duskAutomatic.
        Position is DuoFern-native (0=open,100=closed); inversion in cover.py.
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = channel
        f[2] = (command >> 8) & 0xFF
        f[3] = command & 0xFF
        timer_byte = 0x01 if timer else 0x00

        if command in (CoverCommand.UP, CoverCommand.DOWN):
            f[4] = timer_byte
        elif command == CoverCommand.POSITION:
            f[4] = timer_byte
            if position is not None:
                f[5] = max(0, min(100, position))
            else:
                _LOGGER.warning("POSITION command sent without position value")
        elif command == CoverCommand.DUSK:
            # dusk = "070901FF000000000000"
            f[4] = 0x01
            f[5] = 0xFF
        elif command == CoverCommand.DAWN:
            # dawn = "071301FF000000000000"
            f[4] = 0x01
            f[5] = 0xFF
        # STOP, TOGGLE: no extra parameters

        f[15:18] = system_code.raw
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_generic_command(
        cmd_bytes: bytes,
        device_code: DuoFernId,
        system_code: DuoFernId,
        channel: int = 0x01,
    ) -> bytearray:
        """Build a generic command from a 10-byte payload.

        Used for automation commands (sunAutomatic, timeAutomatic, etc.)
        where the payload is known from %commands in 30_DUOFERN.pm.

        From 30_DUOFERN.pm: $duoCommand = "0Dccnnnnnnnnnnnnnnnnnnnn000000zzzzzzyyyyyy00"
          cc      = channel
          nnnnn.. = 10-byte payload (cmd_bytes)
          zzzzzz  = system code
          yyyyyy  = device code
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = channel
        for i, b in enumerate(cmd_bytes[:10]):
            f[2 + i] = b
        f[15:18] = system_code.raw
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_switch_command(
        command: SwitchCommand,
        device_code: DuoFernId,
        system_code: DuoFernId,
        channel: int = 0x01,
        timer: bool = False,
    ) -> bytearray:
        """Build on/off command.

        From 30_DUOFERN.pm %commands:
          off => "0E02tt00000000000000"
          on  => "0E03tt00000000000000"
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = channel
        f[2] = (command >> 8) & 0xFF
        f[3] = command & 0xFF
        f[4] = 0x01 if timer else 0x00
        f[15:18] = system_code.raw
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_dim_command(
        level: int,
        device_code: DuoFernId,
        system_code: DuoFernId,
        channel: int = 0x01,
        timer: bool = False,
    ) -> bytearray:
        """Build level command for dimmers.

        From 30_DUOFERN.pm %commands:
          level => "0707ttnn000000000000"
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = channel
        f[2] = 0x07
        f[3] = 0x07
        f[4] = 0x01 if timer else 0x00
        f[5] = max(0, min(100, level))
        f[15:18] = system_code.raw
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_desired_temp_command(
        temp: float,
        device_code: DuoFernId,
        system_code: DuoFernId,
        timer: bool = False,
    ) -> bytearray:
        """Build desired-temp command for Raumthermostat / HSA.

        From 30_DUOFERN.pm %commands:
          desired-temp => "0722tt0000wwww000000"
          min=-40, max=80, multi=10, offset=400
          ww = (temp * 10 + 400) as 16-bit big-endian
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = 0x01
        f[2] = 0x07
        f[3] = 0x22
        f[4] = 0x01 if timer else 0x00
        # ww at bytes 6-7 (offset 6 in payload = frame bytes 8-9)
        ww = int(temp * 10 + 400)
        ww = max(0, min(0xFFFF, ww))
        f[8] = (ww >> 8) & 0xFF
        f[9] = ww & 0xFF
        f[15:18] = system_code.raw
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_hsa_command(
        set_value: int,
        device_code: "DuoFernId",
        boost_duration_min: int = 0,
        boost_off: bool = False,
    ) -> bytearray:
        """Build duoSetHSA command for Heizkörperantrieb (0xE1).

        From 30_DUOFERN.pm:
          $duoSetHSA = "0D011D80nnnnnn0000000000000000000000yyyyyy00"
          nnnnnn = 24-bit setValue (little-endian in hex pairs)
          yyyyyy = device code

        Bit layout of setValue (commandsHSA):
          bits  0-6:  sendingInterval value  (0-60)
          bit   7:    sendingInterval changeFlag
          bit   8:    manualMode value        (0/1)
          bit   9:    timeAutomatic value     (0/1)
          bit   10:   manualMode changeFlag
          bit   11:   timeAutomatic changeFlag
          bit   12:   windowContact value     (0/1)
          bit   13:   windowContact changeFlag
          bit   16:   HSAtimer                (0/1, always 0 from HA)
          bits 17-22: desired-temp rawValue   int((temp-4)/0.5)
          bit   23:   desired-temp changeFlag
        """
        f = bytearray(22)
        f[0] = 0x0D
        f[1] = 0x01
        f[2] = 0x1D
        f[3] = 0x80
        # nnnnnn: 3 bytes, big-endian
        f[4] = (set_value >> 16) & 0xFF
        f[5] = (set_value >> 8) & 0xFF
        f[6] = set_value & 0xFF
        # bytes 7-17 = 0x00 (duoSetHSA has no system_code field)
        # From FHEM: "0D011D80nnnnnn0000000000000000000000yyyyyy00"
        #              bytes 15-17 are 0x00, NOT system code!
        # Boost bytes — OTA-verified (Homepilot capture, radio payload byte[1:] maps
        # 1:1 to USB stick payload byte[1:], only the first byte differs 0x11 vs 0x0D):
        #   Boost ON:  f[8] = 0x40 | duration_min  (bit6=active, bits5-0=minutes 4-60)
        #              f[11] = 0x03
        #   Boost OFF: f[8] = 0x00
        #              f[11] = 0x02  ← confirmed from Homepilot OTA capture
        # Verified OTA: Boost ON 22min→f[8]=0x56, 46min→0x6E, 56min→0x78.
        if boost_duration_min > 0:
            clamped = max(4, min(60, boost_duration_min))
            f[8] = 0x40 | (clamped & 0x3F)
            f[11] = 0x03
        elif boost_off:
            f[11] = 0x02
        f[18:21] = device_code.raw
        f[21] = 0x00
        return f

    # -- Pairing --

    @staticmethod
    def build_start_pair() -> bytearray:
        """duoStartPair = '04000000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x04
        return f

    @staticmethod
    def build_stop_pair() -> bytearray:
        """duoStopPair = '05000000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x05
        return f

    @staticmethod
    def build_start_unpair() -> bytearray:
        """duoStartUnpair = '07000000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x07
        return f

    @staticmethod
    def build_stop_unpair() -> bytearray:
        """duoStopUnpair = '08000000...'"""
        f = DuoFernEncoder._frame()
        f[0] = 0x08
        return f

    @staticmethod
    def build_remote_pair(device_code: DuoFernId) -> bytearray:
        """duoRemotePair — direct pairing without physical button.

        From 10_DUOFERNSTICK.pm:
          "0D0106010000000000000000000000000000yyyyyy00"
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = 0x01
        f[2] = 0x06
        f[3] = 0x01
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_remote_unpair(device_code: DuoFernId) -> bytearray:
        """duoRemoteUnpair — direct unpairing without physical button.

        From 30_DUOFERN.pm:
          remoteUnpair => {cmd => {noArg => "06020000000000000000"}}
        Same frame structure as build_remote_pair with f[3]=0x02.
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = 0x01
        f[2] = 0x06
        f[3] = 0x02
        f[18:21] = device_code.raw
        return f

    @staticmethod
    def build_remote_stop(device_code: DuoFernId) -> bytearray:
        """Stop remote pairing/unpairing mode on the device.

        OTA-verified 2026-03-10 (capture_stop_1.txt, device 4696e9):
          Radio frame f[2]=0x06, f[3]=0x03 (USB: 0x0D prefix, payload identical).
        Sent after remotePair or remoteUnpair to end the pairing window early.
        """
        f = DuoFernEncoder._frame()
        f[0] = 0x0D
        f[1] = 0x01
        f[2] = 0x06
        f[3] = 0x03
        f[18:21] = device_code.raw
        return f


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


class DuoFernDecoder:
    """Parses DuoFern protocol frames into typed Python objects."""

    @staticmethod
    def _ensure_bytes(data: bytes | bytearray | str) -> bytearray:
        if isinstance(data, str):
            if len(data) != FRAME_SIZE_HEX:
                raise ValueError(
                    f"Hex string must be {FRAME_SIZE_HEX} chars, got {len(data)}"
                )
            return bytearray.fromhex(data)
        if isinstance(data, (bytes, bytearray)):
            if len(data) != FRAME_SIZE_BYTES:
                raise ValueError(
                    f"Frame must be {FRAME_SIZE_BYTES} bytes, got {len(data)}"
                )
            return bytearray(data)
        raise TypeError(f"Unsupported type: {type(data)}")

    # -- Message type checks (all from DUOFERNSTICK_Parse / DUOFERN_Parse) --

    @staticmethod
    def is_ack(data: bytes | bytearray | str) -> bool:
        """Frame is a generic ACK (0x81...). From 10_DUOFERNSTICK.pm."""
        return DuoFernDecoder._ensure_bytes(data)[0] == MessageType.ACK

    @staticmethod
    def is_status_response(data: bytes | bytearray | str) -> bool:
        """Actor status response.

        From 30_DUOFERN.pm:
          #Status Nachricht Aktor
          if ($msg =~ m/0FFF0F.{38}/) { ... }

        Format 0x2A is explicitly excluded: it is a device-to-stick ACK sent
        after a boost activation (payload always 08 F2 55) and must never be
        parsed as a status frame — doing so wipes all entity state because
        parse_status() returns an empty ParsedStatus for the unknown format.
        """
        f = DuoFernDecoder._ensure_bytes(data)
        if len(f) < 4:
            return False
        if f[3] == 0x2A:  # Gerät-ACK nach Boost — ignorieren (NOTES.md: "nicht parsen")
            return False
        return f[0] == 0x0F and f[1] == 0xFF and f[2] == 0x0F

    @staticmethod
    def is_pair_response(data: bytes | bytearray | str) -> bool:
        """#Device paired — if ($msg =~ m/^0602/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x06 and f[1] == 0x02

    @staticmethod
    def is_unpair_response(data: bytes | bytearray | str) -> bool:
        """#Device unpaired — if ($msg =~ m/^0603/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x06 and f[1] == 0x03

    @staticmethod
    def is_sensor_message(data: bytes | bytearray | str) -> bool:
        """#Wandtaster, Funksender UP, Handsender, Sensoren"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x0F and f[2] in (0x07, 0x0E)

    @staticmethod
    def is_weather_data(data: bytes | bytearray | str) -> bool:
        """#Umweltsensor Wetter — if ($msg =~ m/0F..1322/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x0F and f[2] == 0x13 and f[3] == 0x22

    @staticmethod
    def is_time_response(data: bytes | bytearray | str) -> bool:
        """#Umweltsensor/Handzentrale Zeit — if ($msg =~ m/0F..1020/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x0F and f[2] == 0x10 and f[3] == 0x20

    @staticmethod
    def is_weather_config(data: bytes | bytearray | str) -> bool:
        """#Umweltsensor Konfiguration — if ($msg =~ m/0FFF1B2[1-8]/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x0F and f[1] == 0xFF and f[2] == 0x1B and 0x21 <= f[3] <= 0x28

    @staticmethod
    def is_battery_status(data: bytes | bytearray | str) -> bool:
        """#Sensoren Batterie — if ($msg =~ m/0FFF1323/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x0F and f[1] == 0xFF and f[2] == 0x13 and f[3] == 0x23

    @staticmethod
    def is_cmd_ack(data: bytes | bytearray | str) -> bool:
        """#ACK, Befehl vom Aktor empfangen — if ($msg =~ m/^810003CC/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x81 and f[1] == 0x00 and f[2] == 0x03 and f[3] == 0xCC

    @staticmethod
    def is_missing_ack(data: bytes | bytearray | str) -> bool:
        """#NACK, Befehl nicht vom Aktor empfangen
        — if ($msg =~ m/^810108AA/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x81 and f[1] == 0x01 and f[2] == 0x08 and f[3] == 0xAA

    @staticmethod
    def is_not_initialized(data: bytes | bytearray | str) -> bool:
        """#NACK, Aktor nicht initialisiert — if ($msg =~ m/^81010C55/) { ... }"""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x81 and f[1] == 0x01 and f[2] == 0x0C and f[3] == 0x55

    @staticmethod
    def is_broadcast_ack(data: bytes | bytearray | str) -> bool:
        """Broadcast status ack (0FFF11...) — silently ignored."""
        f = DuoFernDecoder._ensure_bytes(data)
        return f[0] == 0x0F and f[1] == 0xFF and f[2] == 0x11

    @staticmethod
    def should_dispatch(data: bytes | bytearray | str) -> bool:
        """True if this frame should be dispatched to device handlers.

        From 10_DUOFERNSTICK.pm DUOFERNSTICK_Parse:
          ACKs (81...) consumed by write-queue, not dispatched.
          Broadcast status ack (0FFF11...) silently ignored.
        """
        f = DuoFernDecoder._ensure_bytes(data)
        if f[0] == 0x81:
            return False
        if f[0] == 0x0F and f[1] == 0xFF and f[2] == 0x11:
            return False
        return True

    # -- Device code extraction --

    @staticmethod
    def extract_device_code(data: bytes | bytearray | str) -> DuoFernId:
        """Extract device code from a frame.

        From DUOFERN_Parse in 30_DUOFERN.pm:
          $code = substr($msg, 30, 6) => bytes 15-17 (normal)
          $code = substr($msg, 36, 6) => bytes 18-20 (ACK 81...)
        """
        f = DuoFernDecoder._ensure_bytes(data)
        if f[0] == MessageType.ACK:
            return DuoFernId(raw=bytes(f[18:21]))
        return DuoFernId(raw=bytes(f[15:18]))

    @staticmethod
    def extract_device_code_from_status(data: bytes | bytearray | str) -> DuoFernId:
        """Extract device code from status message (always bytes 15-17)."""
        f = DuoFernDecoder._ensure_bytes(data)
        return DuoFernId(raw=bytes(f[15:18]))

    # -- Status parsing --

    @staticmethod
    def _read_word(frame: bytearray, pos: int) -> int:
        """Read 16-bit word from payload position N.

        From 30_DUOFERN.pm:
          $value = hex(substr($msg, 6 + $stPos*2, 4))
          hex offset 6 = byte 3 of frame.
        """
        byte_offset = 3 + pos
        if byte_offset + 1 >= FRAME_SIZE_BYTES:
            return 0
        return (frame[byte_offset] << 8) | frame[byte_offset + 1]

    @staticmethod
    def _extract_bits(word: int, from_bit: int, to_bit: int) -> int:
        """Extract bits from_bit..to_bit (inclusive).

        From 30_DUOFERN.pm:
          my $stLen = $stTo - $stFrom + 1;
          $value = ($value >> $stFrom) & ((1<<$stLen) - 1);
        """
        length = to_bit - from_bit + 1
        return (word >> from_bit) & ((1 << length) - 1)

    @staticmethod
    def _apply_mapping(raw: int, map_key: str) -> object:
        """Apply %statusMapping transform.

        From 30_DUOFERN.pm mapping logic for scaleF, scale, hex, string lists.
        """
        if map_key not in STATUS_MAPPING:
            return raw
        mapping = STATUS_MAPPING[map_key]
        if map_key in ("onOff", "upDown", "moving", "motor", "closeT", "openS"):
            idx = int(raw)
            return mapping[idx] if 0 <= idx < len(mapping) else str(raw)
        if map_key == "hex":
            val = int(raw)
            return f"{(val >> 4) & 0x0F}.{val & 0x0F}"
        factor, offset = mapping[0], mapping[1]
        if map_key == "scale10":
            return (raw - offset) / factor
        return round((raw - offset) / factor, 1)

    @staticmethod
    def _determine_format(frame: bytearray, device_code: DuoFernId) -> str:
        """Determine status format string.

        Priority:
          1. Per-device-type override (DEVICE_STATUS_FORMAT_OVERRIDE)
          2. Format encoded in frame byte 3
          3. STATUS_FORMAT_DEFAULT ("21")
        """
        if device_code.device_type in DEVICE_STATUS_FORMAT_OVERRIDE:
            return DEVICE_STATUS_FORMAT_OVERRIDE[device_code.device_type]
        fmt_str = format(frame[3], "02X").lstrip("0") or "0"
        if fmt_str in STATUS_GROUPS:
            return fmt_str
        return STATUS_FORMAT_DEFAULT

    @staticmethod
    def parse_status(
        data: bytes | bytearray | str,
        channel: str = "01",
    ) -> ParsedStatus:
        """Parse a status response frame into ParsedStatus.

        Full implementation of the %statusGroups / %statusIds / %statusMapping
        parsing loop from DUOFERN_Parse in 30_DUOFERN.pm.

        Position/invert handling:
          invert is applied unconditionally (always positionInverse=1 behaviour).
          Result: 0=open, 100=closed (DuoFern native).
          cover.py then does ha_pos = 100 - position (HA convention).

        From 30_DUOFERN.pm:
          if((exists $statusIds{$statusId}{invert}) && ($positionInverse eq "1")) {
            $value = $statusIds{$statusId}{invert} - $value;
          }

        blindsMode cleanup:
          if (defined($statusValue{blindsMode})
              && ($statusValue{blindsMode} eq "off")) {
            foreach my $reading (@readingsBlindMode) { delete ... }
          }

        #Heizkörperantrieb (0xE1) bidirectional protocol handled in coordinator.py.
        """
        frame = DuoFernDecoder._ensure_bytes(data)
        result = ParsedStatus()

        if not DuoFernDecoder.is_status_response(frame):
            _LOGGER.warning("parse_status called on non-status frame: %s", frame.hex())
            return result

        device_code = DuoFernDecoder.extract_device_code_from_status(frame)
        result.device_code = device_code.hex

        # Firmware version: most formats encode it in frame[12] as nibbles (FHEM:
        # substr($msg,24,1).".".substr($msg,25,1)). Format 29 (0xE1) uses StatusID
        # 998 via the normal STATUS_GROUPS parse path instead — overridden below.
        ver_byte = frame[12]
        result.version = (
            f"{(ver_byte >> 4) & 0x0F}.{ver_byte & 0x0F}" if ver_byte != 0 else None
        )

        fmt = DuoFernDecoder._determine_format(frame, device_code)
        readings: dict[str, object] = {}

        for sid in STATUS_GROUPS.get(fmt, []):
            spec = STATUS_IDS.get(sid)
            if spec is None:
                continue
            chan_spec = spec["chan"].get(channel) or spec["chan"].get("01")
            if chan_spec is None:
                continue

            word = DuoFernDecoder._read_word(frame, chan_spec["position"])
            raw = DuoFernDecoder._extract_bits(word, chan_spec["from"], chan_spec["to"])
            name: str = spec["name"]

            if "invert" in spec:
                # Apply inversion unconditionally — matches HA convention.
                raw = spec["invert"] - raw
                value: object = raw
            elif "map" in spec:
                value = DuoFernDecoder._apply_mapping(raw, spec["map"])
            else:
                value = raw

            readings[name] = value

        # blindsMode cleanup from @readingsBlindMode
        if readings.get("blindsMode") == "off":
            for key in BLIND_MODE_READINGS:
                readings.pop(key, None)

        # If parsing produced a 'version' reading (StatusID 998, format 29),
        # it is more accurate than the frame[12] nibble fallback above.
        if "version" in readings:
            result.version = str(readings.pop("version"))

        result.readings = readings

        if "position" in readings:
            try:
                result.position = int(readings["position"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
        if "level" in readings:
            try:
                result.level = int(readings["level"])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
        if "moving" in readings:
            result.moving = str(readings["moving"])
        if "measured-temp" in readings:
            try:
                result.measured_temp = float(  # type: ignore[arg-type]
                    readings["measured-temp"]
                )
            except (TypeError, ValueError):
                pass
        if "desired-temp" in readings:
            try:
                result.desired_temp = float(  # type: ignore[arg-type]
                    readings["desired-temp"]
                )
            except (TypeError, ValueError):
                pass

        # Boost detection for 0xE1 Heizkörperantrieb (format 29).
        # Boost active:   frame[4] (subtype) == 0xF0 → desired-temp = 28°C
        # Boost duration: frame[12] & 0x3F minutes (upper 2 bits = rolling counter)
        #   0x09 (9) is the factory default — no boost ever set.
        #   After a boost the value stays at the set duration even after boost ends.
        # Confirmed by live frame captures: 4 min → 0x04, 30 min → 0x1E, 60 min → 0x3C.
        if fmt == "29":
            result.boost_active = frame[4] == 0xF0
            result.boost_duration_min = frame[12] & 0x3F
            # Mirror into readings so the normal HSA queue/optimistic-update
            # mechanism works identically for boost as for manualMode etc.
            result.readings["boostActive"] = "on" if result.boost_active else "off"
            result.readings["boostDuration"] = result.boost_duration_min

        return result

    @staticmethod
    def parse_sensor_event(data: bytes | bytearray | str) -> SensorEvent | None:
        """Parse sensor/button event message.

        From 30_DUOFERN.pm:
          #Wandtaster, Funksender UP, Handsender, Sensoren
        """
        frame = DuoFernDecoder._ensure_bytes(data)
        msg_id = frame[2:4].hex().upper()
        spec = SENSOR_MESSAGES.get(msg_id)
        if spec is None:
            return None

        device_code = DuoFernDecoder.extract_device_code(frame)
        chan_pos: int = spec["chan"]
        # FHEM: substr($msg, chan*2 + 2, 2)
        # The +2 (hex chars) = +1 byte offset. So byte position = chan + 1.
        byte_pos = chan_pos + 1
        chan_raw = frame[byte_pos] if byte_pos < FRAME_SIZE_BYTES else 0
        chan_hex = f"{chan_raw:02X}"

        # Devices 0x61, 0x70, 0x71 always use channel "01"
        if device_code.device_type in (0x61, 0x70, 0x71):
            chan_hex = "01"

        return SensorEvent(
            device_code=device_code.hex,
            channel=chan_hex,
            event_name=spec["name"],
            state=spec.get("state"),
            raw_msg_id=msg_id,
        )

    @staticmethod
    def parse_weather_data(data: bytes | bytearray | str) -> WeatherData:
        """Parse Umweltsensor weather data (0F..1322...).

        From 30_DUOFERN.pm: #Umweltsensor Wetter
        """
        frame = DuoFernDecoder._ensure_bytes(data)
        w = WeatherData()
        brightness_raw = (frame[4] << 8) | frame[5]
        brightness_exp = 1000 if (brightness_raw & 0x0400) else 1
        w.brightness = float((brightness_raw & 0x01FF) * brightness_exp)
        w.sun_direction = frame[7] * 1.5
        w.sun_height = float(frame[8] - 90)
        temp_raw = (frame[9] << 8) | frame[10]
        w.temperature = ((temp_raw & 0x7FFF) - 400) / 10.0
        w.is_raining = bool(temp_raw & 0x8000)
        wind_raw = (frame[11] << 8) | frame[12]
        w.wind = (wind_raw & 0x03FF) / 10.0
        return w

    @staticmethod
    def parse_battery_status(data: bytes | bytearray | str) -> dict[str, object]:
        """Parse battery status (0FFF1323...).

        From 30_DUOFERN.pm: #Sensoren Batterie
        """
        frame = DuoFernDecoder._ensure_bytes(data)
        level = frame[4]
        return {"batteryState": "low" if level <= 10 else "ok", "batteryPercent": level}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def frame_to_hex(frame: bytearray) -> str:
    return frame.hex().upper()


def hex_to_frame(hex_str: str) -> bytearray:
    return bytearray.fromhex(hex_str)


def validate_system_code(code: str) -> bool:
    """Validate system code: 6 hex chars starting with '6F'.

    From 10_DUOFERNSTICK.pm: dongle serial starts with "6F".
    """
    if len(code) != 6:
        return False
    try:
        bytes.fromhex(code)
    except ValueError:
        return False
    return code.upper().startswith("6F")


def validate_device_code(code: str) -> bool:
    if len(code) != 6:
        return False
    try:
        bytes.fromhex(code)
    except ValueError:
        return False
    return True
