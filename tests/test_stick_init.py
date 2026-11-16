"""The stick initialisation handshake, replayed from a real startup log.

The frame sequence is the one logged by a real DuoFern stick on 2026-11-15
(system code 6F5C7E): every TX of the init and every stick answer.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from custom_components.duofern import stick as stick_module
from custom_components.duofern.protocol import DuoFernId
from custom_components.duofern.stick import DuoFernSerialProtocol, DuoFernStick

SYSTEM_CODE = "6F5C7E"
DEVICES = ["615B24", "61554F", "432FF1"]
PAD = "0" * 44

ACK = "81" + "00" * 21
INIT1 = "01" + "00" * 21
INIT2 = "0E" + "00" * 21
SET_DONGLE = ("0A6F5C7E0001" + PAD)[:44]
SET_DONGLE_REPLY = ("816F5C7E01" + PAD)[:44]
INIT3 = ("1414" + PAD)[:44]
INIT3_REPLY = ("8114" + PAD)[:44]
SET_PAIRS = [(f"03{i:02X}{code}" + PAD)[:44] for i, code in enumerate(DEVICES)]
INIT_END = ("1001" + PAD)[:44]
STATUS_BROADCAST = "0DFF0F400000000000000000000000000000FFFFFF01"

# What the stick answers to each request (from the log; SetPairs, InitEnd and
# the broadcast are acknowledged with a plain 81 00...).
REPLIES = {
    INIT1: ACK,
    INIT2: ACK,
    SET_DONGLE: SET_DONGLE_REPLY,
    INIT3: INIT3_REPLY,
    **{frame: ACK for frame in SET_PAIRS},
    INIT_END: ACK,
    STATUS_BROADCAST: ACK,
}

EXPECTED_TX = [
    INIT1,
    INIT2,
    SET_DONGLE,
    ACK,
    INIT3,
    ACK,
    SET_PAIRS[0],
    ACK,
    SET_PAIRS[1],
    ACK,
    SET_PAIRS[2],
    ACK,
    INIT_END,
    ACK,
    STATUS_BROADCAST,
    ACK,
]


class FakeTransport:
    """Records writes and lets the "stick" answer them."""

    def __init__(self, replies: dict[str, str], silent: set[str] | None = None) -> None:
        self.replies = replies
        self.silent = silent or set()
        self.written: list[str] = []
        self.protocol: DuoFernSerialProtocol | None = None
        self.closed = False
        self.released = False
        self.close_delay: float | None = 0.0

    def write(self, data: bytes) -> None:
        frame = bytes(data).hex().upper()
        self.written.append(frame)
        if frame == ACK or frame in self.silent:
            return
        reply = self.replies.get(frame)
        if reply is not None:
            assert self.protocol is not None
            asyncio.get_running_loop().call_soon(
                self.protocol.data_received, bytes.fromhex(reply)
            )

    def close(self) -> None:
        # Like the real transports: the port is released a little later and
        # connection_lost() reports it.
        self.closed = True
        self.released = False

        def release() -> None:
            self.released = True
            if self.protocol is not None:
                self.protocol.connection_lost(None)

        if self.close_delay is not None:
            asyncio.get_running_loop().call_later(self.close_delay, release)

    def is_closing(self) -> bool:
        return self.closed


def _make_stick(received: list[bytearray]) -> DuoFernStick:
    return DuoFernStick(
        port="/dev/ttyUSB0",
        system_code=DuoFernId.from_hex(SYSTEM_CODE),
        paired_devices=[DuoFernId.from_hex(code) for code in DEVICES],
        message_callback=received.append,
    )


def _patch_connection(transport: FakeTransport):
    async def create(loop, protocol_factory, location, **kwargs):
        protocol = protocol_factory()
        transport.protocol = protocol
        protocol.connection_made(transport)
        return transport, protocol

    return patch.object(stick_module, "create_serial_connection", create)


async def test_init_sequence_matches_the_real_log() -> None:
    """connect() sends exactly the frames of the logged init, in order."""
    received: list[bytearray] = []
    transport = FakeTransport(REPLIES)
    stick = _make_stick(received)

    with _patch_connection(transport):
        await stick.connect()

    assert transport.written == EXPECTED_TX
    assert stick.connected is True
    assert received == []  # init answers are not passed on as messages

    await stick.disconnect()
    assert transport.closed
    assert stick.connected is False


async def test_init_retries_after_a_missing_answer() -> None:
    """No answer to Init2 on the first attempt: the whole sequence starts again."""
    transport = FakeTransport(REPLIES, silent={INIT2})
    stick = _make_stick([])

    with _patch_connection(transport), patch.object(stick_module, "ACK_TIMEOUT", 0.05):
        original = stick._send_and_wait

        async def send_and_wait(frame, timeout=0.05):
            result = await original(frame, timeout=timeout)
            if frame.hex().upper() == INIT2:
                transport.silent.clear()  # answers from the second attempt on
            return result

        stick._send_and_wait = send_and_wait  # type: ignore[method-assign]
        await stick.connect()

    assert transport.written == [INIT1, INIT2] + EXPECTED_TX
    assert stick.connected is True
    await stick.disconnect()


async def test_init_continues_when_a_device_slot_is_not_acknowledged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A SetPairs without answer is logged; init goes on with the next device."""
    transport = FakeTransport(REPLIES, silent={SET_PAIRS[1]})
    stick = _make_stick([])

    with _patch_connection(transport):
        original = stick._send_and_wait

        async def send_and_wait(frame, timeout=0.05):
            return await original(frame, timeout=timeout)

        stick._send_and_wait = send_and_wait  # type: ignore[method-assign]
        await stick.connect()

    expected = list(EXPECTED_TX)
    del expected[9]  # no ACK after the unanswered SetPairs of device 2
    assert transport.written == expected
    assert stick.connected is True
    assert "61554F" in caplog.text and "did not acknowledge SetPairs" in caplog.text
    await stick.disconnect()


