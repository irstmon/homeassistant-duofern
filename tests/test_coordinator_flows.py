"""Pairing windows, sensor messages, device triggers, cleanup and edge paths.

Everything runs in a Home Assistant test instance with the fake stick.
"""

from __future__ import annotations

import inspect
import logging
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_get_device_automations,
)

from custom_components.duofern.const import (
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from custom_components.duofern.coordinator import DuoFernCoordinator
from custom_components.duofern.protocol import DuoFernId

from .common import (
    SYSTEM_CODE,
    FakeStick,
    entity_id,
    fake_stick,
    feed,
    make_entry,
    setup_entry,
    unload_entry,
)

UMWELT = "69A1B2"


def _pair_response(kind: int, code: str) -> str:
    """0602 (paired) / 0603 (unpaired) stick message; device code at bytes 15-17."""
    frame = bytearray(22)
    frame[0], frame[1] = 0x06, kind
    frame[15:18] = bytes.fromhex(code)
    return frame.hex().upper()


def _sensor_message(message_id: str, channel: int, code: str) -> str:
    """sensorMsg frame: 0FFF + id, channel byte repeated, device code at 15-17."""
    frame = bytearray(22)
    frame[0], frame[1] = 0x0F, 0xFF
    frame[2:4] = bytes.fromhex(message_id)
    frame[4:15] = bytes([channel] * 11)
    frame[15:18] = bytes.fromhex(code)
    frame[18:21] = b"\xff\xff\xff"
    frame[21] = 0x01
    return frame.hex().upper()


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str):
    return dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, identifier), entry.entry_id
    )


def _state(hass: HomeAssistant, domain: str, unique_id: str):
    return hass.states.get(entity_id(hass, domain, unique_id))


# ---------------------------------------------------------------------------
# Pairing and unpairing windows
# ---------------------------------------------------------------------------


async def test_pair_response_only_counts_inside_a_pairing_window(
    hass: HomeAssistant,
) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)

        # no window: a stray 0602 changes nothing
        feed(coordinator, _pair_response(0x02, "46ABCD"))
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2"]
        assert entry.runtime_data is coordinator

        # unpairing window: a 0602 is ignored as well
        await coordinator.async_start_unpairing(duration=30)
        feed(coordinator, _pair_response(0x02, "46ABCD"))
        await coordinator.async_stop_unpairing()
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2"]

        # pairing window: the device is added and the entry reloads
        stick = FakeStick.instances[-1]
        stick.sent.clear()
        await coordinator.async_start_pairing(duration=30)
        assert coordinator.data.pairing_active
        await coordinator.async_start_pairing(duration=30)  # second press: no-op
        await coordinator.async_start_unpairing(duration=30)  # blocked while pairing
        assert len(stick.sent) == 1
        feed(coordinator, _pair_response(0x02, "46ABCD"))
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2", "46ABCD"]
        assert entry.runtime_data is not coordinator
        assert "46ABCD" in entry.runtime_data.data.devices
        await unload_entry(hass, entry)


async def test_unpair_response_only_counts_inside_an_unpairing_window(
    hass: HomeAssistant,
) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2", "46ABCD"])
        coordinator = await setup_entry(hass, entry)

        # no window: a stray 0603 must not remove the device
        feed(coordinator, _pair_response(0x03, "46ABCD"))
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2", "46ABCD"]
        assert entry.runtime_data is coordinator

        # pairing window: a 0603 is ignored
        await coordinator.async_start_pairing(duration=30)
        feed(coordinator, _pair_response(0x03, "46ABCD"))
        await coordinator.async_stop_pairing()
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2", "46ABCD"]

        # unpairing window: the device is removed, registry cleaned, entry reloads
        device_registry = dr.async_get(hass)
        assert _device(hass, entry, "46ABCD")
        await coordinator.async_start_unpairing(duration=30)
        assert coordinator.data.unpairing_active
        feed(coordinator, _pair_response(0x03, "46ABCD"))
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2"]
        assert entry.runtime_data is not coordinator
        assert "46ABCD" not in entry.runtime_data.data.devices
        assert _device(hass, entry, "46ABCD") is None
        registry = er.async_get(hass)
        assert not [
            e
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if "46ABCD" in e.unique_id
        ]
        await unload_entry(hass, entry)


