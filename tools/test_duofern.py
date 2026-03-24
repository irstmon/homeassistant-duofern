#!/usr/bin/env python3
"""Standalone test script for DuoFern roller shutter control.

Tests the protocol and stick layer directly, without Home Assistant.
Run this on the Raspberry Pi where the DuoFern USB stick is connected.

Requirements:
    pip install pyserial pyserial-asyncio-fast

Usage:
    python3 test_duofern.py <command> [device_code] [position]

    If device_code is omitted, the command is sent to ALL paired devices.

Examples:
    python3 test_duofern.py 4053B8 up           # Open one shutter
    python3 test_duofern.py 4053B8 down          # Close one shutter
    python3 test_duofern.py 4053B8 stop          # Stop one shutter
    python3 test_duofern.py 4053B8 position 50   # Set one to 50%
    python3 test_duofern.py 4053B8 status        # Status of one device
    python3 test_duofern.py up                   # Open ALL shutters
    python3 test_duofern.py down                 # Close ALL shutters
    python3 test_duofern.py position 50          # Set ALL to 50%
    python3 test_duofern.py status               # Status of ALL devices
    python3 test_duofern.py statusall            # Broadcast status request

Device codes (from your FHEM config):
    406B0D  Rolladentuer        (Wohnzimmer)
    4090EA  Rolladenfenster     (Wohnzimmer)
    40B689  Rolladenfensterklein (Wohnzimmer Esstisch)
    4053B8  az_Rolladentuer     (Arbeitszimmer)
    4083D8  kz_Rolladenfenster  (Kinderzimmer)
    409C11  sz_Rolladenfenster  (Schlafzimmer)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# ---------------------------------------------------------------------------
# Direct module loading — bypasses __init__.py (which needs homeassistant)
# ---------------------------------------------------------------------------
import importlib.util
import types

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(SCRIPT_DIR)  # Go up from tools/ to repo root
_DUOFERN_PKG = os.path.join(_REPO_ROOT, "custom_components", "duofern")


def _load_module(name: str) -> types.ModuleType:
    """Load a duofern module directly by file path, bypassing __init__.py."""
    fqn = f"custom_components.duofern.{name}"
    spec = importlib.util.spec_from_file_location(
        fqn, os.path.join(_DUOFERN_PKG, f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[fqn] = mod
    spec.loader.exec_module(mod)
    return mod


# Create fake package hierarchy so relative imports inside the modules work
# (e.g. stick.py does "from .const import ..." which resolves to
#  "custom_components.duofern.const")
_pkg_cc = types.ModuleType("custom_components")
_pkg_cc.__path__ = [os.path.join(_REPO_ROOT, "custom_components")]
sys.modules["custom_components"] = _pkg_cc

_pkg_df = types.ModuleType("custom_components.duofern")
_pkg_df.__path__ = [_DUOFERN_PKG]
sys.modules["custom_components.duofern"] = _pkg_df

# Load in dependency order: const → protocol → stick
_const = _load_module("const")
_protocol = _load_module("protocol")
_stick = _load_module("stick")

# Pull symbols into local namespace (same names as before)
SERIAL_BAUDRATE = _const.SERIAL_BAUDRATE
CoverCommand = _protocol.CoverCommand
DuoFernDecoder = _protocol.DuoFernDecoder
DuoFernEncoder = _protocol.DuoFernEncoder
DuoFernId = _protocol.DuoFernId
frame_to_hex = _protocol.frame_to_hex
validate_device_code = _protocol.validate_device_code
validate_system_code = _protocol.validate_system_code
DuoFernStick = _stick.DuoFernStick

# ---------------------------------------------------------------------------
# Configuration — adjust these to match your setup
# ---------------------------------------------------------------------------
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_SYSTEM_CODE = "6F1A2B"

# All known paired devices (registered during init handshake)
PAIRED_DEVICES = [
    "406B0D",  # Rolladentuer (Wohnzimmer)
    "4090EA",  # Rolladenfenster (Wohnzimmer)
    "40B689",  # Rolladenfensterklein (Wohnzimmer Esstisch)
    "4053B8",  # az_Rolladentuer (Arbeitszimmer)
    "4083D8",  # kz_Rolladenfenster (Kinderzimmer)
    "409C11",  # sz_Rolladenfenster (Schlafzimmer)
]

# How long to wait for status responses after sending a command (seconds)
STATUS_WAIT_TIME = 10.0

# Filter: when set, on_message only shows status from this device
_filter_device: str | None = None

# Duplicate filter: tracks device codes already shown in this run
_seen_devices: set[str] = set()

COMMANDS = ["up", "down", "stop", "position", "status", "statusall"]


# ---------------------------------------------------------------------------
# Message handler: prints incoming messages
# ---------------------------------------------------------------------------
def on_message(frame: bytearray) -> None:
    """Handle incoming messages from the stick."""
    hex_str = frame_to_hex(frame)

    if DuoFernDecoder.is_status_response(frame):
        device_code = DuoFernDecoder.extract_device_code_from_status(frame)
        # Filter: skip if we only want a specific device
        if _filter_device and device_code.hex.upper() != _filter_device:
            return
        # Duplicate filter: skip if we already showed this device
        dev_key = device_code.hex.upper()
        if dev_key in _seen_devices:
            return
        _seen_devices.add(dev_key)
        status = DuoFernDecoder.parse_status(frame)
        print(f"\n{'=' * 60}")
        print(f"  STATUS from {device_code.hex} ({device_code.device_type_name})")
        ha_position = 100 - status.position  # HA: 0=closed, 100=open
        print(f"  Position:    {status.position}% (DuoFern: 0=open, 100=closed)")
        print(f"  Position:    {ha_position}% (HomeAssistant: 100=open, 0=closed)")
        print(f"  Moving:      {status.moving}")
        print(f"  Version:     {status.version}")
        print(
            f"  Automatics:  time={status.time_automatic}"
            f" sun={status.sun_automatic}"
            f" dawn={status.dawn_automatic}"
            f" dusk={status.dusk_automatic}"
        )
        print(f"  Manual mode: {status.manual_mode}")
        print(f"  Raw:         {hex_str}")
        print(f"{'=' * 60}")
    elif DuoFernDecoder.is_pair_response(frame):
        code = DuoFernDecoder.extract_device_code(frame)
        print(f"  PAIR response from {code.hex}")
    elif DuoFernDecoder.is_unpair_response(frame):
        code = DuoFernDecoder.extract_device_code(frame)
        print(f"  UNPAIR response from {code.hex}")
    else:
        print(f"  MSG: {hex_str}")


# ---------------------------------------------------------------------------
# Helper: send a command to one or all devices
# ---------------------------------------------------------------------------
async def send_to_targets(
    stick: DuoFernStick,
    args: argparse.Namespace,
    system_code: DuoFernId,
    targets: list[str],
) -> None:
    """Send the requested command to all target devices."""
    global _filter_device

    for device_hex in targets:
        device_code = DuoFernId.from_hex(device_hex)

        if args.command == "up":
            print(f">> Sending UP to {device_hex}...")
            frame = DuoFernEncoder.build_cover_command(
                CoverCommand.UP, device_code, system_code
            )
            await stick.send_command(frame)

        elif args.command == "down":
            print(f">> Sending DOWN to {device_hex}...")
            frame = DuoFernEncoder.build_cover_command(
                CoverCommand.DOWN, device_code, system_code
            )
            await stick.send_command(frame)

        elif args.command == "stop":
            print(f">> Sending STOP to {device_hex}...")
            frame = DuoFernEncoder.build_cover_command(
                CoverCommand.STOP, device_code, system_code
            )
            await stick.send_command(frame)

        elif args.command == "position":
            pos = args.position
            print(f">> Sending POSITION {pos}% to {device_hex}...")
            frame = DuoFernEncoder.build_cover_command(
                CoverCommand.POSITION,
                device_code,
                system_code,
                position=100 - pos,  # Convert: user says 0=closed, 100=open
            )
            await stick.send_command(frame)

        elif args.command == "status":
            if len(targets) == 1:
                _filter_device = device_hex.upper()
            else:
                _filter_device = None
            print(f">> Requesting status from {device_hex}...")
            frame = DuoFernEncoder.build_status_request(device_code, system_code)
            await stick.send_command(frame)

        # Small delay between commands when sending to multiple devices
        if len(targets) > 1:
            await asyncio.sleep(0.5)


# ---------------------------------------------------------------------------
# Main async logic
# ---------------------------------------------------------------------------
async def run(args: argparse.Namespace) -> None:
    """Connect to stick, send command, wait for response."""
    global _filter_device, _seen_devices
    _seen_devices = set()  # Reset for each run

    system_code = DuoFernId.from_hex(args.system_code)
    paired = [DuoFernId.from_hex(d) for d in PAIRED_DEVICES]

    # Determine target devices
    if args.device:
        targets = [args.device.upper()]
        # Make sure target device is in paired list
        if args.device.upper() not in [d.upper() for d in PAIRED_DEVICES]:
            print(f"WARNING: Device {args.device} is not in PAIRED_DEVICES list!")
            print(f"         The stick might not be able to reach it.")
            print(f"         Add it to PAIRED_DEVICES in this script.\n")
    else:
        targets = [d.upper() for d in PAIRED_DEVICES]

    # Header
    print(f"DuoFern Test Script")
    print(f"  Port:        {args.port}")
    print(f"  System code: {args.system_code}")
    if args.device:
        dc = DuoFernId.from_hex(args.device)
        print(f"  Device:      {args.device} ({dc.device_type_name})")
    else:
        print(f"  Devices:     ALL ({len(targets)} paired)")
    print(f"  Command:     {args.command}", end="")
    if args.command == "position":
        print(f" {args.position}%")
    else:
        print()
    print()

    # Create and connect stick
    print("Connecting to DuoFern stick...")
    stick = DuoFernStick(
        port=args.port,
        system_code=system_code,
        paired_devices=paired,
        message_callback=on_message,
    )

    try:
        await stick.connect()
        print("Connected and initialized!\n")
    except Exception as err:
        print(f"\nERROR: Failed to connect: {err}")
        print(f"\nTroubleshooting:")
        print(f"  - Is the USB stick plugged in?")
        print(f"  - Check: ls -la {args.port}")
        print(f"  - Check permissions: groups $(whoami)")
        print(f"  - Try: sudo chmod 666 {args.port}")
        sys.exit(1)

    try:
        if args.command == "statusall" or (
            args.command == "status" and not args.device
        ):
            # Broadcast: status without device or explicit statusall
            _filter_device = None
            print(f">> Broadcasting status request to all devices...")
            frame = DuoFernEncoder.build_status_request_broadcast()
            await stick.send_command(frame)
        else:
            await send_to_targets(stick, args, system_code, targets)

        print(f"\nCommand sent. Waiting {STATUS_WAIT_TIME}s for responses...\n")
        await asyncio.sleep(STATUS_WAIT_TIME)

    except Exception as err:
        print(f"\nERROR: {err}")
        import traceback

        traceback.print_exc()
    finally:
        print("\nDisconnecting...")
        await stick.disconnect()
        print("Done.")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
def main() -> None:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(
        description="DuoFern roller shutter test script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Device codes (from FHEM config):
  406B0D  Rolladentuer         (Wohnzimmer)
  4090EA  Rolladenfenster      (Wohnzimmer)
  40B689  Rolladenfensterklein (Wohnzimmer Esstisch)
  4053B8  az_Rolladentuer      (Arbeitszimmer)
  4083D8  kz_Rolladenfenster   (Kinderzimmer)
  409C11  sz_Rolladenfenster   (Schlafzimmer)

Examples:
  python3 test_duofern.py 4053B8 up           # Open one shutter
  python3 test_duofern.py 4053B8 status       # Status of one device
  python3 test_duofern.py up                  # Open ALL shutters
  python3 test_duofern.py status              # Status of ALL devices
  python3 test_duofern.py statusall           # Broadcast status request
  python3 test_duofern.py position 50         # Set ALL to 50%
  python3 test_duofern.py 4053B8 position 50  # Set one to 50%
        """,
    )

    # We accept: [device] command [position]
    # argparse can't do optional-positional-before-required easily,
    # so we parse the positional args manually.
    parser.add_argument(
        "args",
        nargs="+",
        help="[device_code] command [position]",
    )
    parser.add_argument(
        "--port",
        "-p",
        default=DEFAULT_SERIAL_PORT,
        help=f"Serial port (default: {DEFAULT_SERIAL_PORT})",
    )
    parser.add_argument(
        "--system-code",
        "-s",
        default=DEFAULT_SYSTEM_CODE,
        help=f"System code (default: {DEFAULT_SYSTEM_CODE})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    parsed = parser.parse_args()

    # --- Manual positional argument parsing ---
    positional = parsed.args
    device = None
    command = None
    position = 50

    if len(positional) == 1:
        # Just a command: "up", "status", "statusall"
        command = positional[0].lower()
    elif len(positional) == 2:
        # Either "device command" or "command position"
        if positional[0].lower() in COMMANDS:
            # "position 50" or "status -v" etc.
            command = positional[0].lower()
            try:
                position = int(positional[1])
            except ValueError:
                parser.error(f"Expected position number, got: {positional[1]}")
        else:
            # "4053B8 up"
            device = positional[0].upper()
            command = positional[1].lower()
    elif len(positional) == 3:
        # "device command position": "4053B8 position 50"
        device = positional[0].upper()
        command = positional[1].lower()
        try:
            position = int(positional[2])
        except ValueError:
            parser.error(f"Expected position number, got: {positional[2]}")
    else:
        parser.error("Too many arguments. Usage: [device_code] command [position]")

    if command not in COMMANDS:
        parser.error(f"Unknown command: {command}. Choose from: {', '.join(COMMANDS)}")

    # Validate device code if provided
    if device and not validate_device_code(device):
        parser.error(f"Invalid device code: {device} (need 6 hex chars)")

    # Build a namespace that run() expects
    args = argparse.Namespace(
        device=device,
        command=command,
        position=position,
        port=parsed.port,
        system_code=parsed.system_code.upper(),
        verbose=parsed.verbose,
    )

    if not validate_system_code(args.system_code):
        parser.error(
            f"Invalid system code: {args.system_code} (need 6 hex chars starting with 6F)"
        )

    if args.command == "position":
        if args.position < 0 or args.position > 100:
            parser.error(f"Position must be 0-100, got {args.position}")

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet down noisy loggers unless verbose
    if not args.verbose:
        logging.getLogger("custom_components.duofern.stick").setLevel(logging.WARNING)
        logging.getLogger("custom_components.duofern.protocol").setLevel(
            logging.WARNING
        )

    # Run
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
