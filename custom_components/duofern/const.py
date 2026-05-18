"""Constants for the DuoFern integration.

All protocol data tables are transcribed 1:1 from the FHEM Perl modules:
  10_DUOFERNSTICK.pm  — stick/IO layer
  30_DUOFERN.pm       — device layer (%devices, %sensorMsg, %statusGroups,
                        %statusIds, %statusMapping, %commands, %commandsStatus)
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Integration domain
# ---------------------------------------------------------------------------

DOMAIN: Final = "duofern"

# ---------------------------------------------------------------------------
# USB device identification (FTDI FT232R used by Rademacher)
# ---------------------------------------------------------------------------

USB_VID: Final = 0x0403  # Future Technology Devices International (FTDI)
USB_PID: Final = 0x6001  # FT232 Serial (UART) IC
USB_PRODUCT: Final = "DuoFern USB-Stick"
USB_MANUFACTURER: Final = "Rademacher"

# ---------------------------------------------------------------------------
# Serial communication
# ---------------------------------------------------------------------------

SERIAL_BAUDRATE: Final = 115200

# ---------------------------------------------------------------------------
# DuoFern protocol frame format
# ---------------------------------------------------------------------------

FRAME_SIZE_HEX: Final = 44  # 22 bytes = 44 hex characters
FRAME_SIZE_BYTES: Final = 22

# Dongle serial format: must start with "6F" + 4 hex digits
DONGLE_SERIAL_PREFIX: Final = "6F"

# ---------------------------------------------------------------------------
# Timing constants (seconds)
# ---------------------------------------------------------------------------

ACK_TIMEOUT: Final = 5.0
INIT_RETRY_COUNT: Final = 4
PAIR_TIMEOUT: Final = 60.0
REMOTE_PAIR_TIMEOUT: Final = 10.0  # seconds to wait for CC/AA/BB after remotePair
STATUS_TIMEOUT: Final = 30.0
STATUS_RETRY_COUNT: Final = 4  # retries after ACK 810003CC (from FHEM)
FLUSH_BUFFER_TIMEOUT: Final = 0.5

# ---------------------------------------------------------------------------
# Config flow keys
# ---------------------------------------------------------------------------

CONF_SERIAL_PORT: Final = "serial_port"
CONF_DEVICE_CODE: Final = "system_code"
CONF_PAIRED_DEVICES: Final = "paired_devices"
CONF_AUTO_DISCOVER: Final = "auto_discover"

# ---------------------------------------------------------------------------
# Device type registry
# Transcribed from 30_DUOFERN.pm: my %devices
# ---------------------------------------------------------------------------

DEVICE_TYPES: Final[dict[int, str]] = {
    0x40: "RolloTron Standard",
    0x41: "RolloTron Comfort Slave",
    0x42: "Rohrmotor-Aktor",
    0x43: "Universalaktor",
    0x46: "Steckdosenaktor",
    0x47: "Rohrmotor Steuerung",
    0x48: "Dimmaktor",
    0x49: "Rohrmotor",
    0x4A: "Dimmer (9476-1)",
    0x4B: "Connect-Aktor",
    0x4C: "Troll Basis",
    0x4E: "SX5",
    0x61: "RolloTron Comfort Master",
    0x62: "Super Fake Device",
    0x65: "Bewegungsmelder",
    0x69: "Umweltsensor",
    0x70: "Troll Comfort DuoFern",
    0x71: "Troll Comfort DuoFern (Lichtmodus)",
    0x73: "Raumthermostat",
    0x74: "Wandtaster 6fach 230V",
    0xA0: "Handsender (6 Gruppen-48 Geraete)",
    0xA1: "Handsender (1 Gruppe-48 Geraete)",
    0xA2: "Handsender (6 Gruppen-1 Geraet)",
    0xA3: "Handsender (1 Gruppe-1 Geraet)",
    0xA4: "Wandtaster",
    0xA5: "Sonnensensor",
    0xA7: "Funksender UP",
    0xA8: "HomeTimer",
    0xA9: "Sonnen-/Windsensor",
    0xAA: "Markisenwaechter",
    0xAB: "Rauchmelder",
    0xAC: "Fenster-Tuer-Kontakt",
    0xAD: "Wandtaster 6fach Bat",
    0xAF: "Sonnensensor",
    0xE0: "Handzentrale",
    0xE1: "Heizkoerperantrieb",
}

# ---------------------------------------------------------------------------
# Device class groupings — used to determine HA entity platform
# ---------------------------------------------------------------------------

# Roller shutters / covers
# Format "21": RolloTron family
COVER_DEVICE_TYPES_FORMAT21: Final[set[int]] = {
    0x40,  # RolloTron Standard
    0x41,  # RolloTron Comfort Slave
    0x61,  # RolloTron Comfort Master
}

# Format "23" / "23a": Rohrmotor / Troll / Connect-Aktor
COVER_DEVICE_TYPES_FORMAT23: Final[set[int]] = {
    0x42,  # Rohrmotor-Aktor
    0x47,  # Rohrmotor Steuerung       (format "23a")
    0x49,  # Rohrmotor
    0x4B,  # Connect-Aktor
    0x4C,  # Troll Basis
    0x70,  # Troll Comfort DuoFern
}

# Format "24a": SX5 garage door
COVER_DEVICE_TYPES_FORMAT24: Final[set[int]] = {
    0x4E,  # SX5
}

# Cover devices that can report obstacle/block via format-24 status frames
# Determined by hardware capability (obstacle detection feature in the motor)
OBSTACLE_COVER_TYPES: Final[set[int]] = {
    0x49,  # Rohrmotor — confirmed: sends format 24, FHEM shows obstacle+block readings
    0x4E,  # SX5 — confirmed: format 24a explicit in FHEM, obstacle+block+lightCurtain
    # 0x47 excluded: format 23a does NOT contain obstacle/block
    # 0x42, 0x4B, 0x4C, 0x70 excluded: unverified, no real frames available
}

# Devices that support blinds/slat mode (setsBlinds in FHEM dispatch for 42|4B|4C|70)
BLINDS_DEVICE_TYPES: Final[set[int]] = {
    0x42,  # Rohrmotor-Aktor
    0x4B,  # Connect-Aktor
    0x4C,  # Troll Basis
    0x70,  # Troll Comfort DuoFern
}

# All covers combined
COVER_DEVICE_TYPES: Final[set[int]] = (
    COVER_DEVICE_TYPES_FORMAT21
    | COVER_DEVICE_TYPES_FORMAT23
    | COVER_DEVICE_TYPES_FORMAT24
)

# All cover device types as a flat set — used in number.py and switch.py to
# filter which entities apply to cover devices. Defined here to avoid duplication.
ALL_COVER_TYPES: Final[frozenset[int]] = frozenset(COVER_DEVICE_TYPES)

# Cover types that have the Troll/Rohrmotor motor feature set: running time,
# wind/rain automatic, motor dead time, reversal, and motor-specific number/switch
# entities. Note: obstacle detection is a separate concern — see OBSTACLE_COVER_TYPES.
# Used in number.py and switch.py — defined here to avoid duplication.
TROLL_COVER_TYPES: Final[frozenset[int]] = frozenset(
    {
        0x42,  # Rohrmotor-Aktor
        0x47,  # Rohrmotor Steuerung
        0x49,  # Rohrmotor
        0x4B,  # Connect-Aktor
        0x4C,  # Troll Basis
        0x70,  # Troll Comfort DuoFern
    }
)

# Dimmers / lights (level 0-100, on/off) — Format "25" / "2B"
LIGHT_DEVICE_TYPES: Final[set[int]] = {
    0x48,  # Dimmaktor
    0x4A,  # Dimmer (9476-1)
}

# Switch actors (on/off) — Format "22"
SWITCH_DEVICE_TYPES: Final[set[int]] = {
    0x43,  # Universalaktor            (has channels 01, 02)
    0x46,  # Steckdosenaktor
    0x71,  # Troll Comfort DuoFern (Lichtmodus)
}

# Thermostats / climate devices
# Format "27": Raumthermostat  |  Format "29": Heizkoerperantrieb
CLIMATE_DEVICE_TYPES: Final[set[int]] = {
    0x73,  # Raumthermostat
    0xE1,  # Heizkoerperantrieb
}

# Binary sensors (motion, smoke, door/window contact)
BINARY_SENSOR_DEVICE_TYPES: Final[set[int]] = {
    0x65,  # Motion detector
    0xAB,  # Smoke detector
    0xAC,  # Window/door contact sensor
}

# Weather / environment sensors that send full weather data frames (0F..1322).
# Only 0x69 (Umweltsensor / weather station) actually transmits these frames.
# All 5 sensor entities (brightness, temperature, wind, sunDirection, sunHeight)
# are created exclusively for this type.
SENSOR_DEVICE_TYPES: Final[set[int]] = {
    0x69,  # Umweltsensor (weather station) — sends full weather data frames
}

# Dedicated external environmental sensor devices (A5/AF/A9/AA).
# These send sun/wind events and are registered as standalone HA devices.
# IMPORTANT: These devices do NOT send weather data frames (0F..1322) — they
# only send sensorMsg events (startSun/endSun/startWind/endWind). Creating
# numeric sensor entities (brightness, temperature, wind, sunDirection,
# sunHeight) for these types would result in permanently unavailable entities
# because reading_key never appears in status.readings. Only 0x69 gets those.
# (See Bug 6 from the 2026-03-12 review: previously these were incorrectly
# included in SENSOR_DEVICE_TYPES, causing 5 phantom entities per device.)
# Note: 0x61 RolloTron Comfort Master also sends sun events but is already
# registered as a Cover — it gets an additional binary_sensor entity instead.
# From 30_DUOFERN.pm: none of these have get/set commands.
ENVIRONMENTAL_SENSOR_DEVICE_TYPES: Final[set[int]] = {
    0xA5,  # Sonnensensor
    0xAF,  # Sonnensensor (alternate model)
    0xA9,  # Sonnen-/Windsensor
    0xAA,  # Markisenwaechter (wind guard for awnings)
}

# Devices that send startSun/endSun events (sensorMsg 0708/070A)
SUN_SENSOR_DEVICE_TYPES: Final[set[int]] = {
    0x61,  # RolloTron Comfort Master (built-in brightness sensor)
    0xA5,  # Sonnensensor
    0xAF,  # Sonnensensor (alternate model)
    0xA9,  # Sonnen-/Windsensor
}

# Devices that send startWind/endWind events (sensorMsg 070D/070E)
WIND_SENSOR_DEVICE_TYPES: Final[set[int]] = {
    0xA9,  # Sonnen-/Windsensor
    0xAA,  # Markisenwaechter
}

# Remote controls / wall buttons / timers — fire HA events, no persistent state.
# These devices only send events (button presses, timer triggers) and never
# respond to commands. They get EventEntity + device triggers but NO actor buttons.
# 0xA8 HomeTimer and 0xE0 Handzentrale are included here because they fire
# duofern_event on the HA event bus just like all other remotes.
REMOTE_DEVICE_TYPES: Final[set[int]] = {
    0xA0,  # Handsender (6 groups, 48 devices)
    0xA1,  # Handsender (1 group, 48 devices)
    0xA2,  # Handsender (6 groups, 1 device)
    0xA3,  # Handsender (1 group, 1 device)
    0xA4,  # Wandtaster (wall button)
    0xA7,  # Funksender UP (wireless transmitter)
    0xA8,  # HomeTimer — fires events, listed in README as duofern_event source
    0x74,  # Wandtaster 6fach 230V (has channel 01)
    0xAD,  # Wandtaster 6fach Bat (battery-powered wall button)
    0xE0,  # Handzentrale — fires events, listed in README as duofern_event source
}

# ---------------------------------------------------------------------------
# Devices that expose multiple channels
# Transcribed from 30_DUOFERN.pm: %devices -> "chans" key
# Main device = 6-digit code (parent); channels = 8-digit codes (children)
# ---------------------------------------------------------------------------

DEVICE_CHANNELS: Final[dict[int, list[str]]] = {
    0x43: ["01", "02"],  # Universalaktor:   channel 01 and 02
    0x65: ["01"],  # Motion detector:  channel 01
    # 0x69 Umweltsensor has two sub-channels:
    #   "00" = weather station channel (getWeather / getTime / config buttons)
    #   "01" = actor channel (automation/heating outputs)
    # Both must be registered so that the correct entities are created for each.
    0x69: ["00", "01"],  # Umweltsensor: channel 00 (weather station) + 01 (actor)
    0x74: ["01"],  # Wandtaster 6fach: channel 01
}

# ---------------------------------------------------------------------------
# Status format override per device type
# Transcribed from 30_DUOFERN.pm: %devices -> "format" key
# If not listed here, the format comes from byte 3 of the status message.
# ---------------------------------------------------------------------------

DEVICE_STATUS_FORMAT_OVERRIDE: Final[dict[int, str]] = {
    0x47: "23a",  # Rohrmotor Steuerung
    0x69: "23a",  # Umweltsensor
    0x4E: "24a",  # SX5
}

# ---------------------------------------------------------------------------
# Status format -> list of statusId numbers to parse
# Transcribed from 30_DUOFERN.pm: my %statusGroups
# ---------------------------------------------------------------------------

STATUS_GROUPS: Final[dict[str, list[int]]] = {
    "21": [100, 101, 102, 104, 105, 106, 111, 112, 113, 114, 50],
    "22": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "23": [
        102,
        107,
        109,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        123,
        124,
        125,
        126,
        127,
        128,
        129,
        130,
        131,
        132,
        133,
        134,
        135,
        136,
        140,
        141,
        50,
    ],
    "23a": [
        102,
        107,
        109,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        123,
        124,
        125,
        126,
        127,
        133,
        140,
        141,
        50,
    ],
    "24": [
        102,
        107,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        123,
        124,
        125,
        126,
        127,
        140,
        141,
        400,
        402,
        50,
    ],
    "24a": [
        102,
        107,
        115,
        123,
        124,
        400,
        402,
        404,
        405,
        406,
        407,
        408,
        409,
        410,
        411,
        50,
    ],
    "25": [300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313],
    "26": [],
    "27": [160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171],
    "29": [180, 181, 182, 183, 184, 185, 186, 187, 188, 998],
    "2B": [300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313],
}

# ---------------------------------------------------------------------------
# Value scaling / mapping table
# Transcribed from 30_DUOFERN.pm: my %statusMapping
#
# List entries:
#   "onOff" / "upDown" / "moving" / "motor" / "closeT" / "openS"
#       -> list of strings; raw value is used as index
#   "scale10" / "scaleF1"-"scaleF4"
#       -> [factor, offset]: value = (raw - offset) / factor
#   "hex"
#       -> rendered as "X.Y" nibble string
# ---------------------------------------------------------------------------

STATUS_MAPPING: Final[dict[str, list]] = {
    "onOff": ["off", "on"],
    "upDown": ["up", "down"],
    "moving": ["stop", "stop"],
    "motor": ["off", "short(160ms)", "long(480ms)", "individual"],
    "closeT": ["off", "30", "60", "90", "120", "150", "180", "210", "240"],
    "openS": ["error", "11", "15", "19"],
    "scale10": [10, 0],  # factor=10, offset=0
    "scaleF1": [2, 80],  # factor=2,  offset=80  -> temp °C (raw/2 - 40)
    "scaleF2": [10, 400],  # factor=10, offset=400 -> temp °C (raw/10 - 40)
    "scaleF3": [2, -8],  # factor=2,  offset=-8
    "scaleF4": [100, 0],  # factor=100,offset=0
    "hex": [1, 0],  # displayed as hex nibbles "X.Y"
}

# ---------------------------------------------------------------------------
# Status field definitions
# Transcribed from 30_DUOFERN.pm: my %statusIds
#
# Each entry: {
#   "name":   reading name (str),
#   "map":    key into STATUS_MAPPING (optional),
#   "invert": invert = invert_value - raw (optional),
#   "chan": {
#     "01": {"position": N, "from": F, "to": T},
#     "02": {...},
#   }
# }
#
# "position" N -> read the 16-bit word at frame byte (3 + N).
# Bits F..T (inclusive) are extracted from that word.
# ---------------------------------------------------------------------------

STATUS_IDS: Final[dict[int, dict]] = {
    # --- Format 22: Universalaktor / Steckdosenaktor (2-channel) ---
    1: {
        "name": "level",
        "chan": {
            "01": {"position": 7, "from": 0, "to": 6},
            "02": {"position": 6, "from": 0, "to": 6},
        },
    },
    2: {
        "name": "timeAutomatic",
        "map": "onOff",
        "chan": {
            "01": {"position": 3, "from": 0, "to": 0},
            "02": {"position": 2, "from": 0, "to": 0},
        },
    },
    3: {
        "name": "duskAutomatic",
        "map": "onOff",
        "chan": {
            "01": {"position": 3, "from": 1, "to": 1},
            "02": {"position": 2, "from": 1, "to": 1},
        },
    },
    4: {
        "name": "dawnAutomatic",
        "map": "onOff",
        "chan": {
            "01": {"position": 3, "from": 6, "to": 6},
            "02": {"position": 2, "from": 6, "to": 6},
        },
    },
    5: {
        "name": "sunAutomatic",
        "map": "onOff",
        "chan": {
            "01": {"position": 3, "from": 2, "to": 2},
            "02": {"position": 2, "from": 2, "to": 2},
        },
    },
    6: {
        "name": "manualMode",
        "map": "onOff",
        "chan": {
            "01": {"position": 3, "from": 5, "to": 5},
            "02": {"position": 2, "from": 5, "to": 5},
        },
    },
    7: {
        "name": "modeChange",
        "map": "onOff",
        "chan": {
            "01": {"position": 7, "from": 7, "to": 7},
            "02": {"position": 6, "from": 7, "to": 7},
        },
    },
    8: {
        "name": "sunMode",
        "map": "onOff",
        "chan": {
            "01": {"position": 3, "from": 4, "to": 4},
            "02": {"position": 2, "from": 4, "to": 4},
        },
    },
    9: {
        "name": "stairwellFunction",
        "map": "onOff",
        "chan": {
            "01": {"position": 4, "from": 7, "to": 7},
            "02": {"position": 0, "from": 7, "to": 7},
        },
    },
    10: {
        "name": "stairwellTime",
        "map": "scale10",
        "chan": {
            "01": {"position": 5, "from": 0, "to": 14},
            "02": {"position": 1, "from": 0, "to": 14},
        },
    },
    # --- Shared: moving indicator ---
    50: {
        "name": "moving",
        "map": "moving",
        "chan": {
            "01": {"position": 0, "from": 0, "to": 0},
            "02": {"position": 0, "from": 0, "to": 0},
        },
    },
    # --- Format 21: RolloTron Standard / Comfort ---
    100: {
        "name": "sunAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 2, "to": 2}},
    },
    101: {
        "name": "timeAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 0, "to": 0}},
    },
    102: {"name": "position", "chan": {"01": {"position": 7, "from": 0, "to": 6}}},
    104: {
        "name": "duskAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 3, "to": 3}},
    },
    105: {
        "name": "dawnAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 1, "from": 3, "to": 3}},
    },
    106: {
        "name": "manualMode",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 7, "to": 7}},
    },
    107: {
        "name": "manualMode",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 5, "to": 5}},
    },
    109: {"name": "runningTime", "chan": {"01": {"position": 6, "from": 0, "to": 7}}},
    111: {
        "name": "sunPosition",
        "invert": 100,
        "chan": {"01": {"position": 6, "from": 0, "to": 6}},
    },
    112: {
        "name": "ventilatingPosition",
        "invert": 100,
        "chan": {"01": {"position": 2, "from": 0, "to": 6}},
    },
    113: {
        "name": "ventilatingMode",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 7, "to": 7}},
    },
    114: {
        "name": "sunMode",
        "map": "onOff",
        "chan": {"01": {"position": 6, "from": 7, "to": 7}},
    },
    # --- Format 23 / 23a: Rohrmotor / Troll ---
    115: {
        "name": "timeAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 0, "to": 0}},
    },
    116: {
        "name": "sunAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 2, "to": 2}},
    },
    117: {
        "name": "dawnAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 1, "to": 1}},
    },
    118: {
        "name": "duskAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 1, "to": 1}},
    },
    119: {
        "name": "rainAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 7, "to": 7}},
    },
    120: {
        "name": "windAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 6, "to": 6}},
    },
    121: {
        "name": "sunPosition",
        "invert": 100,
        "chan": {"01": {"position": 5, "from": 0, "to": 6}},
    },
    122: {
        "name": "sunMode",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 4, "to": 4}},
    },
    123: {
        "name": "ventilatingPosition",
        "invert": 100,
        "chan": {"01": {"position": 4, "from": 0, "to": 6}},
    },
    124: {
        "name": "ventilatingMode",
        "map": "onOff",
        "chan": {"01": {"position": 4, "from": 7, "to": 7}},
    },
    125: {
        "name": "reversal",
        "map": "onOff",
        "chan": {"01": {"position": 7, "from": 7, "to": 7}},
    },
    126: {
        "name": "rainDirection",
        "map": "upDown",
        "chan": {"01": {"position": 2, "from": 3, "to": 3}},
    },
    127: {
        "name": "windDirection",
        "map": "upDown",
        "chan": {"01": {"position": 2, "from": 2, "to": 2}},
    },
    128: {"name": "slatRunTime", "chan": {"01": {"position": 0, "from": 0, "to": 5}}},
    129: {
        "name": "tiltAfterMoveLevel",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 6, "to": 6}},
    },
    130: {
        "name": "tiltInVentPos",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 7, "to": 7}},
    },
    131: {
        "name": "defaultSlatPos",
        "chan": {"01": {"position": 1, "from": 0, "to": 6}},
    },
    132: {
        "name": "tiltAfterStopDown",
        "map": "onOff",
        "chan": {"01": {"position": 1, "from": 7, "to": 7}},
    },
    133: {
        "name": "motorDeadTime",
        "map": "motor",
        "chan": {"01": {"position": 2, "from": 4, "to": 5}},
    },
    134: {
        "name": "tiltInSunPos",
        "map": "onOff",
        "chan": {"01": {"position": 5, "from": 7, "to": 7}},
    },
    135: {"name": "slatPosition", "chan": {"01": {"position": 9, "from": 0, "to": 6}}},
    136: {
        "name": "blindsMode",
        "map": "onOff",
        "chan": {"01": {"position": 9, "from": 7, "to": 7}},
    },
    140: {
        "name": "windMode",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 3, "to": 3}},
    },
    141: {
        "name": "rainMode",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 0, "to": 0}},
    },
    # --- Format 27: Raumthermostat ---
    160: {
        "name": "temperatureThreshold1",
        "map": "scaleF1",
        "chan": {"01": {"position": 4, "from": 0, "to": 7}},
    },
    161: {
        "name": "temperatureThreshold2",
        "map": "scaleF1",
        "chan": {"01": {"position": 5, "from": 0, "to": 7}},
    },
    162: {
        "name": "temperatureThreshold3",
        "map": "scaleF1",
        "chan": {"01": {"position": 6, "from": 0, "to": 7}},
    },
    163: {
        "name": "temperatureThreshold4",
        "map": "scaleF1",
        "chan": {"01": {"position": 7, "from": 0, "to": 7}},
    },
    164: {
        "name": "desired-temp",
        "map": "scaleF1",
        "chan": {"01": {"position": 9, "from": 0, "to": 7}},
    },
    165: {
        "name": "measured-temp",
        "map": "scaleF2",
        "chan": {"01": {"position": 1, "from": 0, "to": 10}},
    },
    166: {
        "name": "output",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 3, "to": 3}},
    },
    167: {
        "name": "manualOverride",
        "map": "onOff",
        "chan": {"01": {"position": 0, "from": 4, "to": 4}},
    },
    168: {"name": "actTempLimit", "chan": {"01": {"position": 0, "from": 5, "to": 6}}},
    169: {
        "name": "timeAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 3, "to": 3}},
    },
    170: {
        "name": "manualMode",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 4, "to": 4}},
    },
    171: {
        "name": "measured-temp2",
        "map": "scaleF2",
        "chan": {"01": {"position": 3, "from": 0, "to": 10}},
    },
    # --- Format 29: Heizkoerperantrieb (HSA) ---
    180: {
        "name": "desired-temp",
        "map": "scaleF3",
        "chan": {"01": {"position": 0, "from": 0, "to": 5}},
    },
    181: {
        "name": "measured-temp",
        "map": "scaleF4",
        "chan": {"01": {"position": 2, "from": 0, "to": 15}},
    },
    182: {
        "name": "manualMode",
        "map": "onOff",
        "chan": {"01": {"position": 4, "from": 0, "to": 0}},
    },
    183: {
        "name": "timeAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 4, "from": 1, "to": 1}},
    },
    184: {
        "name": "sendingInterval",
        "chan": {"01": {"position": 4, "from": 6, "to": 11}},
    },
    185: {
        "name": "batteryPercent",
        "chan": {"01": {"position": 7, "from": 0, "to": 6}},
    },
    186: {"name": "valvePosition", "chan": {"01": {"position": 6, "from": 0, "to": 6}}},
    187: {"name": "forceResponse", "chan": {"01": {"position": 8, "from": 7, "to": 7}}},
    # windowContact echo — device mirrors the last windowContact value sent via
    # duoSetHSA back in every status frame. Verified 2026-03-10 via USB log +
    # RTL-SDR: byte[8] bit5=0 → off, bit5=1 → on. Device updates immediately
    # after CC ACK (no delay). pos=4 → _read_word reads byte[7..8]; bit 5 of
    # that word sits in byte[8] bit 5 (lower byte of the 16-bit word).
    188: {
        "name": "windowContact",
        "map": "onOff",
        "chan": {"01": {"position": 4, "from": 5, "to": 5}},
    },
    # --- Format 25 / 2B: Dimmaktor ---
    300: {"name": "level", "chan": {"01": {"position": 7, "from": 0, "to": 6}}},
    301: {
        "name": "manualMode",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 5, "to": 5}},
    },
    302: {
        "name": "timeAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 0, "to": 0}},
    },
    303: {
        "name": "duskAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 1, "to": 1}},
    },
    304: {
        "name": "sunAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 2, "to": 2}},
    },
    305: {
        "name": "sunMode",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 4, "to": 4}},
    },
    306: {
        "name": "dawnAutomatic",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 6, "to": 6}},
    },
    307: {"name": "runningTime", "chan": {"01": {"position": 5, "from": 0, "to": 7}}},
    308: {
        "name": "intermediateValue",
        "chan": {"01": {"position": 6, "from": 0, "to": 6}},
    },
    309: {
        "name": "intermediateMode",
        "map": "onOff",
        "chan": {"01": {"position": 6, "from": 7, "to": 7}},
    },
    310: {
        "name": "modeChange",
        "map": "onOff",
        "chan": {"01": {"position": 7, "from": 7, "to": 7}},
    },
    311: {
        "name": "stairwellFunction",
        "map": "onOff",
        "chan": {"01": {"position": 1, "from": 7, "to": 7}},
    },
    312: {
        "name": "stairwellTime",
        "map": "scale10",
        "chan": {"01": {"position": 2, "from": 0, "to": 14}},
    },
    313: {
        "name": "saveIntermediateOnStop",
        "map": "onOff",
        "chan": {"01": {"position": 3, "from": 7, "to": 7}},
    },
    # --- Format 24 / 24a: SX5 garage door ---
    400: {"name": "obstacle", "chan": {"01": {"position": 2, "from": 4, "to": 4}}},
    401: {
        "name": "obstacleDetection",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 5, "to": 5}},
    },
    402: {"name": "block", "chan": {"01": {"position": 2, "from": 6, "to": 6}}},
    403: {
        "name": "blockDetection",
        "map": "onOff",
        "chan": {"01": {"position": 2, "from": 7, "to": 7}},
    },
    404: {"name": "lightCurtain", "chan": {"01": {"position": 0, "from": 7, "to": 7}}},
    405: {
        "name": "automaticClosing",
        "map": "closeT",
        "chan": {"01": {"position": 1, "from": 0, "to": 3}},
    },
    406: {
        "name": "openSpeed",
        "map": "openS",
        "chan": {"01": {"position": 1, "from": 4, "to": 6}},
    },
    407: {
        "name": "2000cycleAlarm",
        "map": "onOff",
        "chan": {"01": {"position": 1, "from": 7, "to": 7}},
    },
    408: {
        "name": "wicketDoor",
        "map": "onOff",
        "chan": {"01": {"position": 5, "from": 7, "to": 7}},
    },
    409: {
        "name": "backJump",
        "map": "onOff",
        "chan": {"01": {"position": 9, "from": 0, "to": 0}},
    },
    410: {
        "name": "10minuteAlarm",
        "map": "onOff",
        "chan": {"01": {"position": 9, "from": 1, "to": 1}},
    },
    411: {
        "name": "light",
        "map": "onOff",
        "chan": {"01": {"position": 9, "from": 2, "to": 2}},
    },
    # --- Version fields (all formats) ---
    998: {
        "name": "version",
        "map": "hex",
        "chan": {"01": {"position": 9, "from": 0, "to": 6}},
    },
    999: {
        "name": "version",
        "map": "hex",
        "chan": {
            "01": {"position": 8, "from": 0, "to": 7},
            "02": {"position": 8, "from": 0, "to": 7},
        },
    },
}

# ---------------------------------------------------------------------------
# Sensor / button event messages
# Transcribed from 30_DUOFERN.pm: my %sensorMsg
#
# Key: 4-hex-char message ID (frame bytes 2+3 as uppercase hex)
# Value: {
#   "name":  event name,
#   "chan":  channel byte-position in frame (5 or 6),
#   "state": optional state string,
# }
# chan=6 -> button/remote;  chan=5 -> sensor (may be bitmask)
# ---------------------------------------------------------------------------

SENSOR_MESSAGES: Final[dict[str, dict]] = {
    # Button / remote events
    "0701": {"name": "up", "chan": 6, "state": "Btn01"},
    "0702": {"name": "stop", "chan": 6, "state": "Btn02"},
    "0703": {"name": "down", "chan": 6, "state": "Btn03"},
    "0718": {"name": "stepUp", "chan": 6, "state": "Btn18"},
    "0719": {"name": "stepDown", "chan": 6, "state": "Btn19"},
    "071A": {"name": "pressed", "chan": 6, "state": "Btn1A"},
    # Environmental / weather sensor events
    "0713": {"name": "dawn", "chan": 5, "state": "dawn"},
    "0709": {"name": "dusk", "chan": 5, "state": "dusk"},
    "0708": {"name": "startSun", "chan": 5, "state": "on"},
    "070A": {"name": "endSun", "chan": 5, "state": "off"},
    "070D": {"name": "startWind", "chan": 5, "state": "on"},
    "070E": {"name": "endWind", "chan": 5, "state": "off"},
    "0711": {"name": "startRain", "chan": 5, "state": "on"},
    "0712": {"name": "endRain", "chan": 5, "state": "off"},
    "071C": {"name": "startTemp", "chan": 5, "state": "on"},
    "071D": {"name": "endTemp", "chan": 5, "state": "off"},
    "071E": {"name": "startSmoke", "chan": 5, "state": "on"},
    "071F": {"name": "endSmoke", "chan": 5, "state": "off"},
    "0720": {"name": "startMotion", "chan": 5, "state": "on"},
    "0721": {"name": "endMotion", "chan": 5, "state": "off"},
    "0723": {"name": "opened", "chan": 5, "state": "opened"},
    "0724": {"name": "closed", "chan": 5, "state": "closed"},
    "0725": {"name": "startVibration", "chan": 5},
    "0726": {"name": "endVibration", "chan": 5},
    # Switch actor events
    "0E01": {"name": "off", "chan": 6, "state": "Btn01"},
    "0E02": {"name": "off", "chan": 6, "state": "Btn02"},
    "0E03": {"name": "on", "chan": 6, "state": "Btn03"},
}

# ---------------------------------------------------------------------------
# Status request type codes
# Transcribed from 30_DUOFERN.pm: my %commandsStatus
# ---------------------------------------------------------------------------

COMMAND_STATUS_TYPES: Final[dict[str, str]] = {
    "getStatus": "0F",
    "getWeather": "13",
    "getTime": "10",
}

# ---------------------------------------------------------------------------
# Blind-mode-only readings
# Deleted when blindsMode == "off"
# Transcribed from 30_DUOFERN.pm: my @readingsBlindMode
# ---------------------------------------------------------------------------

BLIND_MODE_READINGS: Final[list[str]] = [
    "tiltInSunPos",
    "tiltInVentPos",
    "tiltAfterMoveLevel",
    "tiltAfterStopDown",
    "defaultSlatPos",
    "slatRunTime",
    "slatPosition",
]

# ---------------------------------------------------------------------------
# HSA (Heizkoerperantrieb) command field definitions
# Transcribed from 30_DUOFERN.pm: my %commandsHSA
# ---------------------------------------------------------------------------

COMMANDS_HSA: Final[dict[str, dict]] = {
    "manualMode": {"bitFrom": 8, "changeFlag": 10},
    "timeAutomatic": {"bitFrom": 9, "changeFlag": 11},
    "sendingInterval": {"bitFrom": 0, "changeFlag": 7, "min": 0, "max": 60, "step": 1},
    "desired-temp": {"bitFrom": 17, "changeFlag": 23, "min": 4, "max": 28, "step": 0.5},
    "windowContact": {"bitFrom": 12, "changeFlag": 13},
}

# ---------------------------------------------------------------------------
# Default status format (fallback)
# ---------------------------------------------------------------------------

STATUS_FORMAT_DEFAULT: Final = "21"