async def test_unpair_of_a_device_that_is_not_in_the_list(hass: HomeAssistant) -> None:
    """A 0603 for an unknown code in the window ends the window without a reload."""
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        await coordinator.async_start_unpairing(duration=30)
        feed(coordinator, _pair_response(0x03, "46ABCD"))
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2"]
        assert entry.runtime_data is coordinator
        assert not coordinator.data.unpairing_active
        await unload_entry(hass, entry)


async def test_pairing_window_counts_down_and_closes(hass: HomeAssistant) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        stick.sent.clear()
        with patch(
            "custom_components.duofern.coordinator.asyncio.sleep", new=AsyncMock()
        ):
            await coordinator.async_start_pairing(duration=3)
            await hass.async_block_till_done()
        assert not coordinator.data.pairing_active
        assert coordinator.data.pairing_remaining == 0
        assert len(stick.sent) == 2  # start pair, stop pair
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Umweltsensor: sensor messages, Grenzwert slots, device triggers
# ---------------------------------------------------------------------------


async def test_umweltsensor_sensor_messages(hass: HomeAssistant) -> None:
    """startSun/endSun with a slot bitmask drive the sensors and the events."""
    async with fake_stick():
        entry = make_entry(hass, [UMWELT, "40A1B2"])
        coordinator = await setup_entry(hass, entry)
        events: list[dict] = []
        slot_events: list[dict] = []
        hass.bus.async_listen("duofern_event", lambda e: events.append(dict(e.data)))
        hass.bus.async_listen(
            "duofern_grenzwert_event", lambda e: slot_events.append(dict(e.data))
        )

        sun_slots = f"duofern_{UMWELT}00_sun_grenzwerte"
        assert _state(hass, "sensor", sun_slots).state == "unknown"

        # startSun for Grenzwert 1 and 3 (bitmask 0b00101)
        feed(coordinator, _sensor_message("0708", 0x05, UMWELT))
        await hass.async_block_till_done()
        assert events[-1]["device_code"] == UMWELT + "00"
        assert events[-1]["event"] == "startSun"
        assert _state(hass, "sensor", sun_slots).state == "1,3"
        assert sorted(int(e["slot"]) for e in slot_events) == [1, 3]

        # endSun for Grenzwert 1
        feed(coordinator, _sensor_message("070A", 0x01, UMWELT))
        await hass.async_block_till_done()
        assert _state(hass, "sensor", sun_slots).state == "3"

        # channel byte 00: slot indeterminate, sensor unchanged, no slot event
        slot_events.clear()
        feed(coordinator, _sensor_message("0708", 0x00, UMWELT))
        await hass.async_block_till_done()
        assert _state(hass, "sensor", sun_slots).state == "3"
        assert slot_events == []

        # an event of another group or another device does not touch it
        feed(coordinator, _sensor_message("070D", 0x02, UMWELT))  # startWind
        await hass.async_block_till_done()
        assert _state(hass, "sensor", sun_slots).state == "3"
        assert (
            _state(hass, "sensor", f"duofern_{UMWELT}00_wind_grenzwerte").state == "2"
        )

        # dawn / dusk event entity carries the Grenzwert list
        feed(coordinator, _sensor_message("0713", 0x06, UMWELT))  # dawn, slots 2+3
        await hass.async_block_till_done()
        dawn_dusk = _state(hass, "event", f"duofern_{UMWELT}00_dawn_dusk_event")
        assert dawn_dusk.attributes["event_type"] == "dawn"
        assert dawn_dusk.attributes["grenzwerte"] == "2,3"
        feed(coordinator, _sensor_message("0709", 0x00, UMWELT))  # dusk, no bitmask
        await hass.async_block_till_done()
        dawn_dusk = _state(hass, "event", f"duofern_{UMWELT}00_dawn_dusk_event")
        assert dawn_dusk.attributes["event_type"] == "dusk"
        assert dawn_dusk.attributes["grenzwerte"] == ""

        await unload_entry(hass, entry)


