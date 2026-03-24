#!/usr/bin/env python3
"""Standalone pairing script for DuoFern devices.

Allows pairing and unpairing DuoFern devices (RolloTron, Gurtwickler, etc.)
with the DuoFern USB stick — without FHEM or Home Assistant.

Requirements:
    pip install pyserial pyserial-asyncio-fast

Usage:
    python3 pair_duofern.py pair              # Start pairing mode (60s window)
    python3 pair_duofern.py unpair            # Start unpairing mode (60s window)
    python3 pair_duofern.py list              # List all paired devices with status

Examples:
    python3 pair_duofern.py pair -v
    python3 pair_duofern.py pair --timeout 120
    python3 pair_duofern.py unpair -v
    python3 pair_duofern.py list -v

Pairing a new device:
    1. Run:  python3 pair_duofern.py pair
    2. Press the programming button on the new device (LED blinks)
    3. Wait for the device code to appear
    4. Add the code to your HA integration:
       Settings → Devices & Services → DuoFern → Configure

Device codes (currently paired):
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

# Pull symbols into local namespace
DuoFernDecoder = _protocol.DuoFernDecoder
DuoFernEncoder = _protocol.DuoFernEncoder
DuoFernId = _protocol.DuoFernId
frame_to_hex = _protocol.frame_to_hex
validate_system_code = _protocol.validate_system_code
DuoFernStick = _stick.DuoFernStick

# ---------------------------------------------------------------------------
# Configuration — adjust these to match your setup
# ---------------------------------------------------------------------------
DEFAULT_SERIAL_PORT = "/dev/ttyUSB0"
DEFAULT_SYSTEM_CODE = "6F1A2B"
DEFAULT_TIMEOUT = 60

# All known paired devices (needed for init handshake)
PAIRED_DEVICES = [
    "406B0D",  # Rolladentuer (Wohnzimmer)
    "4090EA",  # Rolladenfenster (Wohnzimmer)
    "40B689",  # Rolladenfensterklein (Wohnzimmer Esstisch)
    "4053B8",  # az_Rolladentuer (Arbeitszimmer)
    "4083D8",  # kz_Rolladenfenster (Kinderzimmer)
    "409C11",  # sz_Rolladenfenster (Schlafzimmer)
]

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pair command
# ---------------------------------------------------------------------------
async def run_pair(args: argparse.Namespace) -> None:
    """Run the pairing workflow."""
    system_code = DuoFernId.from_hex(args.system_code)
    paired = [DuoFernId.from_hex(d) for d in PAIRED_DEVICES]

    # Event signalled when a pair response arrives
    pair_event = asyncio.Event()
    paired_code: list[DuoFernId] = []

    def on_message(frame: bytearray) -> None:
        hex_str = frame_to_hex(frame)
        if DuoFernDecoder.is_pair_response(frame):
            code = DuoFernDecoder.extract_device_code(frame)
            paired_code.append(code)
            pair_event.set()
            print(f"\n{'=' * 60}")
            print(f"  PAIRED: {code.hex} ({code.device_type_name})")
            print(f"  Raw:    {hex_str}")
            print(f"{'=' * 60}")
        elif DuoFernDecoder.is_status_response(frame):
            # Ignore status responses during pairing
            pass
        else:
            _LOGGER.debug("MSG: %s", hex_str)

    # Connect to stick
    print(f"DuoFern Pairing Tool")
    print(f"  Port:        {args.port}")
    print(f"  System code: {args.system_code}")
    print(f"  Timeout:     {args.timeout}s")
    print()

    print("Connecting to DuoFern stick...")
    stick = DuoFernStick(
        port=args.port,
        system_code=system_code,
        paired_devices=paired,
        message_callback=on_message,
    )

    try:
        await stick.connect()
        print("Connected!\n")
    except Exception as err:
        print(f"\nERROR: Failed to connect: {err}")
        sys.exit(1)

    try:
        # Send start pair command
        frame = DuoFernEncoder.build_start_pair()
        await stick.send_command(frame)
        print(f"Pairing mode ACTIVE for {args.timeout} seconds.")
        print(f"Press the programming button on your new device now...")
        print()

        # Wait with countdown
        timeout = args.timeout
        interval = 10
        elapsed = 0

        while elapsed < timeout:
            wait_time = min(interval, timeout - elapsed)
            try:
                await asyncio.wait_for(pair_event.wait(), timeout=wait_time)
                # Device responded!
                break
            except asyncio.TimeoutError:
                elapsed += wait_time
                remaining = timeout - elapsed
                if remaining > 0:
                    print(f"  Waiting... {remaining}s remaining")

        if paired_code:
            code = paired_code[0]
            print(f"\nDevice successfully paired!")
            print(f"  Code: {code.hex}")
            print(f"  Type: {code.device_type_name}")
            print()
            print(f"Next steps:")
            print(f"  1. Add this code to your HA integration:")
            print(f"     Settings -> Devices & Services -> DuoFern -> Configure")
            print(f'     Add "{code.hex}" to the device codes list')
            print(
                f"  2. Also add it to PAIRED_DEVICES in this script and test_duofern.py"
            )
        else:
            print(f"\nNo device responded within {timeout} seconds.")
            print(f"  - Make sure the device is in pairing mode")
            print(f"  - Press and hold the programming button until the LED blinks")
            print(f"  - Try again with a longer timeout: --timeout 120")

        # Send stop pair
        frame = DuoFernEncoder.build_stop_pair()
        await stick.send_command(frame)
        _LOGGER.debug("Stop pair sent")

        # Brief wait for any final messages
        await asyncio.sleep(2)

    except Exception as err:
        print(f"\nERROR: {err}")
        import traceback

        traceback.print_exc()
    finally:
        print("\nDisconnecting...")
        await stick.disconnect()
        print("Done.")


# ---------------------------------------------------------------------------
# Unpair command
# ---------------------------------------------------------------------------
async def run_unpair(args: argparse.Namespace) -> None:
    """Run the unpairing workflow."""
    system_code = DuoFernId.from_hex(args.system_code)
    paired = [DuoFernId.from_hex(d) for d in PAIRED_DEVICES]

    unpair_event = asyncio.Event()
    unpaired_code: list[DuoFernId] = []

    def on_message(frame: bytearray) -> None:
        hex_str = frame_to_hex(frame)
        if DuoFernDecoder.is_unpair_response(frame):
            code = DuoFernDecoder.extract_device_code(frame)
            unpaired_code.append(code)
            unpair_event.set()
            print(f"\n{'=' * 60}")
            print(f"  UNPAIRED: {code.hex} ({code.device_type_name})")
            print(f"  Raw:      {hex_str}")
            print(f"{'=' * 60}")
        elif DuoFernDecoder.is_status_response(frame):
            pass
        else:
            _LOGGER.debug("MSG: %s", hex_str)

    print(f"DuoFern Unpairing Tool")
    print(f"  Port:        {args.port}")
    print(f"  System code: {args.system_code}")
    print(f"  Timeout:     {args.timeout}s")
    print()

    print("Connecting to DuoFern stick...")
    stick = DuoFernStick(
        port=args.port,
        system_code=system_code,
        paired_devices=paired,
        message_callback=on_message,
    )

    try:
        await stick.connect()
        print("Connected!\n")
    except Exception as err:
        print(f"\nERROR: Failed to connect: {err}")
        sys.exit(1)

    try:
        frame = DuoFernEncoder.build_start_unpair()
        await stick.send_command(frame)
        print(f"Unpairing mode ACTIVE for {args.timeout} seconds.")
        print(f"Press the programming button on the device to unpair...")
        print()

        timeout = args.timeout
        interval = 10
        elapsed = 0

        while elapsed < timeout:
            wait_time = min(interval, timeout - elapsed)
            try:
                await asyncio.wait_for(unpair_event.wait(), timeout=wait_time)
                break
            except asyncio.TimeoutError:
                elapsed += wait_time
                remaining = timeout - elapsed
                if remaining > 0:
                    print(f"  Waiting... {remaining}s remaining")

        if unpaired_code:
            code = unpaired_code[0]
            print(f"\nDevice successfully unpaired!")
            print(f"  Code: {code.hex}")
            print(f"  Type: {code.device_type_name}")
            print()
            print(f"Next steps:")
            print(f"  1. Remove this code from your HA integration:")
            print(f"     Settings -> Devices & Services -> DuoFern -> Configure")
            print(f'     Remove "{code.hex}" from the device codes list')
            print(
                f"  2. Also remove it from PAIRED_DEVICES in this script and test_duofern.py"
            )
        else:
            print(f"\nNo device responded within {timeout} seconds.")
            print(f"  - Make sure the device is in unpairing mode")
            print(f"  - Press and hold the programming button until the LED blinks")

        frame = DuoFernEncoder.build_stop_unpair()
        await stick.send_command(frame)
        _LOGGER.debug("Stop unpair sent")

        await asyncio.sleep(2)

    except Exception as err:
        print(f"\nERROR: {err}")
        import traceback

        traceback.print_exc()
    finally:
        print("\nDisconnecting...")
        await stick.disconnect()
        print("Done.")


# ---------------------------------------------------------------------------
# List command
# ---------------------------------------------------------------------------
async def run_list(args: argparse.Namespace) -> None:
    """List all paired devices and their status."""
    system_code = DuoFernId.from_hex(args.system_code)
    paired = [DuoFernId.from_hex(d) for d in PAIRED_DEVICES]

    received_devices: dict[str, dict] = {}

    def on_message(frame: bytearray) -> None:
        if DuoFernDecoder.is_status_response(frame):
            code = DuoFernDecoder.extract_device_code_from_status(frame)
            status = DuoFernDecoder.parse_status(frame)
            received_devices[code.hex] = {
                "code": code,
                "status": status,
                "raw": frame_to_hex(frame),
            }
        else:
            _LOGGER.debug("MSG: %s", frame_to_hex(frame))

    print(f"DuoFern Device List")
    print(f"  Port:        {args.port}")
    print(f"  System code: {args.system_code}")
    print(f"  Registered:  {len(PAIRED_DEVICES)} devices")
    print()

    print("Connecting to DuoFern stick...")
    stick = DuoFernStick(
        port=args.port,
        system_code=system_code,
        paired_devices=paired,
        message_callback=on_message,
    )

    try:
        await stick.connect()
        print("Connected!\n")
    except Exception as err:
        print(f"\nERROR: Failed to connect: {err}")
        sys.exit(1)

    try:
        # Send broadcast status request
        print("Requesting status from all devices...")
        frame = DuoFernEncoder.build_status_request_broadcast()
        await stick.send_command(frame)

        # Wait for responses
        wait_time = 12
        print(f"Waiting {wait_time}s for responses...\n")
        await asyncio.sleep(wait_time)

        # Display results
        print(f"{'=' * 72}")
        print(f"  {'Code':<8} {'Type':<22} {'Position':<10} {'Version':<8} {'Status'}")
        print(f"  {'-' * 8} {'-' * 22} {'-' * 10} {'-' * 8} {'-' * 12}")

        for device_hex in PAIRED_DEVICES:
            device_hex_upper = device_hex.upper()
            if device_hex_upper in received_devices:
                info = received_devices[device_hex_upper]
                code = info["code"]
                status = info["status"]
                pos_str = f"{status.position}%" if status.position is not None else "?"
                ver_str = status.version or "?"
                flags = []
                if status.manual_mode:
                    flags.append("manual")
                if status.time_automatic:
                    flags.append("timer")
                if status.sun_automatic:
                    flags.append("sun")
                flag_str = ", ".join(flags) if flags else "ok"
                print(
                    f"  {code.hex:<8} {code.device_type_name:<22} {pos_str:<10} {ver_str:<8} {flag_str}"
                )
            else:
                device_id = DuoFernId.from_hex(device_hex)
                print(
                    f"  {device_hex_upper:<8} {device_id.device_type_name:<22} {'--':<10} {'--':<8} NO RESPONSE"
                )

        print(f"{'=' * 72}")
        print(f"\n  {len(received_devices)}/{len(PAIRED_DEVICES)} devices responded")

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
        description="DuoFern device pairing tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  pair     Start pairing mode to add a new device
  unpair   Start unpairing mode to remove a device
  list     Show all paired devices with current status

Currently paired devices:
  406B0D  Rolladentuer         (Wohnzimmer)
  4090EA  Rolladenfenster      (Wohnzimmer)
  40B689  Rolladenfensterklein (Wohnzimmer Esstisch)
  4053B8  az_Rolladentuer      (Arbeitszimmer)
  4083D8  kz_Rolladenfenster   (Kinderzimmer)
  409C11  sz_Rolladenfenster   (Schlafzimmer)

Examples:
  python3 pair_duofern.py pair
  python3 pair_duofern.py pair --timeout 120 -v
  python3 pair_duofern.py unpair -v
  python3 pair_duofern.py list
        """,
    )

    parser.add_argument(
        "command",
        choices=["pair", "unpair", "list"],
        help="Command to execute",
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
        "--timeout",
        "-t",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Pairing/unpairing timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Validate
    args.system_code = args.system_code.upper()
    if not validate_system_code(args.system_code):
        parser.error(
            f"Invalid system code: {args.system_code} (need 6 hex chars starting with 6F)"
        )

    if args.timeout < 10 or args.timeout > 300:
        parser.error(f"Timeout must be 10-300 seconds, got {args.timeout}")

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.verbose:
        logging.getLogger("custom_components.duofern.stick").setLevel(logging.WARNING)
        logging.getLogger("custom_components.duofern.protocol").setLevel(
            logging.WARNING
        )

    # Run
    if args.command == "pair":
        asyncio.run(run_pair(args))
    elif args.command == "unpair":
        asyncio.run(run_unpair(args))
    elif args.command == "list":
        asyncio.run(run_list(args))


if __name__ == "__main__":
    main()
