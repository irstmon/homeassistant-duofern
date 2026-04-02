"""Tests for the DuoFern switch platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.duofern.switch import (
    DuoFernSwitch,
    DuoFernAutomationSwitch,
    DuoFernBoostSwitch,
    AUTOMATION_SWITCH_DESCRIPTIONS,
)
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE

SWITCH_HEX = "436C1A"   # Universalaktor 0x43
SOCKET_HEX = "461234"   # Steckdosenaktor 0x46
HSA_HEX = "E11234"      # Heizkörperantrieb 0xE1 → boost switch


def _make_switch_coordinator(hex_code: str) -> tuple[MagicMock, DuoFernDeviceState]:
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.status.level = None

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    coordinator.async_switch_on = AsyncMock()
    coordinator.async_switch_off = AsyncMock()
    coordinator.async_set_automation = AsyncMock()
    coordinator.async_set_window_contact = AsyncMock()
    coordinator.async_set_mode_change = AsyncMock()
    return coordinator, device_state


# ---------------------------------------------------------------------------
# Automation switch descriptions
# ---------------------------------------------------------------------------


def test_automation_switch_descriptions_not_empty():
    assert len(AUTOMATION_SWITCH_DESCRIPTIONS) > 0


def test_manual_mode_description_exists():
    keys = [d.key for d in AUTOMATION_SWITCH_DESCRIPTIONS]
    assert "manualMode" in keys


def test_time_automatic_description_exists():
    keys = [d.key for d in AUTOMATION_SWITCH_DESCRIPTIONS]
    assert "timeAutomatic" in keys


def test_automation_switches_have_reading_key():
    for desc in AUTOMATION_SWITCH_DESCRIPTIONS:
        assert desc.reading_key, f"{desc.key} missing reading_key"


# ---------------------------------------------------------------------------
# DuoFernSwitch — is_on uses status.level, not readings
# ---------------------------------------------------------------------------


def test_switch_unique_id():
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    assert SOCKET_HEX in sw._attr_unique_id


def test_switch_is_on_when_level_nonzero():
    """is_on uses status.level > 0, not readings."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    device_state.status.level = 100
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    assert sw.is_on is True


def test_switch_is_off_when_level_zero():
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    device_state.status.level = 0
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    assert sw.is_on is False


def test_switch_is_none_when_level_none():
    """is_on returns None when status.level is None (unknown state)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    device_state.status.level = None
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    assert sw.is_on is None


async def test_switch_turn_on_calls_coordinator():
    """async_turn_on calls coordinator.async_switch_on(device_code, channel=1)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    await sw.async_turn_on()
    device_id = DuoFernId.from_hex(SOCKET_HEX)
    coordinator.async_switch_on.assert_called_once_with(device_id, channel=1)


async def test_switch_turn_off_calls_coordinator():
    """async_turn_off calls coordinator.async_switch_off(device_code, channel=1)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    await sw.async_turn_off()
    device_id = DuoFernId.from_hex(SOCKET_HEX)
    coordinator.async_switch_off.assert_called_once_with(device_id, channel=1)


def test_switch_available_when_device_present():
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    device_state.available = True
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
    )
    assert sw.available is True


# ---------------------------------------------------------------------------
# DuoFernAutomationSwitch
# ---------------------------------------------------------------------------


def test_automation_switch_entity_category_config():
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "manualMode")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    assert sw.entity_category == EntityCategory.CONFIG


def test_automation_switch_unique_id_includes_key_and_auto():
    """unique_id format is {DOMAIN}_{hex_code}_{key}_auto."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "manualMode")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    assert "manualMode" in sw._attr_unique_id
    assert SOCKET_HEX in sw._attr_unique_id
    assert sw._attr_unique_id.endswith("_auto")


def test_automation_switch_is_on_from_reading():
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    device_state.status.readings = {"manualMode": "on"}
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "manualMode")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    assert sw.is_on is True


def test_automation_switch_is_off_from_reading():
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    device_state.status.readings = {"manualMode": "off"}
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "manualMode")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    assert sw.is_on is False


