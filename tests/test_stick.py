"""Tests for DuoFernStick and DuoFernSerialProtocol (stick.py).

These tests do NOT open a real serial port. DuoFernSerialProtocol is
tested directly (pure frame-accumulation logic). DuoFernStick is tested
for its state machine, send-queue guard, and frame-dispatch logic.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.duofern.stick import DuoFernSerialProtocol, DuoFernStick
from custom_components.duofern.const import FRAME_SIZE_BYTES
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_PORT, MOCK_SYSTEM_CODE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stick(
    message_callback=None,
    error_callback=None,
    paired=None,
) -> DuoFernStick:
    """Create a DuoFernStick without connecting."""
    return DuoFernStick(
        port=MOCK_PORT,
        system_code=DuoFernId.from_hex(MOCK_SYSTEM_CODE),
        paired_devices=paired or [],
        message_callback=message_callback or MagicMock(),
        error_callback=error_callback,
    )


def _make_protocol(callback=None) -> DuoFernSerialProtocol:
    """Create a DuoFernSerialProtocol with an optional callback."""
    return DuoFernSerialProtocol(frame_callback=callback or MagicMock())


# ---------------------------------------------------------------------------
# DuoFernStick — initial state
# ---------------------------------------------------------------------------


def test_stick_not_connected_before_connect():
    """stick.connected is False before async_connect is called."""
    stick = _make_stick()
    assert stick.connected is False


def test_stick_has_no_transport_initially():
    """_transport is None before connect."""
    stick = _make_stick()
    assert stick._transport is None


def test_stick_send_queue_empty_initially():
    """Send queue is empty before any commands are enqueued."""
    stick = _make_stick()
    assert stick._send_queue.empty()


# ---------------------------------------------------------------------------
# DuoFernStick — send_command raises when not connected
# ---------------------------------------------------------------------------


async def test_send_command_raises_connection_error_when_not_connected() -> None:
    """send_command raises ConnectionError when _connected is False."""
    stick = _make_stick()
    with pytest.raises(ConnectionError):
        await stick.send_command(bytearray(22))


async def test_send_command_queues_when_connected() -> None:
    """send_command enqueues the frame when _connected is True."""
    stick = _make_stick()
    stick._connected = True
    await stick.send_command(bytearray(22))
    assert not stick._send_queue.empty()


# ---------------------------------------------------------------------------
# DuoFernStick — _on_frame_received
# ---------------------------------------------------------------------------


def test_on_frame_received_acks_non_ack_frame():
    """For non-ACK frames, _write_frame is called once (to send ACK)."""
    message_cb = MagicMock()
    stick = _make_stick(message_callback=message_cb)
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch",
            return_value=False,
        ),
        patch.object(stick, "_write_frame") as mock_write,
    ):
        stick._on_frame_received(frame)

    mock_write.assert_called_once()  # ACK was written back


def test_on_frame_received_dispatches_non_ack_frame():
    """Non-ACK frame with should_dispatch=True reaches the message callback."""
    message_cb = MagicMock()
    stick = _make_stick(message_callback=message_cb)
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch",
            return_value=True,
        ),
        patch.object(stick, "_write_frame"),
    ):
        stick._on_frame_received(frame)

    message_cb.assert_called_once_with(frame)


def test_on_frame_received_does_not_dispatch_when_should_dispatch_false():
    """Non-ACK frame with should_dispatch=False is NOT forwarded."""
    message_cb = MagicMock()
    stick = _make_stick(message_callback=message_cb)
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch",
            return_value=False,
        ),
        patch.object(stick, "_write_frame"),
    ):
        stick._on_frame_received(frame)

    message_cb.assert_not_called()


def test_on_frame_received_ack_sets_event():
    """ACK frame sets the _ack_event."""
    stick = _make_stick()
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=True,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch_ack",
            return_value=False,
        ),
        patch.object(stick, "_write_frame"),
    ):
        stick._on_frame_received(frame)

    assert stick._ack_event.is_set()


def test_on_frame_received_ack_does_not_write_ack_back():
    """ACK frames do NOT get an ACK response written back."""
    stick = _make_stick()
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=True,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch_ack",
            return_value=False,
        ),
        patch.object(stick, "_write_frame") as mock_write,
    ):
        stick._on_frame_received(frame)

    mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# DuoFernStick — _on_queue_task_done
# ---------------------------------------------------------------------------


def test_on_queue_task_done_skips_when_closing():
    """No error callback when _closing=True (normal disconnect)."""
    error_cb = MagicMock()
    stick = _make_stick(error_callback=error_cb)
    stick._closing = True

    mock_task = MagicMock()
    stick._on_queue_task_done(mock_task)

    error_cb.assert_not_called()


def test_on_queue_task_done_calls_error_callback_on_exception():
    """error_callback is called when the queue task raises an exception."""
    error_cb = MagicMock()
    stick = _make_stick(error_callback=error_cb)
    stick._closing = False

    exc = RuntimeError("serial broke")
    mock_task = MagicMock()
    mock_task.exception.return_value = exc

    stick._on_queue_task_done(mock_task)

    error_cb.assert_called_once_with(exc)


def test_on_queue_task_done_no_error_callback_when_none():
    """If error_callback is None, no AttributeError is raised on exception."""
    stick = _make_stick(error_callback=None)
    stick._closing = False

    exc = RuntimeError("serial broke")
    mock_task = MagicMock()
    mock_task.exception.return_value = exc

    # Must not raise
    stick._on_queue_task_done(mock_task)


def test_on_queue_task_done_no_call_when_task_has_no_exception():
    """error_callback is NOT called when task exits cleanly (exc=None)."""
    error_cb = MagicMock()
    stick = _make_stick(error_callback=error_cb)
    stick._closing = False

    mock_task = MagicMock()
    mock_task.exception.return_value = None

    stick._on_queue_task_done(mock_task)

    error_cb.assert_not_called()


# ---------------------------------------------------------------------------
# DuoFernSerialProtocol — frame accumulation
# ---------------------------------------------------------------------------


def test_protocol_does_not_dispatch_partial_frame():
    """Fewer than 22 bytes → callback not called."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    proto.data_received(bytes(FRAME_SIZE_BYTES - 1))
    cb.assert_not_called()