async def test_umweltsensor_device_triggers(hass: HomeAssistant) -> None:
    """Triggers are offered on the "00" device only and fire for the right slot."""
    async with fake_stick():
        entry = make_entry(hass, [UMWELT])
        coordinator = await setup_entry(hass, entry)
        device_registry = dr.async_get(hass)
        weather = _device(hass, entry, UMWELT + "00")
        actor = _device(hass, entry, UMWELT + "01")
        assert weather and actor

        triggers = await async_get_device_automations(
            hass, DeviceAutomationType.TRIGGER, weather.id
        )
        own = [t for t in triggers if t["domain"] == DOMAIN]
        types = {(t["type"], t["subtype"]) for t in own}
        # sun/wind/temperature: 2 subtypes x 5 slots, dawn/dusk: 1 x 5, rain: 2
        assert len(own) == 3 * 2 * 5 + 2 * 5 + 2
        assert ("sun_3", "start") in types and ("temperature_5", "undercut") in types
        assert ("dawn_1", "triggered") in types and ("rain", "start") in types

        actor_triggers = await async_get_device_automations(
            hass, DeviceAutomationType.TRIGGER, actor.id
        )
        assert not [t for t in actor_triggers if t["domain"] == DOMAIN]

        fired: list[str] = []
        hass.bus.async_listen("test_sun_3", lambda e: fired.append("sun_3"))
        hass.bus.async_listen("test_rain", lambda e: fired.append("rain"))
        assert await async_setup_component(
            hass,
            "automation",
            {
                "automation": [
                    {
                        "trigger": {
                            "platform": "device",
                            "domain": DOMAIN,
                            "device_id": weather.id,
                            "type": "sun_3",
                            "subtype": "start",
                        },
                        "action": {"event": "test_sun_3"},
                    },
                    {
                        "trigger": {
                            "platform": "device",
                            "domain": DOMAIN,
                            "device_id": weather.id,
                            "type": "rain",
                            "subtype": "start",
                        },
                        "action": {"event": "test_rain"},
                    },
                ]
            },
        )
        await hass.async_block_till_done()

        feed(coordinator, _sensor_message("0708", 0x01, UMWELT))  # startSun slot 1
        await hass.async_block_till_done()
        assert fired == []
        feed(coordinator, _sensor_message("0708", 0x04, UMWELT))  # startSun slot 3
        await hass.async_block_till_done()
        assert fired == ["sun_3"]
        feed(coordinator, _sensor_message("0711", 0x00, UMWELT))  # startRain
        await hass.async_block_till_done()
        assert fired == ["sun_3", "rain"]

        await unload_entry(hass, entry)