async def test_automation_switch_turn_on_calls_coordinator():
    """async_turn_on calls coordinator.async_set_automation(device_code, name, True)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "manualMode")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    await sw.async_turn_on()
    device_id = DuoFernId.from_hex(SOCKET_HEX)
    coordinator.async_set_automation.assert_called_once_with(
        device_id, "manualMode", True
    )


async def test_automation_switch_turn_off_calls_coordinator():
    """async_turn_off calls coordinator.async_set_automation(device_code, name, False)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "manualMode")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    await sw.async_turn_off()
    device_id = DuoFernId.from_hex(SOCKET_HEX)
    coordinator.async_set_automation.assert_called_once_with(
        device_id, "manualMode", False
    )


# ---------------------------------------------------------------------------
# DuoFernBoostSwitch
# ---------------------------------------------------------------------------


def _make_boost_coordinator(hex_code=HSA_HEX):
    device_id = DuoFernId.from_hex(hex_code)
    device_state = DuoFernDeviceState(device_code=device_id)
    device_state.status = MagicMock()
    device_state.status.readings = {}
    device_state.available = True

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.data.devices[hex_code] = device_state
    coordinator.async_set_boost = AsyncMock()
    return coordinator, device_state


def test_boost_switch_unique_id():
    coordinator, device_state = _make_boost_coordinator()
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert HSA_HEX in sw._attr_unique_id
    assert "boost" in sw._attr_unique_id


def test_boost_switch_is_on_when_reading_on():
    """is_on returns True when readings['boostActive'] == 'on'."""
    coordinator, device_state = _make_boost_coordinator()
    device_state.status.readings = {"boostActive": "on"}
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.is_on is True


def test_boost_switch_is_off_when_reading_off():
    coordinator, device_state = _make_boost_coordinator()
    device_state.status.readings = {"boostActive": "off"}
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.is_on is False


def test_boost_switch_is_off_when_reading_missing():
    """is_on returns False when boostActive not in readings."""
    coordinator, device_state = _make_boost_coordinator()
    device_state.status.readings = {}
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.is_on is False


def test_boost_switch_available_when_device_present():
    coordinator, device_state = _make_boost_coordinator()
    device_state.available = True
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.available is True


def test_boost_switch_unavailable_when_device_unavailable():
    coordinator, device_state = _make_boost_coordinator()
    device_state.available = False
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.available is False


async def test_boost_switch_turn_on_calls_coordinator():
    """async_turn_on calls coordinator.async_set_boost(device_code, True)."""
    coordinator, device_state = _make_boost_coordinator()
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    await sw.async_turn_on()
    device_id = DuoFernId.from_hex(HSA_HEX)
    coordinator.async_set_boost.assert_called_once_with(device_id, True)


async def test_boost_switch_turn_off_calls_coordinator():
    """async_turn_off calls coordinator.async_set_boost(device_code, False)."""
    coordinator, device_state = _make_boost_coordinator()
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    await sw.async_turn_off()
    device_id = DuoFernId.from_hex(HSA_HEX)
    coordinator.async_set_boost.assert_called_once_with(device_id, False)


def test_boost_switch_is_none_when_coordinator_data_none():
    coordinator, device_state = _make_boost_coordinator()
    coordinator.data = None
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.is_on is None


def test_boost_switch_unavailable_when_coordinator_data_none():
    coordinator, device_state = _make_boost_coordinator()
    coordinator.data = None
    sw = DuoFernBoostSwitch(coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX)
    assert sw.available is False


# ---------------------------------------------------------------------------
# DuoFernSwitch — availability and extra attributes
# ---------------------------------------------------------------------------


def _make_switch(hex_code=SOCKET_HEX):
    coordinator, device_state = _make_switch_coordinator(hex_code)
    sw = DuoFernSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
    )
    return sw, coordinator, device_state


def test_switch_unavailable_when_coordinator_data_none():
    sw, coordinator, _ = _make_switch()
    coordinator.data = None
    assert sw.available is False


def test_switch_unavailable_when_device_unavailable():
    sw, _, device_state = _make_switch()
    device_state.available = False
    assert sw.available is False


def test_switch_unavailable_when_last_update_failed():
    sw, coordinator, device_state = _make_switch()
    device_state.available = True
    coordinator.last_update_success = False
    assert sw.available is False


def test_switch_is_none_when_coordinator_data_none():
    sw, coordinator, _ = _make_switch()
    coordinator.data = None
    assert sw.is_on is None