def test_protocol_dispatches_complete_22_byte_frame():
    """Exactly 22 bytes → callback called once with that frame."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    proto.data_received(bytes(FRAME_SIZE_BYTES))
    cb.assert_called_once()
    args, _ = cb.call_args
    assert len(args[0]) == FRAME_SIZE_BYTES


def test_protocol_dispatches_two_frames_from_44_bytes():
    """44 bytes → callback called twice."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    proto.data_received(bytes(FRAME_SIZE_BYTES * 2))
    assert cb.call_count == 2


def test_protocol_split_delivery_dispatches_once():
    """10 bytes then 12 bytes → one complete 22-byte frame dispatched."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    proto.data_received(bytes(10))
    cb.assert_not_called()
    proto.data_received(bytes(12))
    cb.assert_called_once()


def test_protocol_0x06_legacy_dispatches_at_22_bytes():
    """0x06 first byte with exactly 22 bytes → dispatched immediately (legacy)."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    # 0x06 frames are normally 38 bytes, but 22-byte legacy devices get dispatched early
    frame = bytearray(FRAME_SIZE_BYTES)
    frame[0] = 0x06
    proto.data_received(bytes(frame))
    cb.assert_called_once()


def test_protocol_0x06_dispatches_at_38_bytes():
    """0x06 first byte with 38 bytes → dispatched at 38."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    frame = bytearray(38)
    frame[0] = 0x06
    proto.data_received(bytes(frame))
    cb.assert_called_once()
    args, _ = cb.call_args
    assert len(args[0]) == 38


def test_protocol_buffer_cleared_after_dispatch():
    """After dispatching a frame the internal buffer is empty."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    proto.data_received(bytes(FRAME_SIZE_BYTES))
    assert len(proto._buffer) == 0


