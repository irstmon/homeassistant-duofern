"""The integration in a Home Assistant test instance, with real frames.

The stick is replaced by a fake (see common.py). Frames marked "real" were
recorded from actual devices (issue reports and the maintainer's logs).
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from unittest.mock import patch

from custom_components.duofern import coordinator as coordinator_module
from custom_components.duofern.const import (
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)

from .common import (
    ALL_DEVICES,
    FakeStick,
    enable_all_entities,
    entity_id,
    fake_stick,
    feed,
    make_entry,
    setup_entry,
    stick_ack,
    unload_entry,
)

# Real frames
UMWELT_WEATHER = "0F011322021301D44E82BC30190324691FC8FFFFFF01"  # 531 lx
ROLLOTRON_STATUS = "0FFF0F210D0814800000451514000061D753FFFFFF01"  # position 79
ROHRMOTOR_23 = "0FFF0F23090002035032146433000342283E6F1A2B01"
ROHRMOTOR_26 = "0FFF0F26002500000000000033000342283EFFFFFF01"  # must be ignored
WANDTASTER_28 = "0FFF0F28341896969600000004002674304EFFFFFF01"  # unknown format
SWITCH_46044B = "0FFF0F2200000001753000E430001146044B6F5C7E01"
UNIVERSAL_432FF1 = "0FFF0F220708010107088080300007432FF16F5C7E01"

REAL_DEVICES = ["691FC8", "74304E", "61D753", "42283E"]
DEVICES = [
    d for d in ALL_DEVICES if d[:2] not in ("69", "74", "61", "42")
] + REAL_DEVICES

# Devices of the startup log of 2026-11-15: 42D4BC no longer exists.
LOG_DEVICES = ["42D4BC", "46044B", "432FF1", "65A1B2", "AB0A60", "A04E69", "46087F"]
ALL_AVAILABLE = {
    "42D4BC": True,
    "432FF101": True,
    "432FF102": True,
    "46044B": True,
    "46087F": True,
    "65A1B200": True,
    "65A1B201": True,
    "A04E69": True,
    "AB0A60": True,
}
SILENT = {
    **ALL_AVAILABLE,
    "42D4BC": False,
    "432FF101": False,
    "432FF102": False,
    "46087F": False,
    "65A1B201": False,
}


async def _wait_until(condition, timeout: float = 10.0) -> None:
    """Wait for a condition instead of sleeping a fixed time (slow CI runners)."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.02)


def _polled(stick: FakeStick) -> list[str]:
    return sorted(f[36:42] for f in stick.sent if f.startswith("0DFF0F40"))


def _available(coordinator) -> dict[str, bool]:
    return {k: s.available for k, s in sorted(coordinator.data.devices.items())}


def _state(hass: HomeAssistant, domain: str, unique_id: str):
    return hass.states.get(entity_id(hass, domain, unique_id))


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


async def test_setup_all_device_types(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """All device types set up: every platform loads, nothing is logged as error."""
    async with fake_stick():
        entry = make_entry(hass, DEVICES)
        with caplog.at_level(logging.WARNING):
            await setup_entry(hass, entry)
        assert entry.state is ConfigEntryState.LOADED

        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert {e.domain for e in entities} == {
            "binary_sensor",
            "button",
            "cover",
            "event",
            "light",
            "number",
            "select",
            "sensor",
            "switch",
            "text",
        }
        assert len(entities) > 400
        assert len(devices) > 35
        without_state = [
            e.entity_id
            for e in entities
            if e.disabled_by is None and hass.states.get(e.entity_id) is None
        ]
        assert not without_state
        assert len({e.unique_id for e in entities}) == len(entities)

        problems = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and r.name.startswith("custom_components.duofern")
        ]
        assert not problems, problems[:5]
        await unload_entry(hass, entry)


async def test_setup_failure_closes_the_port(hass: HomeAssistant) -> None:
    """A failed stick init ends in SETUP_RETRY and the port is closed again."""

    class FailingStick(FakeStick):
        async def connect(self) -> None:
            raise ConnectionError("init failed")

    async with fake_stick(FailingStick):
        entry = make_entry(hass, ["40A1B2"])
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert FakeStick.instances[0].closed


async def test_startup_does_not_wait_for_the_status_poll(hass: HomeAssistant) -> None:
    """The startup poll runs in the background; setup returns at once."""
    async with fake_stick(startup_status_timeout=5.0):
        entry = make_entry(hass, ["40A1B2"])
        started = time.monotonic()
        await setup_entry(hass, entry)  # includes async_block_till_done
        assert time.monotonic() - started < 2.0
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Real frames -> entity states
# ---------------------------------------------------------------------------