# ---------------------------------------------------------------------------
# DuoFernSwitch — extra_state_attributes
# ---------------------------------------------------------------------------


def test_switch_extra_state_attributes_empty_when_data_none():
    sw, coordinator, _ = _make_switch()
    coordinator.data = None
    assert sw.extra_state_attributes == {}


def test_switch_extra_state_attributes_from_readings():
    sw, _, device_state = _make_switch()
    device_state.status.readings = {"manualMode": "on", "level": 100}
    device_state.status.version = None
    device_state.battery_state = None
    device_state.battery_percent = None
    attrs = sw.extra_state_attributes
    assert attrs.get("manualMode") == "on"
    assert "level" not in attrs  # level is in _SKIP_AS_ATTRIBUTE


def test_switch_extra_state_attributes_includes_firmware():
    sw, _, device_state = _make_switch()
    device_state.status.readings = {}
    device_state.status.version = "1.5"
    device_state.battery_state = None
    device_state.battery_percent = None
    attrs = sw.extra_state_attributes
    assert attrs.get("firmware_version") == "1.5"


def test_switch_extra_state_attributes_includes_battery():
    sw, _, device_state = _make_switch()
    device_state.status.readings = {}
    device_state.status.version = None
    device_state.battery_state = "low"
    device_state.battery_percent = 10
    attrs = sw.extra_state_attributes
    assert attrs.get("battery_state") == "low"
    assert attrs.get("battery_level") == 10


# ---------------------------------------------------------------------------
# DuoFernSwitch — device_info
# ---------------------------------------------------------------------------


def test_switch_device_info_has_domain_identifier():
    sw, _, device_state = _make_switch()
    device_state.status.version = None
    info = sw.device_info
    assert (DOMAIN, SOCKET_HEX) in info["identifiers"]


def test_switch_device_info_sw_version():
    sw, _, device_state = _make_switch()
    device_state.status.version = "2.1"
    info = sw.device_info
    assert info.get("sw_version") == "2.1"


def test_switch_device_info_sw_version_none_when_data_none():
    sw, coordinator, _ = _make_switch()
    coordinator.data = None
    info = sw.device_info
    assert info.get("sw_version") is None


# ---------------------------------------------------------------------------
# DuoFernSwitch — device class
# ---------------------------------------------------------------------------


def test_switch_device_class_outlet_for_steckdosen():
    """0x46 Steckdosenaktor → SwitchDeviceClass.OUTLET."""
    from homeassistant.components.switch import SwitchDeviceClass
    sw, _, _ = _make_switch(SOCKET_HEX)
    assert sw._attr_device_class == SwitchDeviceClass.OUTLET


def test_switch_device_class_switch_for_troll_lichtmodus():
    """0x71 Troll Lichtmodus → SwitchDeviceClass.SWITCH."""
    from homeassistant.components.switch import SwitchDeviceClass
    coordinator, device_state = _make_switch_coordinator("711234")
    sw = DuoFernSwitch(coordinator=coordinator, device_state=device_state, hex_code="711234")
    assert sw._attr_device_class == SwitchDeviceClass.SWITCH


# ---------------------------------------------------------------------------
# DuoFernAutomationSwitch — availability and is_on edge cases
# ---------------------------------------------------------------------------


def _make_auto_switch(hex_code=SOCKET_HEX, key="manualMode"):
    coordinator, device_state = _make_switch_coordinator(hex_code)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == key)
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=hex_code,
        description=desc,
    )
    return sw, coordinator, device_state


def test_automation_switch_available_true():
    sw, _, device_state = _make_auto_switch()
    device_state.available = True
    assert sw.available is True


def test_automation_switch_available_false_when_device_unavailable():
    sw, _, device_state = _make_auto_switch()
    device_state.available = False
    assert sw.available is False


def test_automation_switch_unavailable_when_data_none():
    sw, coordinator, _ = _make_auto_switch()
    coordinator.data = None
    assert sw.available is False


def test_automation_switch_is_on_none_when_state_none():
    """When coordinator.data is None, is_on returns _restored_is_on."""
    sw, coordinator, _ = _make_auto_switch()
    coordinator.data = None
    sw._restored_is_on = None
    assert sw.is_on is None


