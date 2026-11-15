"""Heizkörperantrieb (0xE1): the device-initiated protocol.

The actuator sleeps and only listens right after it has sent a status frame.
Changes are therefore queued and sent as an answer to the next status frame,
with guards around boost on/off (no receive window on the first frame after
a change). The sequences below fix the behaviour that was worked out from
radio captures and confirmed on a real actuator.

Frames: D = status with boost off (real frame of E14A0F), F = the same frame
with the boost bit set.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

import custom_components.duofern as integration
from custom_components.duofern.coordinator import DuoFernCoordinator
from custom_components.duofern.protocol import DuoFernDecoder, DuoFernId

from .common import (
    FakeStick,
    fake_stick,
    feed,
    make_entry,
    setup_entry,
    stick_ack,
    unload_entry,
)

CODE = "E14A0F"
DEVICE = DuoFernId.from_hex(CODE)
D = "0FFF0F29D40917008042642A04140AE14A0F6F5C7E01"
F = "0FFF0F29F00917008042642A04140AE14A0F6F5C7E01"
CC = stick_ack("810003CC", CODE)
AA = stick_ack("810108AA", CODE)
BB = stick_ack("810100BB", CODE)


def _with_force_response(frame: str) -> str:
    raw = bytearray.fromhex(frame)
    raw[12] |= 0x80
    return raw.hex().upper()


D_FORCE = _with_force_response(D)
F_FORCE = _with_force_response(F)

SET_TEMP_21_5 = "0D011D80C600000000000000000000000000E14A0F00"
BOOST_ON = "0D011D80000000004E000003000000000000E14A0F00"
BOOST_OFF = "0D011D800000000000000002000000000000E14A0F00"
MANUAL_ON = "0D011D800005000000000000000000000000E14A0F00"
EMPTY_REPLY = "0D011D800000000000000000000000000000E14A0F00"

# Climate entities need Home Assistant 2026.11 (see common.CLIMATE_TYPES); the
# protocol is driven on the coordinator, so the climate platform is left out.
PLATFORMS_WITHOUT_CLIMATE = [p for p in integration.PLATFORMS if p != Platform.CLIMATE]


@asynccontextmanager
async def _hsa_environment() -> AsyncGenerator[None]:
    with patch.object(integration, "PLATFORMS", PLATFORMS_WITHOUT_CLIMATE):
        async with fake_stick():
            yield


class _Scenario:
    def __init__(self, hass: HomeAssistant, coordinator: DuoFernCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.stick = FakeStick.instances[-1]

    @property
    def state(self):
        return self.coordinator.data.devices[CODE]

    async def step(self, *, frame: str | None = None, call: Any = None) -> list[str]:
        """Run one step and return the frames sent during it."""
        self.stick.sent.clear()
        if call is not None:
            await call
        if frame is not None:
            feed(self.coordinator, frame)
        await self.hass.async_block_till_done()
        return list(self.stick.sent)

    def snapshot(self) -> tuple:
        state = self.state
        return (
            state.status.readings.get("boostActive"),
            state.status.readings.get("desired-temp"),
            sorted(state.hsa_pending),
            state.boost_ha_on_pending_f0,
            state.boost_off_cooldown,
            state.boost_deactivating,
        )


async def _start(hass: HomeAssistant) -> tuple[_Scenario, Any]:
    entry = make_entry(hass, [CODE])
    coordinator = await setup_entry(hass, entry)
    return _Scenario(hass, coordinator), entry


def test_force_response_bit_is_decoded() -> None:
    assert (
        DuoFernDecoder.parse_status(bytearray.fromhex(D)).readings["forceResponse"] == 0
    )
    assert (
        DuoFernDecoder.parse_status(bytearray.fromhex(D_FORCE)).readings[
            "forceResponse"
        ]
        == 1
    )


async def test_setpoint_and_boost_sequence(hass: HomeAssistant) -> None:
    async with _hsa_environment():
        s, entry = await _start(hass)
        c = s.coordinator

        # status frame, nothing pending: nothing is sent
        assert await s.step(frame=D) == []
        assert s.snapshot() == ("off", 14.0, [], False, False, False)

        # a new setpoint is queued and sent with the next status frame
        assert await s.step(call=c.async_set_desired_temp(DEVICE, 21.5)) == []
        assert s.snapshot() == ("off", 21.5, ["desired-temp"], False, False, False)
        assert await s.step(frame=D) == [SET_TEMP_21_5]
        assert s.snapshot() == ("off", 21.5, [], False, False, False)
        assert await s.step(frame=CC) == []

        # boost on: queued, sent with the next status frame; after the CC the
        # first boost frame (F) has no receive window (guard A)
        assert await s.step(call=c.async_set_boost(DEVICE, True)) == []
        assert s.snapshot()[2] == ["boostActive", "boostDuration"]
        assert await s.step(frame=D) == [BOOST_ON]
        assert await s.step(frame=CC) == []
        assert s.snapshot() == ("on", 14.0, [], True, False, False)
        assert await s.step(frame=F) == []
        assert s.snapshot() == ("on", 14.0, [], False, False, False)

        # boost off while boosting: sent with the next F frame, repeated as
        # long as the actuator still reports boost
        assert await s.step(call=c.async_set_boost(DEVICE, False)) == []
        assert await s.step(frame=F) == [BOOST_OFF]
        assert await s.step(frame=CC) == []
        assert s.snapshot() == ("off", 14.0, [], False, True, True)
        assert await s.step(frame=F) == [BOOST_OFF]
        assert s.snapshot()[0] == "off"  # the UI keeps showing "off"
        assert await s.step(frame=CC) == []

        # first status frame after boost ended: no receive window (guard B)
        assert await s.step(frame=D) == []
        assert s.snapshot() == ("off", 14.0, [], False, False, False)

        # boost on again: sent on the second status frame
        assert await s.step(call=c.async_set_boost(DEVICE, True)) == []
        assert await s.step(frame=D) == [BOOST_ON]

        # the stick reports BB (not delivered): the change is queued again
        # and sent with the next status frame
        await s.step(frame=BB)
        assert s.snapshot()[2] == ["boostActive", "boostDuration"]
        await s.step(frame=AA)
        assert await s.step(frame=D) == [BOOST_ON]

        # frames that carry no status must not disturb the state
        before = s.snapshot()
        assert await s.step(frame="0FFF0F2A08F2550000000000000000E14A0F6F1A2B01") == []
        assert await s.step(frame="0FFF0F2DD40917008042642A04140AE14A0F6F5C7E01") == []
        assert s.snapshot() == before

        # another setting
        assert (
            await s.step(call=c.async_set_automation(DEVICE, "manualMode", True)) == []
        )
        assert s.snapshot()[2] == ["manualMode"]
        assert await s.step(frame=D) == [MANUAL_ON]

        await unload_entry(hass, entry)


async def test_force_response_is_answered(hass: HomeAssistant) -> None:
    """The actuator asks for an answer: it gets one even when nothing is pending."""
    async with _hsa_environment():
        s, entry = await _start(hass)
        c = s.coordinator

        assert await s.step(frame=D) == []
        assert await s.step(frame=D_FORCE) == [EMPTY_REPLY]
        assert s.state.hsa_force_reply_sent is True
        assert await s.step(frame=CC) == []
        assert s.state.hsa_force_reply_sent is False

        # BB on such an answer: the stick stops forwarding until the next
        # TX, so one more frame is sent to release it
        assert await s.step(frame=D_FORCE) == [EMPTY_REPLY]
        assert await s.step(frame=BB) == [EMPTY_REPLY]
        assert s.state.hsa_force_reply_sent is False
        assert await s.step(frame=AA) == []

        # with something pending the pending values are sent
        await s.step(call=c.async_set_desired_temp(DEVICE, 21.5))
        assert await s.step(frame=D_FORCE) == [SET_TEMP_21_5]
        assert await s.step(frame=CC) == []

        # the boost guards stay in force
        await s.step(call=c.async_set_boost(DEVICE, True))
        assert await s.step(frame=D_FORCE) == [BOOST_ON]
        assert await s.step(frame=CC) == []
        assert await s.step(frame=F_FORCE) == []  # guard A
        assert await s.step(frame=F_FORCE) == []  # boosting, no off pending

        await unload_entry(hass, entry)


async def test_boost_and_setpoint_pending_go_out_in_one_frame(
    hass: HomeAssistant,
) -> None:
    """A setpoint change queued together with boost on rides on the boost frame."""
    async with _hsa_environment():
        s, entry = await _start(hass)
        c = s.coordinator
        assert await s.step(frame=D) == []
        await s.step(call=c.async_set_desired_temp(DEVICE, 21.5))
        await s.step(call=c.async_set_boost(DEVICE, True))
        assert s.snapshot()[2] == ["boostActive", "boostDuration", "desired-temp"]

        sent = await s.step(frame=D)
        assert len(sent) == 1
        frame = bytes.fromhex(sent[0])
        assert frame[:4] == bytes.fromhex("0D011D80")
        assert frame[11] == 0x03  # boost on, as in BOOST_ON
        assert frame[18:21] == bytes.fromhex(CODE)
        assert sent[0] != BOOST_ON  # carries the setpoint in addition
        assert s.snapshot()[2] == []  # everything was sent
        await unload_entry(hass, entry)
