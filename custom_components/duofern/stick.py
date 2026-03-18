"""Async serial communication with the DuoFern USB stick.

Uses pyserial-asyncio-fast for non-blocking serial I/O via asyncio.Protocol.
Implements the initialization handshake and ACK-gated send queue exactly as
described in FHEM's 10_DUOFERNSTICK.pm.

Architecture:
  DuoFernStick
    ├── _protocol: DuoFernSerialProtocol (asyncio.Protocol)
    ├── _send_queue: asyncio.Queue of frames to send
    └── _init_sequence(): 7-step handshake with retry

From 10_DUOFERNSTICK.pm:
  DUOFERNSTICK_DoInit    → _init_sequence()
  DUOFERNSTICK_Parse     → _on_frame_received()
  DUOFERNSTICK_Read      → DuoFernSerialProtocol.data_received()
  DUOFERNSTICK_AddSendQueue / DUOFERNSTICK_HandleWriteQueue
                         → _process_send_queue()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import serial_asyncio_fast  # type: ignore[import-untyped]

from .const import (
    ACK_TIMEOUT,
    FLUSH_BUFFER_TIMEOUT,
    FRAME_SIZE_BYTES,
    INIT_RETRY_COUNT,
    REMOTE_PAIR_TIMEOUT,
    SERIAL_BAUDRATE,
)
from .protocol import (
    DuoFernDecoder,
    DuoFernEncoder,
    DuoFernId,
    frame_to_hex,
)

_LOGGER = logging.getLogger(__name__)


class DuoFernStick:
    """Manages the DuoFern USB stick serial connection.

    Lifecycle:
      1. stick = DuoFernStick(port, system_code, paired_devices, callback)
      2. await stick.connect()       # opens serial, runs init sequence
      3. await stick.send_command()  # ACK-gated send queue
      4. await stick.disconnect()    # clean shutdown
    """

    def __init__(
        self,
        port: str,
        system_code: DuoFernId,
        paired_devices: list[DuoFernId],
        message_callback: Callable[[bytearray], None],
        error_callback: Callable[[Exception], None] | None = None,
    ) -> None:
        """Initialize the stick manager.

        Args:
            port:             Serial port path (e.g. /dev/ttyUSB0)
            system_code:      6-char hex dongle serial starting with 6F
            paired_devices:   List of paired device codes to register on init
            message_callback: Called for every dispatchable message received
            error_callback:   Optional callback invoked when the send queue task
                              crashes. Used by the coordinator to trigger a reconnect.
                              Signature: (exc: Exception) -> None
        """
        self._port = port
        self._system_code = system_code
        self._paired_devices = paired_devices
        self._message_callback = message_callback
        self._on_error = error_callback

        self._transport: asyncio.Transport | None = None
        self._serial_protocol: DuoFernSerialProtocol | None = None

        # Send queue: only one command in-flight at a time (ACK-gated).
        # From 10_DUOFERNSTICK.pm:
        #   cmdEx tracks in-flight count (0 or 1).
        #   On ACK receipt, cmdEx decrements, next command is popped.
        self._send_queue: asyncio.Queue[bytearray] = asyncio.Queue()
        self._ack_event: asyncio.Event = asyncio.Event()
        self._cmd_in_flight: bool = False
        self._queue_task: asyncio.Task[None] | None = None

        self._connected: bool = False
        self._initialized: bool = False
        self._closing: bool = False

    @property
    def connected(self) -> bool:
        """Return True if serial port is open AND init handshake is complete."""
        return self._connected and self._initialized

    async def connect(self) -> None:
        """Open serial port, run init sequence, start send queue processor."""
        _LOGGER.info(
            "Connecting to DuoFern stick on %s (system code: %s)",
            self._port,
            self._system_code.hex,
        )

        loop = asyncio.get_running_loop()

        (
            self._transport,
            self._serial_protocol,
        ) = await serial_asyncio_fast.create_serial_connection(
            loop,
            lambda: DuoFernSerialProtocol(self._on_frame_received),
            self._port,
            baudrate=SERIAL_BAUDRATE,
            bytesize=serial_asyncio_fast.serial.EIGHTBITS,
            parity=serial_asyncio_fast.serial.PARITY_NONE,
            stopbits=serial_asyncio_fast.serial.STOPBITS_ONE,
        )

        self._connected = True
        _LOGGER.debug("Serial port opened: %s", self._port)

        # Run the initialization handshake
        await self._init_sequence()

        # Start the ACK-gated send queue processor.
        # A done_callback is attached so that if the task exits unexpectedly
        # (e.g. an unhandled exception in _process_send_queue), the error is
        # logged immediately and a reconnect is triggered via the on_error callback.
        # Without this, the task could die silently and all subsequent send_command
        # calls would queue up forever with no output — confirmed as a real bug.
        self._queue_task = asyncio.create_task(self._process_send_queue())
        self._queue_task.add_done_callback(self._on_queue_task_done)

        _LOGGER.info("DuoFern stick initialized successfully")

    async def disconnect(self) -> None:
        """Close the serial connection and stop the queue processor."""
        self._closing = True
        self._initialized = False

        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass

        if self._transport:
            self._transport.close()
            self._transport = None

        self._connected = False
        _LOGGER.info("DuoFern stick disconnected")

    def _on_queue_task_done(self, task: asyncio.Task) -> None:
        """Handle unexpected termination of the send queue processor task.

        Called automatically when _queue_task finishes — either normally
        (disconnect called), due to cancellation, or due to an unhandled error.

        If the task raised an exception, we log it at ERROR level so it is
        immediately visible in the HA log. We then invoke the on_error callback
        (if set) which triggers coordinator reconnect — same path as other
        stick errors.

        Without this callback, a crash in _process_send_queue was completely
        silent: all subsequent send_command calls would enqueue frames but
        nothing would ever be sent to the serial port.
        """
        if self._closing:
            # Normal shutdown — task was cancelled by disconnect(), not an error.
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return  # Cancelled during a non-closing disconnect — acceptable
        if exc is not None:
            _LOGGER.error(
                "DuoFern send queue task crashed unexpectedly: %s — "
                "triggering reconnect. No commands will be sent until reconnected.",
                exc,
                exc_info=exc,
            )
            if self._on_error:
                self._on_error(exc)

    async def send_command(self, frame: bytearray) -> None:
        """Enqueue a command frame for sending.

        Commands are sent one-at-a-time, waiting for ACK before sending next.
        From 10_DUOFERNSTICK.pm: DUOFERNSTICK_AddSendQueue.
        """
        if not self._connected:
            raise ConnectionError("DuoFern stick not connected")
        await self._send_queue.put(frame)
        _LOGGER.debug(
            "Command queued: %s (queue size: %d)",
            frame_to_hex(frame),
            self._send_queue.qsize(),
        )

    # ------------------------------------------------------------------
    # Internal: Initialization sequence
    # ------------------------------------------------------------------

    async def _init_sequence(self) -> None:
        """Run the 7-step initialization handshake.

        Directly mirrors DUOFERNSTICK_DoInit from 10_DUOFERNSTICK.pm:
          1. Send Init1   (0x01),          wait for response
          2. Send Init2   (0x0E),          wait for response
          3. Send SetDongle (0x0A + code), wait for response, send ACK
          4. Send Init3   (0x14 0x14),     wait for response, send ACK
          5. For each paired device:
               Send SetPairs (0x03 + idx + code), wait for response, send ACK
          6. Send InitEnd (0x10 0x01),     wait for response, send ACK
          7. Send StatusRequest broadcast, wait for response, send ACK

        Retries up to INIT_RETRY_COUNT times on failure.

        From 10_DUOFERNSTICK.pm:
          # This is relevant for windows/USB only
          (flush buffer before starting init)
        """
        for attempt in range(INIT_RETRY_COUNT):
            try:
                _LOGGER.debug("Init attempt %d/%d", attempt + 1, INIT_RETRY_COUNT)

                # Step 1: Init1
                resp = await self._send_and_wait(DuoFernEncoder.build_init1())
                if resp is None:
                    continue
                _LOGGER.debug("Init1 response: %s", frame_to_hex(resp))

                # Step 2: Init2
                resp = await self._send_and_wait(DuoFernEncoder.build_init2())
                if resp is None:
                    continue
                _LOGGER.debug("Init2 response: %s", frame_to_hex(resp))

                # Step 3: SetDongle — register our system code with the stick
                resp = await self._send_and_wait(
                    DuoFernEncoder.build_set_dongle(self._system_code)
                )
                if resp is None:
                    continue
                _LOGGER.debug("SetDongle response: %s", frame_to_hex(resp))
                self._write_frame(DuoFernEncoder.build_ack())

                # Step 4: Init3 — response byte[1]==0x14 confirms FW 2.0
                resp = await self._send_and_wait(DuoFernEncoder.build_init3())
                if resp is None:
                    continue
                _LOGGER.debug("Init3 response (firmware info): %s", frame_to_hex(resp))
                self._write_frame(DuoFernEncoder.build_ack())

                # Step 5: Register each paired device by index.
                # From 10_DUOFERNSTICK.pm: duoSetPairs = "03nnyyyyyy..."
                #   nn = slot index (0-based)
                #   yyyyyy = device code
                _failed_devices: list[str] = []
                for idx, device in enumerate(self._paired_devices):
                    resp = await self._send_and_wait(
                        DuoFernEncoder.build_set_pair(idx, device)
                    )
                    if resp is None:
                        _LOGGER.warning(
                            "Device %s did not respond during init (slot %d) — "
                            "commands to this device may not work until reconnect.",
                            device.hex,
                            idx,
                        )
                        _failed_devices.append(device.hex)
                        continue
                    self._write_frame(DuoFernEncoder.build_ack())

                if _failed_devices:
                    _LOGGER.warning(
                        "DuoFern init: %d device(s) did not acknowledge SetPairs: %s. "
                        "These devices will not receive commands until the next "
                        "successful reconnect.",
                        len(_failed_devices),
                        ", ".join(_failed_devices),
                    )

                # Step 6: InitEnd — signals end of device registration
                resp = await self._send_and_wait(DuoFernEncoder.build_init_end())
                if resp is None:
                    continue
                self._write_frame(DuoFernEncoder.build_ack())

                # Step 7: Status broadcast — trigger initial state from all devices
                resp = await self._send_and_wait(
                    DuoFernEncoder.build_status_request_broadcast()
                )
                if resp is None:
                    continue
                self._write_frame(DuoFernEncoder.build_ack())

                self._initialized = True
                _LOGGER.info("DuoFern stick init complete (attempt %d)", attempt + 1)
                return

            except TimeoutError:
                _LOGGER.warning("Init attempt %d timed out, retrying...", attempt + 1)
                continue

        raise ConnectionError(
            f"DuoFern stick initialization failed after {INIT_RETRY_COUNT} attempts"
        )

    async def _send_and_wait(
        self, frame: bytearray, timeout: float = ACK_TIMEOUT
    ) -> bytearray | None:
        """Send a frame and wait for ANY response (used only during init).

        During init, we use synchronous request/response — not the ACK-gated
        queue. This mirrors the blocking read in DUOFERNSTICK_DoInit.

        From 10_DUOFERNSTICK.pm:
          # Dispatch data in the buffer before the proper answer.
          (partial frames are accumulated and dispatched when complete)
        """
        if self._serial_protocol is None:
            return None

        response_future: asyncio.Future[bytearray] = (
            asyncio.get_running_loop().create_future()
        )
        self._serial_protocol.set_init_response_future(response_future)

        self._write_frame(frame)

        try:
            return await asyncio.wait_for(response_future, timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for response to %s", frame_to_hex(frame))
            return None
        finally:
            self._serial_protocol.set_init_response_future(None)

    # ------------------------------------------------------------------
    # Internal: ACK-gated send queue
    # ------------------------------------------------------------------

    async def _process_send_queue(self) -> None:
        """Process the command send queue — one command in-flight at a time.

        From 10_DUOFERNSTICK.pm:
          DUOFERNSTICK_HandleWriteQueue / DUOFERNSTICK_AddSendQueue:
            cmdEx tracks in-flight count (0 or 1).
            On ACK receipt, cmdEx decrements, next command is popped.
            5-second timeout triggers HandleWriteQueue regardless (safety).

        We mirror this: send one frame, wait for ACK (or timeout),
        then send the next.
        """
        while not self._closing:
            try:
                frame = await self._send_queue.get()
            except asyncio.CancelledError:
                return

            self._ack_event.clear()
            self._cmd_in_flight = True

            self._write_frame(frame)
            _LOGGER.debug("Command sent: %s", frame_to_hex(frame))

            # Wait for ACK (0x81...) with timeout.
            # From 10_DUOFERNSTICK.pm: timeout = 3s default, or RA_Timeout attr.
            # We use ACK_TIMEOUT (5s) as a safe margin.
            try:
                await asyncio.wait_for(self._ack_event.wait(), timeout=ACK_TIMEOUT)
                _LOGGER.debug("ACK received for command")
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "ACK timeout for command %s, proceeding",
                    frame_to_hex(frame),
                )

            self._cmd_in_flight = False
            self._send_queue.task_done()

    # ------------------------------------------------------------------
    # Internal: Frame I/O
    # ------------------------------------------------------------------

    def _write_frame(self, frame: bytearray) -> None:
        """Write a raw frame to the serial transport."""
        if self._transport is None:
            _LOGGER.error("Cannot write: transport is None")
            return
        _LOGGER.debug("TX: %s", frame_to_hex(frame))
        self._transport.write(bytes(frame))

    def _on_frame_received(self, frame: bytearray) -> None:
        """Handle a complete 22-byte frame from the serial protocol.

        Mirrors DUOFERNSTICK_Parse from 10_DUOFERNSTICK.pm:
          1. If NOT an ACK → send ACK back immediately
          2. If IS an ACK  → signal the send queue (release next command)
          3. If message should be dispatched → call message callback
             (ACKs and broadcast acks 0FFF11... are NOT dispatched)
        """
        hex_str = frame_to_hex(frame)
        _LOGGER.debug("RX: %s", hex_str)

        is_ack = DuoFernDecoder.is_ack(frame)

        # Step 1: Send ACK for every non-ACK message
        if not is_ack:
            self._write_frame(DuoFernEncoder.build_ack())

        # Step 2: Release send queue on ACK
        if is_ack:
            self._ack_event.set()
            # Dispatch CC/AA/BB to coordinator so _handle_cmd_ack,
            # _handle_missing_ack, _handle_unknown_ack actually run.
            # Previously all 0x81 frames were silently dropped here.
            if DuoFernDecoder.should_dispatch_ack(frame):
                try:
                    self._message_callback(frame)
                except Exception:
                    _LOGGER.exception("Error in message callback for %s", hex_str)
            return  # ACKs never go through the normal dispatch path below

        # Step 3: Dispatch to coordinator (excludes broadcast ack 0FFF11...)
        if DuoFernDecoder.should_dispatch(frame):
            try:
                self._message_callback(frame)
            except Exception:
                _LOGGER.exception("Error in message callback for %s", hex_str)


class DuoFernSerialProtocol(asyncio.Protocol):
    """asyncio.Protocol that accumulates bytes into complete frames.

    Mirrors DUOFERNSTICK_Read from 10_DUOFERNSTICK.pm:
      - Bytes arrive in arbitrary-sized chunks from the OS
      - Accumulated in a buffer (PARTIAL in FHEM)
      - Complete frames are extracted and dispatched
      - Partial trailing data is flushed after FLUSH_BUFFER_TIMEOUT (safety)

    Frame sizes are variable, looked up by first byte:
      Default:        22 bytes (FRAME_SIZE_BYTES)
      Pair response:  38 bytes (0x06, 2020+ protocol)

    From 10_DUOFERNSTICK.pm:
      $hash->{PARTIAL} = $duodata; # for recursive calls
    """

    # Map first frame byte to expected total frame length.
    # Bytes not listed fall back to FRAME_SIZE_BYTES (22).
    _FRAME_SIZES: dict[int, int] = {
        0x06: 38,  # pair response — 2020+ devices use 38-byte frames
    }

    def __init__(
        self,
        frame_callback: Callable[[bytearray], None],
    ) -> None:
        """Initialize the serial protocol handler."""
        self._frame_callback = frame_callback
        self._buffer = bytearray()
        self._flush_handle: asyncio.TimerHandle | None = None
        self._init_response_future: asyncio.Future[bytearray] | None = None

    def set_init_response_future(
        self, future: asyncio.Future[bytearray] | None
    ) -> None:
        """Set a future for init sequence response capture."""
        self._init_response_future = future

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Called when serial connection is established."""
        _LOGGER.debug("Serial connection established")

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when serial connection is lost."""
        if exc:
            _LOGGER.error("Serial connection lost: %s", exc)
        else:
            _LOGGER.debug("Serial connection closed")

    def data_received(self, data: bytes) -> None:
        """Called when data arrives from the serial port.

        Accumulates bytes and extracts complete frames. Frame size is determined
        by the first byte via _FRAME_SIZES (default FRAME_SIZE_BYTES = 22).

        From 10_DUOFERNSTICK.pm DUOFERNSTICK_Read:
          $hash->{PARTIAL} = $mduodata; # for recursive calls
        """
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

        self._buffer.extend(data)

        # Extract all complete frames — size determined by first byte.
        while True:
            if not self._buffer:
                break
            expected = self._FRAME_SIZES.get(self._buffer[0], FRAME_SIZE_BYTES)
            if len(self._buffer) < expected:
                break
            frame = bytearray(self._buffer[:expected])
            del self._buffer[:expected]

            if self._init_response_future and not self._init_response_future.done():
                self._init_response_future.set_result(frame)
            else:
                self._frame_callback(frame)

        if len(self._buffer) > 0:
            loop = asyncio.get_running_loop()
            self._flush_handle = loop.call_later(
                FLUSH_BUFFER_TIMEOUT, self._flush_buffer
            )

    def _flush_buffer(self) -> None:
        """Discard partial data after timeout — safety net for protocol errors.

        From 10_DUOFERNSTICK.pm: partial frames in PARTIAL are discarded
        when a new valid frame starts (implicit by overwrite).
        """
        if self._buffer:
            _LOGGER.debug(
                "Flushing %d partial bytes: %s",
                len(self._buffer),
                self._buffer.hex(),
            )
            self._buffer.clear()