async def test_trigger_for_a_removed_device_is_harmless(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An automation that still points to a removed device loads without error."""
    async with fake_stick():
        entry = make_entry(hass, ["A0A1B2"])
        await setup_entry(hass, entry)
        device_registry = dr.async_get(hass)
        foreign = MockConfigEntry(domain="other")
        foreign.add_to_hass(hass)
        other = device_registry.async_get_or_create(
            config_entry_id=foreign.entry_id, identifiers={("other", "x")}
        )
        assert await async_setup_component(
            hass,
            "automation",
            {
                "automation": [
                    {
                        "trigger": {
                            "platform": "device",
                            "domain": DOMAIN,
                            "device_id": other.id,
                            "type": "channel_01",
                            "subtype": "up",
                        },
                        "action": {"event": "never"},
                    }
                ]
            },
        )
        await hass.async_block_till_done()
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Battery, time, frames from unknown devices
# ---------------------------------------------------------------------------


async def test_battery_status_frames(hass: HomeAssistant) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["ABA1B2", "65A1B2"])
        coordinator = await setup_entry(hass, entry)

        feed(coordinator, "0FFF1323" + "5A" + "00" * 10 + "ABA1B2" + "FFFFFF01")
        await hass.async_block_till_done()
        assert _state(hass, "sensor", "duofern_ABA1B2_battery").state == "90"

        feed(coordinator, "0FFF1323" + "08" + "00" * 10 + "ABA1B2" + "FFFFFF01")
        await hass.async_block_till_done()
        assert _state(hass, "sensor", "duofern_ABA1B2_battery").state == "8"
        assert coordinator.data.devices["ABA1B2"].battery_state == "low"

        # multi-channel device: stored on its channels
        feed(coordinator, "0FFF1323" + "32" + "00" * 10 + "65A1B2" + "FFFFFF01")
        await hass.async_block_till_done()
        assert coordinator.data.devices["65A1B200"].battery_percent == 50
        assert coordinator.data.devices["65A1B201"].battery_percent == 50

        await unload_entry(hass, entry)


async def test_battery_sensor_only_for_known_battery_devices(
    hass: HomeAssistant,
) -> None:
    """Battery entity for 0xAB, 0xAC and 0xE1 only; a stale 0x65 one is removed."""
    async with fake_stick():
        entry = make_entry(hass, ["ABA1B2", "ACA1B2", "E1A1B2", "65A1B2", "73A1B2"])
        registry = er.async_get(hass)
        # Battery entity left behind by an older version for the Bewegungsmelder
        registry.async_get_or_create(
            "sensor", DOMAIN, "duofern_65A1B200_battery", config_entry=entry
        )
        coordinator = await setup_entry(hass, entry)

        def battery(hex_code: str) -> str | None:
            return registry.async_get_entity_id(
                "sensor", DOMAIN, f"duofern_{hex_code}_battery"
            )

        assert battery("ABA1B2") is not None
        assert battery("ACA1B2") is not None
        assert battery("E1A1B2") is not None
        assert battery("65A1B200") is None
        assert battery("65A1B201") is None
        assert battery("73A1B2") is None

        # A battery frame from another type is stored and shown as attribute,
        # but creates no battery entity.
        feed(coordinator, "0FFF1323" + "3C" + "00" * 10 + "73A1B2" + "FFFFFF01")
        await hass.async_block_till_done()
        assert coordinator.data.devices["73A1B2"].battery_percent == 60
        assert battery("73A1B2") is None

        await unload_entry(hass, entry)


async def test_frames_from_unknown_devices_are_ignored(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Frames of devices that are not paired change nothing and raise nothing."""
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        before = {
            k: dict(s.status.readings) for k, s in coordinator.data.devices.items()
        }
        with caplog.at_level(logging.DEBUG):
            for frame in (
                "0FFF1323" + "5A" + "00" * 10 + "ABFFFF" + "FFFFFF01",  # battery
                "0FFF1323"
                + "5A"
                + "00" * 10
                + "65FFFF"
                + "FFFFFF01",  # battery, channels
                "0F011020" + "00" * 11 + "69FFFF" + "FFFFFF01",  # time
                "0FFF1B21" + "00" * 11 + "69FFFF" + "FFFFFF01",  # config page
                "0F011322" + "00" * 11 + "69FFFF" + "FFFFFF01",  # weather
                "0FFF0F22" + "00" * 11 + "43FFFF" + "FFFFFF01",  # status, channels
                _sensor_message("0708", 0x01, "69FFFF"),
                _sensor_message("0701", 0x01, "A0FFFF"),
            ):
                feed(coordinator, frame)
            await hass.async_block_till_done()
        assert {
            k: dict(s.status.readings) for k, s in coordinator.data.devices.items()
        } == before
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        await unload_entry(hass, entry)


async def test_commands_for_unknown_devices_do_nothing(hass: HomeAssistant) -> None:
    """Umweltsensor setters and getters called for a code that is not paired."""
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        stick.sent.clear()
        unknown = DuoFernId.from_hex("69FFFF")

        called = 0
        for name, method in inspect.getmembers(coordinator, inspect.ismethod):
            if not (
                name.startswith(
                    ("async_set_trigger_", "async_set_umweltsensor_", "get_trigger_")
                )
                or name in ("async_set_selected_grenzwert",)
            ):
                continue
            params = list(inspect.signature(method).parameters)
            args: list = [unknown]
            for param in params[1:]:
                args.append("sun" if param == "group" else 1)
            result = method(*args)
            if inspect.isawaitable(result):
                await result
            called += 1
        assert called > 30
        assert stick.sent == []
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Umweltsensor: write configuration
# ---------------------------------------------------------------------------


async def test_write_config_sends_all_pages_and_reads_back(hass: HomeAssistant) -> None:
    async with fake_stick():
        entry = make_entry(hass, [UMWELT])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        pages = [f"{n + 1:02X}" * 10 for n in range(8)]
        for n, page in enumerate(pages):
            feed(coordinator, f"0FFF1B2{n + 1}{page}00{UMWELT}FFFFFF01")
        await hass.async_block_till_done()
        stick.sent.clear()

        await hass.services.async_call(
            "button",
            "press",
            {
                "entity_id": entity_id(
                    hass, "button", f"duofern_{UMWELT}00_write_config"
                )
            },
            blocking=True,
        )
        await hass.async_block_till_done()

        written = [f for f in stick.sent if f.startswith("0DFF1B")]
        assert [f[8:28] for f in written] == pages
        assert [f[6:8] for f in written] == [f"8{n + 1}" for n in range(8)]
        assert all(f[36:42] == UMWELT for f in written)
        assert len(stick.sent) == 9  # followed by one getConfig to read back
        await unload_entry(hass, entry)


async def test_write_config_with_seven_of_eight_pages_is_refused(
    hass: HomeAssistant,
) -> None:
    async with fake_stick():
        entry = make_entry(hass, [UMWELT])
        coordinator = await setup_entry(hass, entry)
        for n in range(7):
            feed(coordinator, f"0FFF1B2{n + 1}{'00' * 10}00{UMWELT}FFFFFF01")
        await hass.async_block_till_done()
        FakeStick.instances[-1].sent.clear()
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                "button",
                "press",
                {
                    "entity_id": entity_id(
                        hass, "button", f"duofern_{UMWELT}00_write_config"
                    )
                },
                blocking=True,
            )
        assert error.value.translation_placeholders == {"received": "7"}
        assert FakeStick.instances[-1].sent == []
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Setup: migration, failed cleanup, stale registry entries
# ---------------------------------------------------------------------------