async def test_real_frames_update_entities(hass: HomeAssistant) -> None:
    # A missing ACK starts the status poll loop; keep it short.
    async with fake_stick(status_timeout=0.01):
        entry = make_entry(hass, DEVICES)
        coordinator = await setup_entry(hass, entry)

        # Umweltsensor: an actor status frame must not wipe the weather values
        feed(coordinator, UMWELT_WEATHER)
        await hass.async_block_till_done()
        brightness = _state(hass, "sensor", "duofern_691FC800_brightness")
        assert float(brightness.state) == 531
        feed(coordinator, "0FFF0F230900020350321464330003691FC86F1A2B01")
        await hass.async_block_till_done()
        assert float(_state(hass, "sensor", "duofern_691FC800_brightness").state) == 531
        assert _state(hass, "cover", "duofern_691FC801").state in ("open", "closed")

        # RolloTron
        feed(coordinator, ROLLOTRON_STATUS)
        await hass.async_block_till_done()
        assert (
            _state(hass, "cover", "duofern_61D753").attributes["current_position"] == 79
        )

        # Rohrmotor-Aktor: format 23 is decoded, format 26 is ignored
        feed(coordinator, ROHRMOTOR_23)
        await hass.async_block_till_done()
        before = _state(hass, "cover", "duofern_42283E")
        feed(coordinator, ROHRMOTOR_26)
        await hass.async_block_till_done()
        after = _state(hass, "cover", "duofern_42283E")
        assert (after.state, after.attributes) == (before.state, before.attributes)

        # Wandtaster: an unknown status format keeps the relay state
        relay_status = "0FFF0F22000000000000006400000074304EFFFFFF01"
        feed(coordinator, relay_status)
        await hass.async_block_till_done()
        relay = _state(hass, "switch", "duofern_74304E01").state
        assert relay in ("on", "off")
        feed(coordinator, WANDTASTER_28)
        await hass.async_block_till_done()
        assert _state(hass, "switch", "duofern_74304E01").state == relay

        # missing ACK -> unavailable, next status frame -> available again;
        # the "00" sub-channel (buttons) stays available
        feed(coordinator, stick_ack("810108AA", "74304E"))
        await hass.async_block_till_done()
        assert _state(hass, "switch", "duofern_74304E01").state == "unavailable"
        assert coordinator.data.devices["74304E00"].available
        feed(coordinator, relay_status)
        await hass.async_block_till_done()
        assert _state(hass, "switch", "duofern_74304E01").state == relay

        await unload_entry(hass, entry)


async def test_universalaktor_channel_two_uses_channel_byte(
    hass: HomeAssistant,
) -> None:
    """Commands for channel 02 of the Universalaktor carry 0D02 (FHEM: cc = chanNo)."""
    async with fake_stick():
        entry = make_entry(hass, ["43A1B2", "48A1B2"])
        await setup_entry(hass, entry)
        await enable_all_entities(hass, entry)
        stick = FakeStick.instances[-1]

        async def call(domain: str, service: str, unique_id: str, **data) -> str:
            stick.sent.clear()
            await hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id(hass, domain, unique_id), **data},
                blocking=True,
            )
            assert len(stick.sent) == 1
            return stick.sent[0]

        assert (await call("switch", "turn_on", "duofern_43A1B201"))[:4] == "0D01"
        assert (await call("switch", "turn_on", "duofern_43A1B202"))[:4] == "0D02"
        assert (
            await call("switch", "turn_on", "duofern_43A1B202_sunAutomatic_auto")
        ) == "0D02080100FD0000000000000000006F1A2B43A1B200"
        assert (
            await call(
                "number", "set_value", "duofern_43A1B202_stairwellTime", value=10
            )
        )[:4] == "0D02"
        # brightness 1 of 255 must not become level 0
        assert (await call("light", "turn_on", "duofern_48A1B2", brightness=1))[
            :12
        ] == "0D0107070001"
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def test_reload_pair_service_reconfigure_unload(hass: HomeAssistant) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        first = await setup_entry(hass, entry)
        assert hass.services.has_service(DOMAIN, "pair_device_by_code")

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        assert coordinator is not first
        assert FakeStick.instances[0].closed
        stick = FakeStick.instances[-1]

        # pair by code: the stick reports a missing ACK -> translated error
        async def answer_missing_ack(frame: bytearray) -> None:
            if frame[0] == 0x0D and frame[2] == 0x06:
                hass.loop.call_soon(feed, coordinator, stick_ack("810108AA", "40AB12"))

        stick.send_command = answer_missing_ack  # type: ignore[method-assign]
        with (
            patch.object(coordinator_module, "REMOTE_PAIR_TIMEOUT", 0.5),
            pytest.raises(HomeAssistantError) as error,
        ):
            await hass.services.async_call(
                DOMAIN,
                "pair_device_by_code",
                {"device_code": "40AB12"},
                blocking=True,
                return_response=True,
            )
        assert error.value.translation_key in ("pair_aa", "pair_timeout")

        # pair by code: the device answers -> added, one reload by the listener
        async def answer_paired(frame: bytearray) -> None:
            if frame[0] == 0x0D and frame[2] == 0x06:
                response = bytearray(22)
                response[0], response[1] = 0x06, 0x02
                response[15:18] = bytes.fromhex("40AB12")
                hass.loop.call_soon(coordinator._on_message, response)

        stick.send_command = answer_paired  # type: ignore[method-assign]
        instances = len(FakeStick.instances)
        with patch.object(coordinator_module, "REMOTE_PAIR_TIMEOUT", 0.5):
            result = await hass.services.async_call(
                DOMAIN,
                "pair_device_by_code",
                {"device_code": "40ab12"},
                blocking=True,
                return_response=True,
            )
        assert result == {"device_code": "40AB12", "result": "paired"}
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2", "40AB12"]
        assert len(FakeStick.instances) == instances + 1

        # reconfigure with a new port: exactly one reload
        instances = len(FakeStick.instances)
        result = await entry.start_reconfigure_flow(hass)
        with patch(
            "custom_components.duofern.config_flow.check_serial_connection",
            return_value=True,
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_SERIAL_PORT: "/dev/ttyUSB7"}
            )
        await hass.async_block_till_done()
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_SERIAL_PORT] == "/dev/ttyUSB7"
        assert len(FakeStick.instances) == instances + 1

        await unload_entry(hass, entry)
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert FakeStick.instances[-1].closed