def test_automation_switch_is_on_restored_when_state_none():
    """When coordinator.data is None, is_on returns persisted _restored_is_on."""
    sw, coordinator, _ = _make_auto_switch()
    coordinator.data = None
    sw._restored_is_on = True
    assert sw.is_on is True


def test_automation_switch_is_on_false_when_reading_missing_and_no_restored():
    """When reading is absent and _restored_is_on is None, is_on returns False."""
    sw, _, device_state = _make_auto_switch()
    device_state.status.readings = {}
    sw._restored_is_on = None
    assert sw.is_on is False


def test_automation_switch_is_on_restored_when_reading_missing():
    """When reading is absent but _restored_is_on is set, return it."""
    sw, _, device_state = _make_auto_switch()
    device_state.status.readings = {}
    sw._restored_is_on = True
    assert sw.is_on is True


def test_automation_switch_is_on_with_numeric_1():
    """Reading value '1' counts as on."""
    sw, _, device_state = _make_auto_switch()
    device_state.status.readings = {"manualMode": "1"}
    assert sw.is_on is True


def test_automation_switch_is_on_with_string_true():
    """Reading value 'true' counts as on."""
    sw, _, device_state = _make_auto_switch()
    device_state.status.readings = {"manualMode": "true"}
    assert sw.is_on is True


def test_automation_switch_live_value_syncs_restored():
    """Reading a live value keeps _restored_is_on in sync."""
    sw, _, device_state = _make_auto_switch()
    device_state.status.readings = {"manualMode": "on"}
    sw._restored_is_on = None
    val = sw.is_on
    assert val is True
    assert sw._restored_is_on is True


# ---------------------------------------------------------------------------
# DuoFernAutomationSwitch — windowContact and modeChange special paths
# ---------------------------------------------------------------------------


async def test_automation_switch_turn_on_window_contact():
    """windowContact turn_on calls async_set_window_contact(device_code, True)."""
    coordinator, device_state = _make_switch_coordinator(HSA_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "windowContact")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
        description=desc,
    )
    await sw.async_turn_on()
    device_id = DuoFernId.from_hex(HSA_HEX)
    coordinator.async_set_window_contact.assert_called_once_with(device_id, True)


async def test_automation_switch_turn_off_window_contact():
    """windowContact turn_off calls async_set_window_contact(device_code, False)."""
    coordinator, device_state = _make_switch_coordinator(HSA_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "windowContact")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=HSA_HEX,
        description=desc,
    )
    await sw.async_turn_off()
    device_id = DuoFernId.from_hex(HSA_HEX)
    coordinator.async_set_window_contact.assert_called_once_with(device_id, False)