async def test_entry_from_a_newer_version_is_not_loaded(hass: HomeAssistant) -> None:
    async with fake_stick():
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=SYSTEM_CODE,
            version=3,
            data={
                CONF_SERIAL_PORT: "/dev/ttyUSB0",
                CONF_DEVICE_CODE: SYSTEM_CODE,
                CONF_PAIRED_DEVICES: [],
            },
        )
        entry.add_to_hass(hass)
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.MIGRATION_ERROR
        assert FakeStick.instances == []


async def test_failed_connect_with_failing_disconnect_still_retries(
    hass: HomeAssistant,
) -> None:
    """An error while closing the port must not hide the connect error."""

    class Broken(FakeStick):
        async def connect(self) -> None:
            raise ConnectionError("init failed")

        async def disconnect(self) -> None:
            raise OSError("port already gone")

    async with fake_stick(Broken):
        entry = make_entry(hass, ["40A1B2"])
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_stale_devices_and_entities_are_removed(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2", "46ABCD"])
        await setup_entry(hass, entry)
        await unload_entry(hass, entry)

        registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        kept_device = _device(hass, entry, "40A1B2")
        # an entity of an older version that the integration no longer creates
        registry.async_get_or_create(
            "button",
            DOMAIN,
            "duofern_40A1B2_removed_in_new_version",
            config_entry=entry,
            device_id=kept_device.id,
        )
        # an entity of a platform that creates nothing in this setup (light):
        # kept, because an empty platform may also mean "failed to load"
        registry.async_get_or_create(
            "light",
            DOMAIN,
            "duofern_40A1B2_light",
            config_entry=entry,
            device_id=kept_device.id,
        )

        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_PAIRED_DEVICES: ["40A1B2"]}
        )
        with caplog.at_level(logging.WARNING):
            await setup_entry(hass, entry)

        assert _device(hass, entry, "46ABCD") is None
        unique_ids = {
            e.unique_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert not [u for u in unique_ids if "46ABCD" in u]
        assert "duofern_40A1B2_removed_in_new_version" not in unique_ids
        assert "duofern_40A1B2_light" in unique_ids
        assert "duofern_40A1B2" in unique_ids  # the cover itself
        assert "Removed stale entity" in caplog.text
        assert "platform 'light' registered no entities" in caplog.text
        await unload_entry(hass, entry)


async def test_cleanup_is_skipped_when_no_platform_registered_anything(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """If every platform failed to load, nothing is deleted."""
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        await setup_entry(hass, entry)
        await unload_entry(hass, entry)
        registry = er.async_get(hass)
        before = {
            e.unique_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

        with (
            patch.object(
                hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
            ),
            caplog.at_level(logging.WARNING),
        ):
            await setup_entry(hass, entry)
        after = {
            e.unique_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert after == before
        assert "skipping stale entity cleanup" in caplog.text
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            assert await hass.config_entries.async_unload(entry.entry_id)


def test_coordinator_exposes_what_the_tests_rely_on() -> None:
    """Guard: the generic unknown-device test above matches real method names."""
    names = [n for n in dir(DuoFernCoordinator) if n.startswith("async_set_trigger_")]
    assert len(names) >= 15


# ---------------------------------------------------------------------------
# Pair by code with a 10-digit code
# ---------------------------------------------------------------------------


async def test_pair_by_code_with_ten_digit_code(hass: HomeAssistant) -> None:
    """Code 431234ABCD: password in the frame, the device stays 6-digit.

    Same layout as in the test with a real device on 2026-11-16: USB frame
    0DFF0601ABCD...6F5C7E43123401, answer 0602 02 ... 431234.
    """
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        sent: list[str] = []
        system = coordinator.system_code.hex

        async def send(frame: bytearray) -> None:
            sent.append(bytes(frame).hex().upper())
            # the device answers once, as in the test with the real device
            if frame[0] == 0x0D and frame[2] == 0x06 and not answered:
                answered.append(True)
                answer = bytearray.fromhex(
                    "06020200000000000000000000000043123400000000"
                )
                hass.loop.call_soon(coordinator._on_message, answer)

        answered: list[bool] = []
        stick.send_command = send  # type: ignore[method-assign]
        with patch("custom_components.duofern.coordinator.REMOTE_PAIR_TIMEOUT", 0.5):
            result = await hass.services.async_call(
                DOMAIN,
                "pair_device_by_code",
                {"device_code": "431234abcd"},
                blocking=True,
                return_response=True,
            )
        assert result == {"device_code": "431234", "result": "paired"}
        pair_frames = [f for f in sent if f.startswith("0DFF0601")]
        assert pair_frames == [f"0DFF0601ABCD000000000000000000{system}43123401"] * 2
        # SetPairs addresses the 6-digit code
        assert sent[0][:2] == "03" and "431234" in sent[0] and "ABCD" not in sent[0]
        assert sent[-1][:2] == "05"
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2", "431234"]
        # Universalaktor: two channel devices, no trace of the password
        assert sorted(entry.runtime_data.data.devices) == [
            "40A1B2",
            "43123401",
            "43123402",
        ]
        await unload_entry(hass, entry)


async def test_pair_by_code_second_pair_response_does_not_reload_early(
    hass: HomeAssistant,
) -> None:
    """The device answers both pair frames at once: StopPair still goes out.

    The second 0602 used to run into the normal pairing path, which wrote
    the config entry and reloaded the integration before StopPair was sent.
    """
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        instances = len(FakeStick.instances)
        sent: list[str] = []

        async def send(frame: bytearray) -> None:
            sent.append(bytes(frame).hex().upper())
            if frame[0] == 0x0D and frame[2] == 0x06:
                answer = bytearray.fromhex(
                    "06020200000000000000000000000046ABCD00000000"
                )
                hass.loop.call_soon(coordinator._on_message, answer)

        stick.send_command = send  # type: ignore[method-assign]
        with patch("custom_components.duofern.coordinator.REMOTE_PAIR_TIMEOUT", 0.5):
            await hass.services.async_call(
                DOMAIN,
                "pair_device_by_code",
                {"device_code": "46ABCD"},
                blocking=True,
                return_response=True,
            )
        assert [f[:8] for f in sent].count("0DFF0601") == 2
        assert sent[-1][:2] == "05"  # StopPair, sent before the reload
        await hass.async_block_till_done()
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2", "46ABCD"]
        assert len(FakeStick.instances) == instances + 1  # exactly one reload
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Pair by code: the three ways it can fail
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stick_answer", "translation_key"),
    [
        ("810108AA", "pair_aa"),  # device did not acknowledge
        ("810100BB", "pair_bb"),  # device rejected
        (None, "pair_timeout"),  # no answer at all
    ],
)
async def test_pair_by_code_failures(
    hass: HomeAssistant, stick_answer: str | None, translation_key: str
) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2"])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        sent: list[str] = []

        async def send(frame: bytearray) -> None:
            sent.append(bytes(frame).hex().upper())
            if stick_answer and frame[0] == 0x0D and frame[2] == 0x06:
                answer = (
                    bytes.fromhex(stick_answer)
                    + bytes(14)
                    + bytes.fromhex("46ABCD")
                    + b"\x00"
                )
                hass.loop.call_soon(coordinator._on_message, bytearray(answer))

        stick.send_command = send  # type: ignore[method-assign]
        with (
            patch("custom_components.duofern.coordinator.REMOTE_PAIR_TIMEOUT", 0.3),
            pytest.raises(HomeAssistantError) as error,
        ):
            await hass.services.async_call(
                DOMAIN,
                "pair_device_by_code",
                {"device_code": "46ABCD"},
                blocking=True,
                return_response=True,
            )
        assert error.value.translation_key == translation_key
        assert error.value.translation_placeholders["device_code"] == "46ABCD"
        await hass.async_block_till_done()
        # nothing was added, pairing mode was left again, no reload
        assert entry.data[CONF_PAIRED_DEVICES] == ["40A1B2"]
        assert entry.runtime_data is coordinator
        assert not coordinator.data.pairing_active
        assert sent[-1][:2] == "05"  # StopPair is the last frame
        await unload_entry(hass, entry)


# ---------------------------------------------------------------------------
# Diagnostics and write-config edge cases
# ---------------------------------------------------------------------------


async def test_diagnostics_contain_umweltsensor_config_state(
    hass: HomeAssistant,
) -> None:
    from custom_components.duofern.diagnostics import async_get_config_entry_diagnostics

    async with fake_stick():
        entry = make_entry(hass, [UMWELT, "40A1B2"])
        coordinator = await setup_entry(hass, entry)
        feed(coordinator, f"0FFF1B21{'11' * 10}00{UMWELT}FFFFFF01")
        await hass.async_block_till_done()

        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        text = str(diagnostics)
        assert "weather_config_registers" in text
        assert "sun_direction_memory" in text and "selected_grenzwert" in text
        assert "11111111111111111111" in text
        # the plain cover has no Umweltsensor fields
        snapshot = coordinator.get_diagnostics()

        def find(node: object, key: str) -> dict | None:
            if isinstance(node, dict):
                if key in node and isinstance(node[key], dict):
                    return node[key]
                for value in node.values():
                    found = find(value, key)
                    if found is not None:
                        return found
            return None

        assert "weather_config_registers" in find(snapshot, UMWELT + "00")
        assert "weather_config_registers" not in find(snapshot, UMWELT + "01")
        assert "weather_config_registers" not in find(snapshot, "40A1B2")
        await unload_entry(hass, entry)


async def test_write_config_survives_bad_register_and_send_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed stored page is sent as zeros; a failing send does not abort."""
    async with fake_stick():
        entry = make_entry(hass, [UMWELT])
        coordinator = await setup_entry(hass, entry)
        stick = FakeStick.instances[-1]
        for n in range(8):
            feed(coordinator, f"0FFF1B2{n + 1}{'AB' * 10}00{UMWELT}FFFFFF01")
        await hass.async_block_till_done()
        state = coordinator.data.devices[UMWELT + "00"]
        state.weather_config_registers[2] = "ABCD"  # wrong length

        sent: list[str] = []

        async def send(frame: bytes) -> None:
            hex_frame = bytes(frame).hex().upper()
            if hex_frame.startswith("0DFF1B85"):
                raise OSError("stick gone")
            sent.append(hex_frame)

        stick.send_command = send  # type: ignore[method-assign]
        with caplog.at_level(logging.WARNING):
            await coordinator.async_write_weather_config(DuoFernId.from_hex(UMWELT))

        pages = [f for f in sent if f.startswith("0DFF1B8")]
        assert [f[6:8] for f in pages] == ["81", "82", "83", "84", "86", "87", "88"]
        assert pages[2][8:28] == "0" * 20
        assert pages[0][8:28] == "AB" * 10
        assert "invalid register data for reg2" in caplog.text
        assert "could not send reg4 frame" in caplog.text
        await unload_entry(hass, entry)