async def test_pair_service_without_loaded_entry(hass: HomeAssistant) -> None:
    """The action stays registered after an unload and then raises."""
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        await setup_entry(hass, entry)
        await unload_entry(hass, entry)
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                DOMAIN,
                "pair_device_by_code",
                {"device_code": "40AB12"},
                blocking=True,
                return_response=True,
            )


async def test_write_config_needs_all_register_pages(hass: HomeAssistant) -> None:
    """Umweltsensor: writing is refused until all 8 pages were read from the device."""
    async with fake_stick():
        entry = make_entry(hass, ["69A1B2"])
        await setup_entry(hass, entry)
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                "button",
                "press",
                {
                    "entity_id": entity_id(
                        hass, "button", "duofern_69A1B200_write_config"
                    )
                },
                blocking=True,
            )
        assert error.value.translation_key == "write_config_incomplete"
        assert error.value.translation_placeholders == {"received": "0"}
        assert FakeStick.instances[-1].sent == []
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Startup status poll, unavailable devices, persistence
# ---------------------------------------------------------------------------


async def test_startup_poll_skips_devices_that_already_answered(
    hass: HomeAssistant,
) -> None:
    class AnswersDuringConnect(FakeStick):
        async def connect(self) -> None:
            self.message_callback(bytearray.fromhex(ROLLOTRON_STATUS))

    async with fake_stick(AnswersDuringConnect, startup_status_timeout=0.2):
        entry = make_entry(hass, ["61D753", "40A1B2", "A0A1B2", "ABA1B2"])
        coordinator = await setup_entry(hass, entry)
        assert coordinator._startup_status_pending == {"40A1B2"}
        stick = FakeStick.instances[-1]
        await _wait_until(lambda: _polled(stick))
        # not the device that answered, not remotes/sensors
        assert _polled(stick) == ["40A1B2"]
        await unload_entry(hass, entry)


