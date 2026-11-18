"""Tests for the DuoFern device_trigger platform."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.duofern.device_trigger import (
    TRIGGER_TYPES,
    async_attach_trigger,
    async_get_triggers,
)
from custom_components.duofern.const import DOMAIN

# Remote 0xA0 has 6 channels; sun+wind sensor is 0xA9
REMOTE_HEX = "A01234"   # device_type = 0xA0 → 6 channels
SUN_HEX = "A51234"      # device_type = 0xA5 → sun only
SUNWIND_HEX = "A91234"  # device_type = 0xA9 → sun + wind
WIND_HEX = "AA1234"     # device_type = 0xAA → wind only
COVER_HEX = "406B2D"    # device_type = 0x40 → no triggers


def _make_device_registry(hex_code: str):
    """Return a mock device registry containing one device identified by hex_code."""
    mock_device = MagicMock()
    mock_device.identifiers = {(DOMAIN, hex_code)}

    mock_registry = MagicMock()
    mock_registry.async_get.return_value = mock_device
    return mock_registry


def _make_empty_registry():
    """Return a mock device registry where the device is not found."""
    mock_registry = MagicMock()
    mock_registry.async_get.return_value = None
    return mock_registry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_trigger_types_contains_expected_actions():
    assert "up" in TRIGGER_TYPES
    assert "down" in TRIGGER_TYPES
    assert "stop" in TRIGGER_TYPES
    assert "pressed" in TRIGGER_TYPES


def test_trigger_types_has_eight_entries():
    assert len(TRIGGER_TYPES) == 8


# ---------------------------------------------------------------------------
# async_get_triggers — device not found
# ---------------------------------------------------------------------------


async def test_get_triggers_returns_empty_when_device_missing(
    hass: HomeAssistant,
) -> None:
    """Returns [] when the HA device ID is not in the device registry."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_empty_registry(),
    ):
        result = await async_get_triggers(hass, "nonexistent-device-id")
    assert result == []


# ---------------------------------------------------------------------------
# async_get_triggers — cover device (not remote/env)
# ---------------------------------------------------------------------------


async def test_get_triggers_returns_empty_for_cover(hass: HomeAssistant) -> None:
    """A cover device type (0x40) produces no device triggers."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(COVER_HEX),
    ):
        result = await async_get_triggers(hass, "some-device-id")
    assert result == []


# ---------------------------------------------------------------------------
# async_get_triggers — remote control (0xA0, 6 channels)
# ---------------------------------------------------------------------------


async def test_get_triggers_remote_a0_count(hass: HomeAssistant) -> None:
    """0xA0 has 6 channels × 8 actions = 48 triggers."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(REMOTE_HEX),
    ):
        result = await async_get_triggers(hass, "remote-device-id")
    assert len(result) == 6 * 8  # 48


async def test_get_triggers_remote_a0_structure(hass: HomeAssistant) -> None:
    """Each remote trigger has platform/domain/device_id/type/subtype."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(REMOTE_HEX),
    ):
        result = await async_get_triggers(hass, "remote-device-id")

    first = result[0]
    assert first["platform"] == "device"
    assert first["domain"] == DOMAIN
    assert first["device_id"] == "remote-device-id"
    assert first["type"].startswith("channel_")
    assert first["subtype"] in TRIGGER_TYPES


async def test_get_triggers_remote_a0_has_channel_01(hass: HomeAssistant) -> None:
    """0xA0 triggers include channel_01 with all actions."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(REMOTE_HEX),
    ):
        result = await async_get_triggers(hass, "remote-device-id")

    channel_01 = [t for t in result if t["type"] == "channel_01"]
    assert len(channel_01) == 8
    subtypes = {t["subtype"] for t in channel_01}
    assert subtypes == set(TRIGGER_TYPES)


# ---------------------------------------------------------------------------
# async_get_triggers — sun sensor (0xA5, sun only)
# ---------------------------------------------------------------------------


