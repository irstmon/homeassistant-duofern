"""Tests for serial_connection.py (local ports, socket:// and rfc2217:// URLs)."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import serial

from custom_components.duofern import serial_connection
from custom_components.duofern.const import SERIAL_BAUDRATE
from custom_components.duofern.serial_connection import (
    _ThreadedSerialTransport,
    check_serial_connection,
    create_serial_connection,
    is_duofern_stick,
    validate_serial_location,
)

# ---------------------------------------------------------------------------
# validate_serial_location
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "valid"),
    [
        ("/dev/ttyUSB0", True),
        ("/dev/serial/by-id/usb-Rademacher_DuoFern_USB-Stick_WR04ZFP4-if00", True),
        ("COM3", True),
        ("socket://192.168.1.50:4001", True),
        ("SOCKET://stick.local:4001", True),
        ("rfc2217://192.168.1.50:4001", True),
        ("", False),
        (" /dev/ttyUSB0", False),
        ("/dev/ttyUSB0 ", False),
        ("socket://192.168.1.50", False),  # no port
        ("socket://:4001", False),  # no host
        ("socket://192.168.1.50:port", False),  # port not numeric
        ("tcp://192.168.1.50:4001", False),  # scheme not supported
        ("http://192.168.1.50:4001", False),
    ],
)
def test_validate_serial_location(location: str, valid: bool) -> None:
    assert validate_serial_location(location) is valid


# ---------------------------------------------------------------------------
# check_serial_connection
# ---------------------------------------------------------------------------


def test_check_opens_and_closes_the_port() -> None:
    connection = MagicMock()
    with patch.object(serial, "serial_for_url", return_value=connection) as opener:
        assert check_serial_connection("/dev/ttyUSB0") is True
    opener.assert_called_once_with(
        "/dev/ttyUSB0", baudrate=SERIAL_BAUDRATE, timeout=1, write_timeout=1
    )
    connection.close.assert_called_once()


def test_check_rejects_malformed_location_without_opening() -> None:
    with patch.object(serial, "serial_for_url") as opener:
        assert check_serial_connection("tcp://host:1") is False
    opener.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [OSError("no such device"), serial.SerialException("busy"), ValueError("bad")],
)
def test_check_returns_false_when_port_cannot_be_opened(error: Exception) -> None:
    with patch.object(serial, "serial_for_url", side_effect=error):
        assert check_serial_connection("/dev/ttyUSB9") is False


# ---------------------------------------------------------------------------
# create_serial_connection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("location", ["/dev/ttyUSB0", "socket://192.168.1.50:4001"])
async def test_local_and_socket_use_serial_asyncio(location: str) -> None:
    """Local ports and socket:// go straight to pyserial-asyncio-fast."""
    loop = asyncio.get_running_loop()
    factory = MagicMock()
    result = (MagicMock(), MagicMock())
    with patch.object(
        serial_connection.serial_asyncio_fast,
        "create_serial_connection",
        new_callable=AsyncMock,
        return_value=result,
    ) as create:
        assert (
            await create_serial_connection(loop, factory, location, baudrate=115200)
            == result
        )
    create.assert_awaited_once_with(loop, factory, location, baudrate=115200)


class FakeSerial:
    """Blocking serial object as PySerial's RFC2217 handler provides it."""

    def __init__(self) -> None:
        self.incoming: list[bytes] = []
        self.written: list[bytes] = []
        self.closed = threading.Event()
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None

    def read(self, size: int) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        if self.incoming:
            return self.incoming.pop(0)
        time.sleep(0.005)  # like a read timeout
        return b""

    def write(self, data: bytes) -> None:
        if self.write_error is not None:
            raise self.write_error
        self.written.append(data)

    def close(self) -> None:
        self.closed.set()


async def _wait_for(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.005)


async def test_rfc2217_uses_threaded_transport() -> None:
    """rfc2217:// opens the PySerial handler and wraps it in the transport."""
    loop = asyncio.get_running_loop()
    fake = FakeSerial()
    protocol = MagicMock()
    with patch.object(serial, "serial_for_url", return_value=fake) as opener:
        transport, returned_protocol = await create_serial_connection(
            loop, lambda: protocol, "rfc2217://192.168.1.50:4001", baudrate=115200
        )
    opener.assert_called_once_with(
        "rfc2217://192.168.1.50:4001", baudrate=115200, timeout=0.25, write_timeout=1
    )
    assert isinstance(transport, _ThreadedSerialTransport)
    assert returned_protocol is protocol
    assert transport.get_extra_info("serial") is fake
    assert transport.get_extra_info("peername") is None
    assert transport.get_extra_info("peername", "x") == "x"

    await _wait_for(lambda: protocol.connection_made.called)
    protocol.connection_made.assert_called_once_with(transport)

    # received bytes reach the protocol
    fake.incoming.append(b"\x81" + bytes(21))
    await _wait_for(lambda: protocol.data_received.called)
    protocol.data_received.assert_called_once_with(b"\x81" + bytes(21))

    # written bytes reach the serial object, bytearray is accepted
    transport.write(bytearray(b"\x0d\x01"))
    await _wait_for(lambda: fake.written)
    assert fake.written == [b"\x0d\x01"]

    # close: serial closed, connection_lost(None) exactly once, later writes dropped
    assert transport.is_closing() is False
    transport.close()
    assert transport.is_closing() is True
    transport.close()  # second call is a no-op
    transport.write(b"\x00")
    await _wait_for(lambda: protocol.connection_lost.called)
    await asyncio.sleep(0.02)
    assert fake.closed.is_set()
    protocol.connection_lost.assert_called_once_with(None)
    assert fake.written == [b"\x0d\x01"]