async def test_init_fails_after_all_attempts() -> None:
    """A stick that never answers ends in ConnectionError after 4 attempts."""
    transport = FakeTransport({})
    stick = _make_stick([])

    with _patch_connection(transport):
        original = stick._send_and_wait

        async def send_and_wait(frame, timeout=0.01):
            return await original(frame, timeout=timeout)

        stick._send_and_wait = send_and_wait  # type: ignore[method-assign]
        with pytest.raises(ConnectionError, match="failed after 4 attempts"):
            await stick.connect()

    assert transport.written == [INIT1] * 4
    assert stick.connected is False


async def test_send_and_wait_without_connection_returns_none() -> None:
    stick = _make_stick([])
    assert await stick._send_and_wait(bytearray.fromhex(INIT1)) is None


async def test_init_timeout_error_is_retried() -> None:
    """A TimeoutError raised inside an attempt leads to the next attempt."""
    transport = FakeTransport(REPLIES)
    stick = _make_stick([])
    calls = 0
    with _patch_connection(transport):
        original = stick._send_and_wait

        async def send_and_wait(frame, timeout=0.05):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError
            return await original(frame, timeout=timeout)

        stick._send_and_wait = send_and_wait  # type: ignore[method-assign]
        await stick.connect()

    assert transport.written == EXPECTED_TX
    await stick.disconnect()


def test_frames_of_the_log_are_well_formed() -> None:
    """Guard for the constants above: all frames are 22 bytes."""
    for frame in [*EXPECTED_TX, *REPLIES.values()]:
        assert len(frame) == 44, frame


# ---------------------------------------------------------------------------
# disconnect() waits until the port is released
# ---------------------------------------------------------------------------


async def test_disconnect_waits_until_the_port_is_released() -> None:
    """Log of 2026-11-16: the port was closed 24 ms after disconnect() returned.

    The reload opened it again in between and failed with "Could not
    exclusively lock port /dev/ttyUSB0".
    """
    transport = FakeTransport(REPLIES)
    transport.close_delay = 0.05
    stick = _make_stick([])
    with _patch_connection(transport):
        await stick.connect()
    await stick.disconnect()
    assert transport.released


async def test_disconnect_gives_up_when_the_port_is_never_released(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = FakeTransport(REPLIES)
    transport.close_delay = None  # never released
    stick = _make_stick([])
    with _patch_connection(transport):
        await stick.connect()
    with patch.object(stick_module, "PORT_CLOSE_TIMEOUT", 0.05):
        await stick.disconnect()
    assert not transport.released
    assert "was not released" in caplog.text