async def test_get_triggers_sun_sensor_count(hass: HomeAssistant) -> None:
    """0xA5 (Sonnensensor) has 2 triggers: sun/start and sun/end."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(SUN_HEX),
    ):
        result = await async_get_triggers(hass, "sun-device-id")
    assert len(result) == 2


async def test_get_triggers_sun_sensor_types(hass: HomeAssistant) -> None:
    """0xA5 triggers are type=sun, subtypes start and end."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(SUN_HEX),
    ):
        result = await async_get_triggers(hass, "sun-device-id")
    assert all(t["type"] == "sun" for t in result)
    subtypes = {t["subtype"] for t in result}
    assert subtypes == {"start", "end"}


# ---------------------------------------------------------------------------
# async_get_triggers — wind sensor (0xAA, wind only)
# ---------------------------------------------------------------------------


async def test_get_triggers_wind_sensor_count(hass: HomeAssistant) -> None:
    """0xAA (Markisenwaechter) has 2 triggers: wind/start and wind/end."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(WIND_HEX),
    ):
        result = await async_get_triggers(hass, "wind-device-id")
    assert len(result) == 2


async def test_get_triggers_wind_sensor_types(hass: HomeAssistant) -> None:
    """0xAA triggers are type=wind."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(WIND_HEX),
    ):
        result = await async_get_triggers(hass, "wind-device-id")
    assert all(t["type"] == "wind" for t in result)


# ---------------------------------------------------------------------------
# async_get_triggers — sun+wind sensor (0xA9, both)
# ---------------------------------------------------------------------------


async def test_get_triggers_sunwind_sensor_count(hass: HomeAssistant) -> None:
    """0xA9 (Sonnen-/Windsensor) has 4 triggers: sun×2 + wind×2."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(SUNWIND_HEX),
    ):
        result = await async_get_triggers(hass, "sunwind-device-id")
    assert len(result) == 4


async def test_get_triggers_sunwind_has_both_types(hass: HomeAssistant) -> None:
    """0xA9 triggers include both sun and wind types."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry(SUNWIND_HEX),
    ):
        result = await async_get_triggers(hass, "sunwind-device-id")
    types = {t["type"] for t in result}
    assert types == {"sun", "wind"}


# ---------------------------------------------------------------------------
# async_attach_trigger — device not found
# ---------------------------------------------------------------------------


async def test_attach_trigger_returns_noop_when_device_missing(
    hass: HomeAssistant,
) -> None:
    """Returns a no-op callable when device is not in the registry."""
    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": "missing-device",
        "type": "channel_01",
        "subtype": "up",
    }
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_empty_registry(),
    ):
        result = await async_attach_trigger(
            hass, config, MagicMock(), MagicMock()
        )
    # Result must be callable (a no-op lambda)
    assert callable(result)


# ---------------------------------------------------------------------------
# async_attach_trigger — remote control (channel-based event_data)
# ---------------------------------------------------------------------------


async def test_attach_trigger_remote_builds_correct_event_data(
    hass: HomeAssistant,
) -> None:
    """Remote triggers build event_data with device_code, event=subtype, channel."""
    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": "remote-device-id",
        "type": "channel_02",
        "subtype": "up",
    }

    captured_event_config = {}

    def fake_schema(cfg):
        captured_event_config.update(cfg)
        return cfg

    mock_unsub = MagicMock()

    with (
        patch(
            "custom_components.duofern.device_trigger.dr.async_get",
            return_value=_make_device_registry(REMOTE_HEX),
        ),
        patch(
            "custom_components.duofern.device_trigger.event_trigger.TRIGGER_SCHEMA",
            side_effect=fake_schema,
        ),
        patch(
            "custom_components.duofern.device_trigger.event_trigger.async_attach_trigger",
            new_callable=AsyncMock,
            return_value=mock_unsub,
        ),
    ):
        result = await async_attach_trigger(
            hass, config, MagicMock(), MagicMock()
        )

    assert result is mock_unsub
    event_data = captured_event_config["event_data"]
    assert event_data["device_code"] == REMOTE_HEX
    assert event_data["event"] == "up"
    assert event_data["channel"] == "02"


# ---------------------------------------------------------------------------
# async_attach_trigger — env sensor (type-based event_data)
# ---------------------------------------------------------------------------