async def test_silent_devices_become_unavailable_and_are_remembered(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    """Two unanswered polls -> unavailable; the list survives a restart."""
    async with fake_stick(startup_status_timeout=0.3):
        entry = make_entry(hass, LOG_DEVICES)
        key = f"{DOMAIN}.{entry.entry_id}.missing_status"

        # start 1: nothing stored, everything starts available
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        assert _available(coordinator) == ALL_AVAILABLE
        assert key not in hass_storage
        feed(coordinator, SWITCH_46044B)

        silent_codes = ["42D4BC", "432FF1", "46087F", "65A1B2"]
        await _wait_until(lambda: len(_polled(stick)) == 4)
        assert _polled(stick) == silent_codes
        assert _available(coordinator) == ALL_AVAILABLE  # still available after poll 1
        stick.sent.clear()
        await _wait_until(lambda: len(_polled(stick)) == 4)
        assert _polled(stick) == silent_codes  # poll 2
        assert _available(coordinator) == ALL_AVAILABLE
        stick.sent.clear()
        await _wait_until(lambda: not coordinator.data.devices["42D4BC"].available)
        await hass.async_block_till_done()
        assert _available(coordinator) == SILENT
        assert _state(hass, "cover", "duofern_42D4BC").state == "unavailable"
        assert _state(hass, "switch", "duofern_46044B").state != "unavailable"
        # "Request status" stays usable on an unavailable device
        assert (
            _state(hass, "button", "duofern_42D4BC_get_status").state != "unavailable"
        )
        assert stick.sent == []  # no further polls after the startup phase

        await _wait_until(lambda: key in hass_storage)  # delayed save
        assert hass_storage[key]["data"] == {"devices": silent_codes}
        await unload_entry(hass, entry)

        # start 2: exactly the stored devices start unavailable
        coordinator = await setup_entry(hass, entry)
        assert _available(coordinator) == SILENT
        assert _state(hass, "cover", "duofern_42D4BC").state == "unavailable"
        # two devices answer: available again and removed from the file
        feed(coordinator, UNIVERSAL_432FF1)
        feed(coordinator, "0FFF0F22000000010708008030001746087F6F5C7E01")
        feed(coordinator, SWITCH_46044B)
        await hass.async_block_till_done()
        assert coordinator.data.devices["432FF101"].available
        assert coordinator.data.devices["432FF102"].available
        assert _state(hass, "switch", "duofern_46087F").state != "unavailable"
        await _wait_until(
            lambda: hass_storage[key]["data"] == {"devices": ["42D4BC", "65A1B2"]}
        )

        # a reload during the startup phase leaves the file as it is
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass_storage[key]["data"] == {"devices": ["42D4BC", "65A1B2"]}
        assert _available(entry.runtime_data) == {
            **ALL_AVAILABLE,
            "42D4BC": False,
            "65A1B201": False,
        }
        await unload_entry(hass, entry)

        # start 3: codes of unpaired devices and garbage in the file are ignored
        hass_storage[key]["data"] = {"devices": ["42D4BC", "999999", "zz", 5, "46044b"]}
        coordinator = await setup_entry(hass, entry)
        assert _available(coordinator) == {
            **ALL_AVAILABLE,
            "42D4BC": False,
            "46044B": False,
        }
        await unload_entry(hass, entry)

        # removing the entry deletes the file
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        assert key not in hass_storage


async def test_broken_store_does_not_block_setup(
    hass: HomeAssistant, hass_storage: dict
) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        hass_storage[f"{DOMAIN}.{entry.entry_id}.missing_status"] = {
            "version": 1,
            "data": ["not", "a", "dict"],
        }
        coordinator = await setup_entry(hass, entry)
        assert coordinator.data.devices["40A1B2"].available
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Umweltsensor configuration
# ---------------------------------------------------------------------------


def _config_frames(code: str, pages: list[str]) -> list[str]:
    return [f"0FFF1B2{n + 1}{pages[n]}00{code}FFFFFF01" for n in range(8)]


async def test_sun_trigger_temperature_link(hass: HomeAssistant) -> None:
    """Link off clears flag and temperature in the register, as FHEM writes it."""
    code = "69A1B2"
    async with fake_stick():
        entry = make_entry(hass, [code])
        coordinator = await setup_entry(hass, entry)
        device_state = coordinator.data.devices[code + "00"]

        async def call(domain: str, service: str, suffix: str, **data) -> None:
            target = entity_id(hass, domain, f"duofern_{code}00_{suffix}")
            await hass.services.async_call(
                domain, service, {"entity_id": target, **data}, blocking=True
            )
            await hass.async_block_till_done()

        def word() -> str:
            page, byte = coordinator._SUN_POS[0]
            return f"{coordinator._get_reg_word32(device_state, page, byte):08X}"

        def temperature() -> float:
            return float(
                _state(hass, "number", f"duofern_{code}00_sun_grenzwert_temp").state
            )

        def load(slot_one: str) -> None:
            pages = ["00" * 10] * 8
            pages[3] = slot_one + "00" * 6
            for frame in _config_frames(code, pages):
                feed(coordinator, frame)

        # slot 1 = 20 klx : 5 min : 10 min : 20 degC as FHEM encodes it
        load("29213CC0")
        await hass.async_block_till_done()
        assert word() == "29213CC0" and temperature() == 20

        await call("switch", "turn_off", "sun_temperatur_verknuepfen")
        assert word() == "29213000"  # FHEM: triggerSun 20:5:10
        assert temperature() == 20  # remembered

        await call("number", "set_value", "sun_grenzwert_temp", value=15)
        assert word() == "29213000" and temperature() == 15  # register untouched

        await call("switch", "turn_on", "sun_temperatur_verknuepfen")
        assert word() == f"{0x29213000 | (20 << 7) | 0x40:08X}"  # 20:5:10:15

        await call("number", "set_value", "sun_grenzwert_temp", value=26)
        assert word() == f"{0x29213000 | (31 << 7) | 0x40:08X}"

        # register written by versions before 2.4.0: link off, value still present
        device_state.sun_temp_memory.clear()
        load("29213C80")
        await hass.async_block_till_done()
        assert temperature() == 20
        await call("switch", "turn_on", "sun_temperatur_verknuepfen")
        assert word() == "29213CC0"

        # nothing remembered: switching on writes 0 degC
        device_state.sun_temp_memory.clear()
        load("29213000")
        await hass.async_block_till_done()
        assert temperature() == 0
        await call("switch", "turn_on", "sun_temperatur_verknuepfen")
        assert word() == f"{0x29213000 | (5 << 7) | 0x40:08X}"

        # the low 6 bits (sun direction / height) are not touched
        load("29213CEB")
        await call("switch", "turn_off", "sun_temperatur_verknuepfen")
        assert word() == "2921302B"

        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Every entity accepts its service calls
# ---------------------------------------------------------------------------


async def test_every_entity_handles_its_services(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Call each service of each entity once; nothing may raise unexpectedly.

    The exact frames are checked in test_golden_frames.py. This test makes
    sure no entity is left that fails on an ordinary service call.
    """
    async with fake_stick():
        entry = make_entry(hass, DEVICES)
        await setup_entry(hass, entry)
        await enable_all_entities(hass, entry)
        coordinator = entry.runtime_data
        stick = FakeStick.instances[-1]
        for frame in (UMWELT_WEATHER, ROLLOTRON_STATUS, ROHRMOTOR_23):
            feed(coordinator, frame)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        calls = 0
        refused = 0

        async def call(domain: str, service: str, target: str, **data) -> None:
            nonlocal calls, refused
            calls += 1
            try:
                await hass.services.async_call(
                    domain, service, {"entity_id": target, **data}, blocking=True
                )
            except HomeAssistantError:
                refused += 1  # e.g. "Write Config" before the registers were read

        with patch.object(coordinator_module, "REMOTE_PAIR_TIMEOUT", 0.01):
            for reg_entry in er.async_entries_for_config_entry(
                registry, entry.entry_id
            ):
                target = reg_entry.entity_id
                state = hass.states.get(target)
                assert state is not None, target
                attrs = state.attributes
                if reg_entry.domain == "switch":
                    await call("switch", "turn_on", target)
                    await call("switch", "turn_off", target)
                elif reg_entry.domain == "button":
                    await call("button", "press", target)
                elif reg_entry.domain == "number":
                    await call("number", "set_value", target, value=attrs["min"])
                    await call("number", "set_value", target, value=attrs["max"])
                elif reg_entry.domain == "select":
                    for option in attrs["options"]:
                        await call("select", "select_option", target, option=option)
                elif reg_entry.domain == "cover":
                    for service in (
                        "open_cover",
                        "close_cover",
                        "stop_cover",
                        "toggle",
                    ):
                        await call("cover", service, target)
                    await call("cover", "set_cover_position", target, position=40)
                    if attrs.get("supported_features", 0) & 128:
                        await call(
                            "cover", "set_cover_tilt_position", target, tilt_position=30
                        )
                        await call("cover", "open_cover_tilt", target)
                        await call("cover", "close_cover_tilt", target)
                elif reg_entry.domain == "light":
                    await call("light", "turn_on", target)
                    await call("light", "turn_on", target, brightness=128)
                    await call("light", "turn_off", target)
                    await call("light", "toggle", target)
                elif reg_entry.domain == "text":
                    await call("text", "set_value", target, value="40AB12")
                    await call("text", "set_value", target, value="")
            await hass.async_block_till_done()
            await asyncio.sleep(0.05)

        assert calls > 800
        assert refused < 20
        assert len(stick.sent) > 500
        assert all(len(f) == 44 for f in stick.sent)
        errors = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.ERROR
            and r.name.startswith("custom_components.duofern")
        ]
        assert not errors, errors[:5]
        await unload_entry(hass, entry)