def test_protocol_partial_stays_in_buffer():
    """Partial data remains in buffer until completed."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    proto.data_received(bytes(5))
    assert len(proto._buffer) == 5


# ---------------------------------------------------------------------------
# DuoFernSerialProtocol — init response future
# ---------------------------------------------------------------------------


async def test_protocol_init_future_resolves_on_complete_frame() -> None:
    """When an init future is set, data_received resolves it instead of calling callback."""
    cb = MagicMock()
    proto = _make_protocol(cb)

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bytearray] = loop.create_future()
    proto.set_init_response_future(fut)

    proto.data_received(bytes(FRAME_SIZE_BYTES))

    assert fut.done()
    assert len(fut.result()) == FRAME_SIZE_BYTES
    cb.assert_not_called()


async def test_protocol_init_future_cleared_after_set() -> None:
    """The init future can be set to None to resume normal dispatch."""
    cb = MagicMock()
    proto = _make_protocol(cb)

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bytearray] = loop.create_future()
    proto.set_init_response_future(fut)
    proto.set_init_response_future(None)

    proto.data_received(bytes(FRAME_SIZE_BYTES))

    # Future was cleared — normal callback path taken
    cb.assert_called_once()
    assert not fut.done()


# ---------------------------------------------------------------------------
# DuoFernSerialProtocol — flush buffer
# ---------------------------------------------------------------------------


def test_protocol_flush_buffer_discards_partial():
    """_flush_buffer clears any partial data in the buffer."""
    proto = _make_protocol()
    proto._buffer.extend(b"\x01\x02\x03")
    proto._flush_buffer()
    assert len(proto._buffer) == 0


# ---------------------------------------------------------------------------
# DuoFernStick — _on_queue_task_done — CancelledError path
# ---------------------------------------------------------------------------


def test_on_queue_task_done_cancelled_error_returns_silently():
    """CancelledError from task.exception() is swallowed (cancelled during shutdown)."""
    error_cb = MagicMock()
    stick = _make_stick(error_callback=error_cb)
    stick._closing = False

    mock_task = MagicMock()
    mock_task.exception.side_effect = asyncio.CancelledError()

    stick._on_queue_task_done(mock_task)

    error_cb.assert_not_called()


# ---------------------------------------------------------------------------
# DuoFernStick — _write_frame
# ---------------------------------------------------------------------------


def test_write_frame_does_nothing_when_transport_none():
    """_write_frame logs error and returns when transport is None."""
    stick = _make_stick()
    stick._transport = None
    # Must not raise
    stick._write_frame(bytearray(FRAME_SIZE_BYTES))


def test_write_frame_writes_bytes_to_transport():
    """_write_frame calls transport.write with the frame as bytes."""
    stick = _make_stick()
    mock_transport = MagicMock()
    stick._transport = mock_transport
    frame = bytearray(b"\x01\x02" + bytes(FRAME_SIZE_BYTES - 2))
    stick._write_frame(frame)
    mock_transport.write.assert_called_once_with(bytes(frame))


# ---------------------------------------------------------------------------
# DuoFernStick — _on_frame_received — ACK dispatch path
# ---------------------------------------------------------------------------


def test_on_frame_received_ack_with_should_dispatch_ack_calls_callback():
    """ACK frames with should_dispatch_ack=True reach the message callback."""
    message_cb = MagicMock()
    stick = _make_stick(message_callback=message_cb)
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=True,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch_ack",
            return_value=True,
        ),
        patch.object(stick, "_write_frame"),
    ):
        stick._on_frame_received(frame)

    message_cb.assert_called_once_with(frame)


def test_on_frame_received_non_ack_callback_exception_does_not_propagate():
    """Exception inside the non-ACK message callback is caught and logged."""
    message_cb = MagicMock(side_effect=RuntimeError("boom"))
    stick = _make_stick(message_callback=message_cb)
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=False,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch",
            return_value=True,
        ),
        patch.object(stick, "_write_frame"),
    ):
        # Must not raise
        stick._on_frame_received(frame)


def test_on_frame_received_ack_callback_exception_does_not_propagate():
    """Exception inside the ACK dispatch callback is caught and logged."""
    message_cb = MagicMock(side_effect=RuntimeError("boom"))
    stick = _make_stick(message_callback=message_cb)
    frame = bytearray(FRAME_SIZE_BYTES)

    with (
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.is_ack",
            return_value=True,
        ),
        patch(
            "custom_components.duofern.stick.DuoFernDecoder.should_dispatch_ack",
            return_value=True,
        ),
        patch.object(stick, "_write_frame"),
    ):
        # Must not raise
        stick._on_frame_received(frame)


# ---------------------------------------------------------------------------
# DuoFernSerialProtocol — connection_made / connection_lost
# ---------------------------------------------------------------------------


def test_protocol_connection_made_does_not_raise():
    """connection_made just logs; must not raise."""
    proto = _make_protocol()
    proto.connection_made(MagicMock())


def test_protocol_connection_lost_with_exception():
    """connection_lost logs error when exc is not None."""
    proto = _make_protocol()
    proto.connection_lost(RuntimeError("lost"))  # must not raise


def test_protocol_connection_lost_without_exception():
    """connection_lost logs debug when exc is None."""
    proto = _make_protocol()
    proto.connection_lost(None)  # must not raise


# ---------------------------------------------------------------------------
# DuoFernSerialProtocol — flush handle lifecycle
# ---------------------------------------------------------------------------


async def test_protocol_data_received_creates_flush_handle_for_partial() -> None:
    """Partial data in buffer schedules a flush timer."""
    proto = _make_protocol()
    proto.data_received(bytes(5))  # only partial (< 22)
    assert proto._flush_handle is not None
    proto._flush_handle.cancel()


async def test_protocol_data_received_cancels_existing_flush_handle() -> None:
    """New data cancels the pending flush timer."""
    cb = MagicMock()
    proto = _make_protocol(cb)
    # First partial → creates flush handle
    proto.data_received(bytes(5))
    old_handle = proto._flush_handle
    assert old_handle is not None

    # More data arrives completing the frame → old handle cancelled
    proto.data_received(bytes(FRAME_SIZE_BYTES - 5))
    assert old_handle.cancelled()
    assert proto._flush_handle is None  # no new partial remains


# ---------------------------------------------------------------------------
# DuoFernSerialProtocol — init future already done falls through to callback
# ---------------------------------------------------------------------------


async def test_protocol_init_future_already_done_uses_callback() -> None:
    """If the init future is already resolved, the frame goes to the callback."""
    cb = MagicMock()
    proto = _make_protocol(cb)

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bytearray] = loop.create_future()
    fut.set_result(bytearray(FRAME_SIZE_BYTES))  # already done
    proto.set_init_response_future(fut)

    proto.data_received(bytes(FRAME_SIZE_BYTES))

    cb.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernStick — disconnect
# ---------------------------------------------------------------------------


async def test_disconnect_cancels_running_queue_task() -> None:
    """disconnect() cancels the queue task if it is running."""
    stick = _make_stick()
    stick._connected = True

    async def _forever() -> None:
        while True:
            await asyncio.sleep(10)

    task = asyncio.create_task(_forever())
    stick._queue_task = task

    await stick.disconnect()

    assert task.cancelled()
    assert stick._connected is False


async def test_disconnect_closes_transport() -> None:
    """disconnect() closes the serial transport."""
    stick = _make_stick()
    stick._connected = True
    mock_transport = MagicMock()
    stick._transport = mock_transport

    await stick.disconnect()

    mock_transport.close.assert_called_once()
    assert stick._transport is None


async def test_disconnect_when_no_task_and_no_transport() -> None:
    """disconnect() with no task and no transport does not raise."""
    stick = _make_stick()
    stick._connected = True
    assert stick._queue_task is None
    assert stick._transport is None
    await stick.disconnect()  # must not raise


# ---------------------------------------------------------------------------
# DuoFernStick — connect
# ---------------------------------------------------------------------------


async def test_connect_sets_connected_and_starts_queue_task() -> None:
    """connect() opens serial port, runs init, starts the queue task."""
    stick = _make_stick()

    mock_transport = MagicMock()
    mock_serial_protocol = MagicMock()
    mock_serial_protocol.set_init_response_future = MagicMock()

    with (
        patch(
            "custom_components.duofern.stick.serial_asyncio_fast.create_serial_connection",
            new_callable=AsyncMock,
            return_value=(mock_transport, mock_serial_protocol),
        ),
        patch.object(stick, "_init_sequence", new_callable=AsyncMock),
    ):
        await stick.connect()

    assert stick._connected is True
    assert stick._queue_task is not None

    # Clean up the queue task
    stick._closing = True
    stick._queue_task.cancel()
    try:
        await stick._queue_task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# DuoFernStick — _process_send_queue
# ---------------------------------------------------------------------------


async def test_process_send_queue_writes_frame_and_waits_for_ack() -> None:
    """_process_send_queue writes the queued frame to the transport."""
    stick = _make_stick()
    mock_transport = MagicMock()
    stick._transport = mock_transport
    stick._connected = True

    frame = bytearray(FRAME_SIZE_BYTES)
    await stick._send_queue.put(frame)

    # Signal ACK immediately so the queue loop unblocks
    async def _signal_ack() -> None:
        await asyncio.sleep(0)
        stick._ack_event.set()

    asyncio.create_task(_signal_ack())

    task = asyncio.create_task(stick._process_send_queue())
    await asyncio.sleep(0.05)

    stick._closing = True
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    mock_transport.write.assert_called()


async def test_process_send_queue_proceeds_on_ack_timeout() -> None:
    """_process_send_queue sends next frame after ACK timeout (no hang)."""
    from custom_components.duofern.const import ACK_TIMEOUT

    stick = _make_stick()
    mock_transport = MagicMock()
    stick._transport = mock_transport
    stick._connected = True

    frame = bytearray(FRAME_SIZE_BYTES)
    await stick._send_queue.put(frame)

    with patch(
        "custom_components.duofern.stick.asyncio.wait_for",
        side_effect=asyncio.TimeoutError,
    ):
        task = asyncio.create_task(stick._process_send_queue())
        await asyncio.sleep(0)

        stick._closing = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    mock_transport.write.assert_called()


# ---------------------------------------------------------------------------
# DuoFernStick — _send_and_wait with no serial protocol
# ---------------------------------------------------------------------------


async def test_send_and_wait_returns_none_when_no_protocol() -> None:
    """_send_and_wait returns None immediately if _serial_protocol is None."""
    stick = _make_stick()
    stick._serial_protocol = None
    result = await stick._send_and_wait(bytearray(FRAME_SIZE_BYTES))
    assert result is None
