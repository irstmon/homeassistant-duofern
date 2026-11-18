"""Serial connection helpers for local devices and network serial URLs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import urlparse

import serial  # type: ignore[import-untyped]
import serial_asyncio_fast  # type: ignore[import-untyped]

from .const import SERIAL_BAUDRATE
from .protocol import DuoFernEncoder

_LOGGER = logging.getLogger(__name__)

SUPPORTED_NETWORK_SCHEMES = {"socket", "rfc2217"}

# Seconds is_duofern_stick() waits for the answer to Init1.
PROBE_TIMEOUT_LOCAL = 2
PROBE_TIMEOUT_NETWORK = 5


def validate_serial_location(location: str) -> bool:
    """Return whether a local path or supported network URL is well formed."""
    if not location or location != location.strip():
        return False

    parsed = urlparse(location)
    if not parsed.scheme:
        return True
    if parsed.scheme.lower() not in SUPPORTED_NETWORK_SCHEMES:
        return False

    try:
        port = parsed.port
    except ValueError:
        return False
    return parsed.hostname is not None and port is not None


def check_serial_connection(location: str) -> bool:
    """Open and close a serial location to verify that it is reachable."""
    if not validate_serial_location(location):
        return False

    try:
        connection = serial.serial_for_url(
            location,
            baudrate=SERIAL_BAUDRATE,
            timeout=1,
            write_timeout=1,
        )
        connection.close()
        return True
    except (OSError, serial.SerialException, ValueError) as err:
        _LOGGER.warning("Cannot open serial connection %s: %s", location, err)
        return False


def is_duofern_stick(location: str) -> bool:
    """Send the first init frame and check that a DuoFern stick answers.

    The stick answers Init1 (01 00...) with a 22-byte frame that starts
    with 0x81. Init1 is also the first frame of every init attempt of the
    integration (10_DUOFERNSTICK.pm: DUOFERNSTICK_DoInit), so a stick that
    has seen it once more is in the same state as after a retried init.

    Must not be called for a port that is in use by a running integration:
    the frame would reach a stick that is initialised and in operation.

    A stick behind a network serial server (socket://, rfc2217://, e.g.
    ser2net) gets more time to answer than a local port.
    """
    is_network = urlparse(location).scheme.lower() in SUPPORTED_NETWORK_SCHEMES
    try:
        connection = serial.serial_for_url(
            location,
            baudrate=SERIAL_BAUDRATE,
            timeout=PROBE_TIMEOUT_NETWORK if is_network else PROBE_TIMEOUT_LOCAL,
            write_timeout=1,
        )
    except (OSError, serial.SerialException, ValueError) as err:
        _LOGGER.warning("Cannot open serial connection %s: %s", location, err)
        return False
    try:
        connection.reset_input_buffer()
        connection.write(bytes(DuoFernEncoder.build_init1()))
        answer = connection.read(22)
    except (OSError, serial.SerialException, ValueError) as err:
        _LOGGER.warning("No DuoFern stick answer on %s: %s", location, err)
        return False
    finally:
        connection.close()
    if len(answer) == 22 and answer[0] == 0x81:
        return True
    _LOGGER.warning(
        "Device on %s did not answer like a DuoFern stick (received %d bytes)",
        location,
        len(answer),
    )
    return False


async def create_serial_connection(
    loop: asyncio.AbstractEventLoop,
    protocol_factory: Callable[[], asyncio.Protocol],
    location: str,
    **kwargs: Any,
) -> tuple[asyncio.Transport, asyncio.Protocol]:
    """Create an asyncio connection for a local, socket, or RFC2217 serial port."""
    if urlparse(location).scheme.lower() != "rfc2217":
        return await serial_asyncio_fast.create_serial_connection(
            loop,
            protocol_factory,
            location,
            **kwargs,
        )

    # pyserial-asyncio-fast handles socket:// itself, but its regular transport
    # requires a file descriptor. PySerial's RFC2217 implementation does not
    # expose one, so perform its blocking reads and writes in worker threads.
    serial_kwargs = {**kwargs, "timeout": 0.25, "write_timeout": 1}
    callback = partial(serial.serial_for_url, location, **serial_kwargs)
    serial_instance = await loop.run_in_executor(None, callback)
    protocol = protocol_factory()
    transport = _ThreadedSerialTransport(loop, protocol, serial_instance)
    return transport, protocol


class _ThreadedSerialTransport(asyncio.Transport):
    """Asyncio transport backed by a blocking PySerial URL handler."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        protocol: asyncio.Protocol,
        serial_instance: serial.SerialBase,
    ) -> None:
        super().__init__()
        self._loop = loop
        self._protocol = protocol
        self._serial = serial_instance
        self._closing = False
        self._connection_lost_called = False
        self._write_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._reader_task = loop.create_task(self._read_loop())
        self._writer_task = loop.create_task(self._write_loop())
        loop.call_soon(protocol.connection_made, self)

    def is_closing(self) -> bool:
        """Return whether the transport is closing."""
        return self._closing

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        """Return the underlying serial connection when requested."""
        if name == "serial":
            return self._serial
        return default

    def write(self, data: bytes | bytearray | memoryview) -> None:
        """Queue bytes for writing without blocking the event loop."""
        if not self._closing:
            self._write_queue.put_nowait(bytes(data))

    def close(self) -> None:
        """Close the transport and its worker tasks."""
        self._start_close(None)

    def abort(self) -> None:
        """Abort the transport."""
        self._start_close(None)

    async def _read_loop(self) -> None:
        try:
            while not self._closing:
                data = await asyncio.to_thread(self._serial.read, 1024)
                if data and not self._closing:
                    self._protocol.data_received(data)
        except asyncio.CancelledError:
            pass
        except Exception as err:  # noqa: BLE001 - transport must report all failures
            self._start_close(err)

    async def _write_loop(self) -> None:
        try:
            while not self._closing:
                data = await self._write_queue.get()
                await asyncio.to_thread(self._serial.write, data)
                self._write_queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as err:  # noqa: BLE001 - transport must report all failures
            self._start_close(err)

    def _start_close(self, exc: Exception | None) -> None:
        if self._closing:
            return
        self._closing = True
        self._reader_task.cancel()
        self._writer_task.cancel()
        self._loop.create_task(self._finish_close(exc))

    async def _finish_close(self, exc: Exception | None) -> None:
        try:
            await asyncio.to_thread(self._serial.close)
            await asyncio.gather(
                self._reader_task,
                self._writer_task,
                return_exceptions=True,
            )
        finally:
            if not self._connection_lost_called:
                self._connection_lost_called = True
                self._protocol.connection_lost(exc)