async def test_automation_switch_turn_on_mode_change():
    """modeChange turn_on calls async_set_mode_change (toggle)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "modeChange")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    await sw.async_turn_on()
    device_id = DuoFernId.from_hex(SOCKET_HEX)
    coordinator.async_set_mode_change.assert_called_once_with(device_id)


async def test_automation_switch_turn_off_mode_change():
    """modeChange turn_off also calls async_set_mode_change (toggle)."""
    coordinator, device_state = _make_switch_coordinator(SOCKET_HEX)
    desc = next(d for d in AUTOMATION_SWITCH_DESCRIPTIONS if d.key == "modeChange")
    sw = DuoFernAutomationSwitch(
        coordinator=coordinator,
        device_state=device_state,
        hex_code=SOCKET_HEX,
        description=desc,
    )
    await sw.async_turn_off()
    device_id = DuoFernId.from_hex(SOCKET_HEX)
    coordinator.async_set_mode_change.assert_called_once_with(device_id)


# ---------------------------------------------------------------------------
# DuoFernAutomationSwitch — async_added_to_hass
# ---------------------------------------------------------------------------


async def test_automation_switch_added_to_hass_restores_on():
    """last_state == 'on' sets _restored_is_on to True."""
    sw, _, _ = _make_auto_switch()
    mock_state = MagicMock()
    mock_state.state = "on"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sw.async_get_last_state = AsyncMock(return_value=mock_state)
        await sw.async_added_to_hass()
    assert sw._restored_is_on is True


async def test_automation_switch_added_to_hass_restores_off():
    """last_state == 'off' sets _restored_is_on to False."""
    sw, _, _ = _make_auto_switch()
    mock_state = MagicMock()
    mock_state.state = "off"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sw.async_get_last_state = AsyncMock(return_value=mock_state)
        await sw.async_added_to_hass()
    assert sw._restored_is_on is False


async def test_automation_switch_added_to_hass_ignores_unknown():
    """last_state.state == 'unknown' leaves _restored_is_on as None."""
    sw, _, _ = _make_auto_switch()
    mock_state = MagicMock()
    mock_state.state = "unknown"
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sw.async_get_last_state = AsyncMock(return_value=mock_state)
        await sw.async_added_to_hass()
    assert sw._restored_is_on is None


async def test_automation_switch_added_to_hass_last_state_none():
    """When last_state is None, _restored_is_on stays None."""
    sw, _, _ = _make_auto_switch()
    with patch.object(CoordinatorEntity, "async_added_to_hass", new_callable=AsyncMock):
        sw.async_get_last_state = AsyncMock(return_value=None)
        await sw.async_added_to_hass()
    assert sw._restored_is_on is None


# ---------------------------------------------------------------------------
# DuoFernAutomationSwitch — _handle_coordinator_update (firmware)
# ---------------------------------------------------------------------------


def test_automation_switch_handle_coordinator_update_updates_firmware():
    """_handle_coordinator_update updates device registry when fw version changes."""
    sw, _, device_state = _make_auto_switch()
    sw.async_write_ha_state = MagicMock()

    device_state.status.version = "3.0"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "2.0"
    mock_device.id = "device-id-xyz"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sw.hass = MagicMock()

    with patch(
        "custom_components.duofern.switch.dr.async_get",
        return_value=mock_registry,
    ):
        sw._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-xyz", sw_version="3.0"
    )
    sw.async_write_ha_state.assert_called_once()


def test_automation_switch_handle_coordinator_update_skips_when_no_version():
    """_handle_coordinator_update skips registry when state.status.version is falsy."""
    sw, _, device_state = _make_auto_switch()
    sw.async_write_ha_state = MagicMock()

    device_state.status.version = None
    device_state.available = True
    sw.hass = MagicMock()

    mock_registry = MagicMock()
    with patch(
        "custom_components.duofern.switch.dr.async_get",
        return_value=mock_registry,
    ):
        sw._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    sw.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernSwitch — _handle_coordinator_update (firmware)
# ---------------------------------------------------------------------------


def test_switch_handle_coordinator_update_updates_firmware():
    """DuoFernSwitch._handle_coordinator_update updates device registry on fw change."""
    sw, _, device_state = _make_switch()
    sw.async_write_ha_state = MagicMock()

    device_state.status.version = "2.5"
    device_state.available = True

    mock_device = MagicMock()
    mock_device.sw_version = "1.0"
    mock_device.id = "device-id-switch"
    mock_registry = MagicMock()
    mock_registry.async_get_device.return_value = mock_device

    sw.hass = MagicMock()

    with patch(
        "custom_components.duofern.switch.dr.async_get",
        return_value=mock_registry,
    ):
        sw._handle_coordinator_update()

    mock_registry.async_update_device.assert_called_once_with(
        "device-id-switch", sw_version="2.5"
    )
    sw.async_write_ha_state.assert_called_once()


def test_switch_handle_coordinator_update_skips_when_no_version():
    """DuoFernSwitch._handle_coordinator_update skips registry when no version."""
    sw, _, device_state = _make_switch()
    sw.async_write_ha_state = MagicMock()

    device_state.status.version = None
    device_state.available = True
    sw.hass = MagicMock()

    mock_registry = MagicMock()
    with patch(
        "custom_components.duofern.switch.dr.async_get",
        return_value=mock_registry,
    ):
        sw._handle_coordinator_update()

    mock_registry.async_get_device.assert_not_called()
    sw.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# DuoFernBoostSwitch — _handle_coordinator_update
# ---------------------------------------------------------------------------


def test_boost_switch_handle_coordinator_update():
    """DuoFernBoostSwitch._handle_coordinator_update calls async_write_ha_state."""
    coordinator, device_state = _make_boost_coordinator()
    sw = DuoFernBoostSwitch(
        coordinator=coordinator, device_state=device_state, hex_code=HSA_HEX
    )
    sw.async_write_ha_state = MagicMock()
    sw._handle_coordinator_update()
    sw.async_write_ha_state.assert_called_once()
