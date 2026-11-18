"""Golden frames: commands and status decoding checked against the FHEM module.

The fixtures were produced by running the original FHEM module
(30_DUOFERN.pm) and this integration side by side on the same input and
keeping only the cases where both agree:

* fixtures/tx_golden.json - a Home Assistant service call and the frame(s)
  FHEM sends for the corresponding "set" command.
* fixtures/rx_golden.json - a received frame and the readings FHEM derives
  from it.

A failure here means the integration no longer does what FHEM does for a case
where it did before.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.duofern.protocol import ParsedStatus

from .common import (
    ALL_DEVICES,
    FakeStick,
    enable_all_entities,
    entity_id,
    fake_stick,
    feed,
    make_entry,
    setup_entry,
    unload_entry,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Real status frame of a Heizkörperantrieb (boost off), code mapped to E1A1B2.
HSA_STATUS = "0FFF0F29D40917008042642A04140AE1A1B26F5C7E01"


def _same(actual: object, expected: object) -> bool:
    """Compare a reading: equal as text, or equal as number."""
    if str(actual) == str(expected):
        return True
    try:
        return abs(float(actual) - float(expected)) < 1e-6  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


async def test_commands_send_the_frames_fhem_sends(hass: HomeAssistant) -> None:
    """Every service call in the fixture produces exactly the FHEM frame(s)."""
    cases = json.loads((FIXTURES / "tx_golden.json").read_text())
    assert len(cases) > 800

    async with fake_stick():
        entry = make_entry(hass, ALL_DEVICES)
        await setup_entry(hass, entry)
        await enable_all_entities(hass, entry)
        coordinator = entry.runtime_data
        stick = FakeStick.instances[-1]

        wrong: list[str] = []
        for case in cases:
            target = entity_id(hass, case["domain"], case["unique_id"])
            # The Heizkörperantrieb only takes commands as an answer to its
            # own status frame: start from a clean state, queue the change,
            # then let the actuator "send" its status.
            answer_to_status = case.get("answer_to_status", False)
            if answer_to_status:
                state = coordinator.data.devices["E1A1B2"]
                state.hsa_pending.clear()
                state.status = ParsedStatus()
                feed(coordinator, HSA_STATUS)
                await hass.async_block_till_done()
            stick.sent.clear()
            await hass.services.async_call(
                case["domain"],
                case["service"],
                {"entity_id": target, **case["data"]},
                blocking=True,
            )
            if answer_to_status:
                feed(coordinator, HSA_STATUS)
            await hass.async_block_till_done()
            if stick.sent != case["frames"]:
                wrong.append(
                    f"{case['fhem']}: sent {stick.sent}, FHEM {case['frames']}"
                )

        await unload_entry(hass, entry)

    assert not wrong, f"{len(wrong)} of {len(cases)} differ, first: {wrong[:5]}"


async def test_frames_give_the_readings_fhem_gives(hass: HomeAssistant) -> None:
    """Every frame in the fixture decodes to the readings FHEM derives."""
    cases = json.loads((FIXTURES / "rx_golden.json").read_text())
    assert len(cases) > 1000

    async with fake_stick():
        entry = make_entry(hass, ALL_DEVICES)
        coordinator = await setup_entry(hass, entry)
        # Readings are compared on the coordinator; refreshing more than 500
        # entities per frame is not needed for that.
        coordinator.async_set_updated_data = lambda data: None  # type: ignore[method-assign]

        wrong: list[str] = []
        checked = 0
        for case in cases:
            frame = case["frame"]
            code = frame[30:36]
            for key, state in coordinator.data.devices.items():
                if key.startswith(code):
                    state.status = ParsedStatus()
                    state.hsa_pending.clear()
                    state.weather_config_registers.clear()
            feed(coordinator, frame)
            for key, expected in case["readings"].items():
                state = coordinator.data.devices[key]
                actual = dict(state.status.readings)
                if state.status.version is not None:
                    actual["version"] = state.status.version
                for name, value in expected.items():
                    checked += 1
                    if name not in actual or not _same(actual[name], value):
                        wrong.append(
                            f"{frame} {key} {name}: {actual.get(name)!r}, FHEM {value!r}"
                        )

        await hass.async_block_till_done()
        await unload_entry(hass, entry)

    assert checked > 14000
    assert not wrong, f"{len(wrong)} of {checked} differ, first: {wrong[:5]}"