async def test_transport_abort_closes() -> None:
    fake = FakeSerial()
    protocol = MagicMock()
    transport = _ThreadedSerialTransport(asyncio.get_running_loop(), protocol, fake)
    transport.abort()
    await _wait_for(lambda: protocol.connection_lost.called)
    protocol.connection_lost.assert_called_once_with(None)
    assert fake.closed.is_set()


async def test_transport_read_error_is_reported() -> None:
    """A failing read closes the transport and passes the error on."""
    fake = FakeSerial()
    error = serial.SerialException("connection reset")
    fake.read_error = error
    protocol = MagicMock()
    transport = _ThreadedSerialTransport(asyncio.get_running_loop(), protocol, fake)
    await _wait_for(lambda: protocol.connection_lost.called)
    protocol.connection_lost.assert_called_once_with(error)
    assert transport.is_closing() and fake.closed.is_set()


async def test_transport_write_error_is_reported() -> None:
    """A failing write closes the transport and passes the error on."""
    fake = FakeSerial()
    error = serial.SerialTimeoutException("write timeout")
    fake.write_error = error
    protocol = MagicMock()
    transport = _ThreadedSerialTransport(asyncio.get_running_loop(), protocol, fake)
    transport.write(b"\x0d")
    await _wait_for(lambda: protocol.connection_lost.called)
    protocol.connection_lost.assert_called_once_with(error)
    assert transport.is_closing() and fake.closed.is_set()


# ---------------------------------------------------------------------------
# is_duofern_stick
# ---------------------------------------------------------------------------

INIT1 = bytes.fromhex("01" + "00" * 21)
STICK_ANSWER = bytes.fromhex("81" + "00" * 21)  # as logged from a real stick


def _probe_connection(answer: bytes) -> MagicMock:
    connection = MagicMock()
    connection.read.return_value = answer
    return connection


def test_stick_answer_is_recognised() -> None:
    connection = _probe_connection(STICK_ANSWER)
    with patch.object(serial, "serial_for_url", return_value=connection) as opener:
        assert is_duofern_stick("/dev/ttyUSB0") is True
    opener.assert_called_once_with(
        "/dev/ttyUSB0", baudrate=SERIAL_BAUDRATE, timeout=2, write_timeout=1
    )
    connection.write.assert_called_once_with(INIT1)
    connection.read.assert_called_once_with(22)
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    ("location", "timeout"),
    [
        ("/dev/ttyUSB0", 2),
        ("COM3", 2),
        ("socket://192.168.1.50:4001", 5),
        ("rfc2217://192.168.1.50:4001", 5),
        ("RFC2217://stick.local:4001", 5),
    ],
)
def test_network_ports_get_more_time_to_answer(location: str, timeout: int) -> None:
    """ser2net and similar add latency: 5 s instead of 2 s for the answer."""
    connection = _probe_connection(STICK_ANSWER)
    with patch.object(serial, "serial_for_url", return_value=connection) as opener:
        assert is_duofern_stick(location) is True
    assert opener.call_args.kwargs["timeout"] == timeout


@pytest.mark.parametrize(
    "answer",
    [b"", STICK_ANSWER[:10], bytes(22), b"OK\r\n", bytes.fromhex("0F" + "00" * 21)],
)
def test_other_answers_are_not_a_stick(answer: bytes) -> None:
    connection = _probe_connection(answer)
    with patch.object(serial, "serial_for_url", return_value=connection):
        assert is_duofern_stick("/dev/ttyUSB0") is False
    connection.close.assert_called_once()


def test_probe_port_cannot_be_opened() -> None:
    with patch.object(
        serial, "serial_for_url", side_effect=serial.SerialException("busy")
    ):
        assert is_duofern_stick("/dev/ttyUSB9") is False


@pytest.mark.parametrize("failing", ["write", "read"])
def test_probe_io_error_closes_the_port(failing: str) -> None:
    connection = _probe_connection(STICK_ANSWER)
    getattr(connection, failing).side_effect = serial.SerialException("gone")
    with patch.object(serial, "serial_for_url", return_value=connection):
        assert is_duofern_stick("/dev/ttyUSB0") is False
    connection.close.assert_called_once()