async def test_attach_trigger_sun_sensor_builds_correct_event_data(
    hass: HomeAssistant,
) -> None:
    """Sun sensor triggers build event_data with device_code and event=startSun."""
    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": "sun-device-id",
        "type": "sun",
        "subtype": "start",
    }

    captured_event_config = {}

    def fake_schema(cfg):
        captured_event_config.update(cfg)
        return cfg

    mock_unsub = MagicMock()

    with (
        patch(
            "custom_components.duofern.device_trigger.dr.async_get",
            return_value=_make_device_registry(SUN_HEX),
        ),
        patch(
            "custom_components.duofern.device_trigger.event_trigger.TRIGGER_SCHEMA",
            side_effect=fake_schema,
        ),
        patch(
            "custom_components.duofern.device_trigger.event_trigger.async_attach_trigger",
            new_callable=AsyncMock,
            return_value=mock_unsub,
        ),
    ):
        result = await async_attach_trigger(
            hass, config, MagicMock(), MagicMock()
        )

    assert result is mock_unsub
    event_data = captured_event_config["event_data"]
    assert event_data["device_code"] == SUN_HEX
    assert event_data["event"] == "startSun"
    assert "channel" not in event_data


async def test_attach_trigger_wind_sensor_end_event(hass: HomeAssistant) -> None:
    """Wind sensor 'end' subtype maps to endWind event name."""
    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": "wind-device-id",
        "type": "wind",
        "subtype": "end",
    }

    captured_event_config = {}

    def fake_schema(cfg):
        captured_event_config.update(cfg)
        return cfg

    with (
        patch(
            "custom_components.duofern.device_trigger.dr.async_get",
            return_value=_make_device_registry(WIND_HEX),
        ),
        patch(
            "custom_components.duofern.device_trigger.event_trigger.TRIGGER_SCHEMA",
            side_effect=fake_schema,
        ),
        patch(
            "custom_components.duofern.device_trigger.event_trigger.async_attach_trigger",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
    ):
        await async_attach_trigger(hass, config, MagicMock(), MagicMock())

    event_data = captured_event_config["event_data"]
    assert event_data["event"] == "endWind"


# ---------------------------------------------------------------------------
# _get_hex_code_and_type — error branches
# ---------------------------------------------------------------------------


def _make_device_registry_invalid_hex():
    """Return a mock registry with a device whose identifier has an invalid hex prefix."""
    mock_device = MagicMock()
    # "GG1234": first two chars are not valid hex → int("GG", 16) raises ValueError
    mock_device.identifiers = {(DOMAIN, "GG1234")}
    mock_registry = MagicMock()
    mock_registry.async_get.return_value = mock_device
    return mock_registry


def _make_device_registry_no_domain_identifier():
    """Return a mock registry where the device has no identifier matching DOMAIN."""
    mock_device = MagicMock()
    mock_device.identifiers = {("other_domain", "A01234")}
    mock_registry = MagicMock()
    mock_registry.async_get.return_value = mock_device
    return mock_registry


async def test_get_triggers_returns_empty_for_invalid_hex_prefix(
    hass: HomeAssistant,
) -> None:
    """_get_hex_code_and_type returns None (→ []) when hex prefix is not valid hex."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry_invalid_hex(),
    ):
        result = await async_get_triggers(hass, "some-device-id")
    assert result == []


async def test_get_triggers_returns_empty_when_no_domain_identifier(
    hass: HomeAssistant,
) -> None:
    """_get_hex_code_and_type returns None (→ []) when device has no DOMAIN identifier."""
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry_no_domain_identifier(),
    ):
        result = await async_get_triggers(hass, "some-device-id")
    assert result == []


async def test_attach_trigger_returns_noop_for_invalid_hex_prefix(
    hass: HomeAssistant,
) -> None:
    """async_attach_trigger returns no-op when _get_hex_code_and_type returns None."""
    config = {
        "platform": "device",
        "domain": DOMAIN,
        "device_id": "bad-device",
        "type": "channel_01",
        "subtype": "up",
    }
    with patch(
        "custom_components.duofern.device_trigger.dr.async_get",
        return_value=_make_device_registry_invalid_hex(),
    ):
        result = await async_attach_trigger(hass, config, MagicMock(), MagicMock())
    assert callable(result)
