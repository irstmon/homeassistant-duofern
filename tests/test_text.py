"""Tests for the DuoFern text platform (pair-by-code input field)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.text import TextEntity

from custom_components.duofern.text import DuoFernPairCodeText
from custom_components.duofern.const import DOMAIN
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import MOCK_SYSTEM_CODE, MOCK_DEVICE_CODE_COVER


def _make_text() -> DuoFernPairCodeText:
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True
    coordinator.data = DuoFernData()
    coordinator.async_pair_device_by_code = AsyncMock()

    text = DuoFernPairCodeText(coordinator, MOCK_SYSTEM_CODE)
    return text


def test_text_unique_id():
    text = _make_text()
    assert MOCK_SYSTEM_CODE in text._attr_unique_id
    assert "pair_code_input" in text._attr_unique_id


def test_text_initial_value_empty():
    text = _make_text()
    assert text.native_value == ""


def test_text_max_length_is_six():
    """Only 6-digit device codes are accepted."""
    text = _make_text()
    assert text._attr_native_max == 6


async def test_text_set_value_stores_code():
    text = _make_text()
    await text.async_set_value(MOCK_DEVICE_CODE_COVER)
    assert text.native_value == MOCK_DEVICE_CODE_COVER.upper()


async def test_text_set_value_invalid_does_not_store():
    """async_set_value ignores values that are not exactly 6 hex chars."""
    text = _make_text()
    await text.async_set_value("ZZZZZZ")
    assert text.native_value == ""


async def test_text_set_value_normalises_to_uppercase():
    """async_set_value uppercases the stored code."""
    text = _make_text()
    await text.async_set_value("406b2d")
    assert text.native_value == "406B2D"


async def test_text_set_value_strips_whitespace():
    """async_set_value strips leading/trailing whitespace before validation."""
    text = _make_text()
    await text.async_set_value("  406B2D  ")
    assert text.native_value == "406B2D"


async def test_text_set_value_too_short_rejected():
    """5-char hex string is rejected (must be exactly 6)."""
    text = _make_text()
    await text.async_set_value("406B2")
    assert text.native_value == ""


async def test_text_set_value_too_long_rejected():
    """7-char hex string is rejected (must be exactly 6)."""
    text = _make_text()
    await text.async_set_value("406B2D1")
    assert text.native_value == ""


async def test_text_set_value_empty_rejected():
    """Empty string is rejected."""
    text = _make_text()
    await text.async_set_value("")
    assert text.native_value == ""


async def test_text_set_value_invalid_chars_rejected():
    """Hex string with non-hex characters is rejected."""
    text = _make_text()
    await text.async_set_value("40GG2D")
    assert text.native_value == ""


async def test_text_set_value_calls_async_write_ha_state_on_success():
    """async_write_ha_state is called when a valid code is stored."""
    text = _make_text()
    text.async_write_ha_state = MagicMock()
    await text.async_set_value("406B2D")
    text.async_write_ha_state.assert_called_once()


async def test_text_set_value_does_not_call_write_state_on_invalid():
    """async_write_ha_state is NOT called when code is invalid."""
    text = _make_text()
    text.async_write_ha_state = MagicMock()
    await text.async_set_value("ZZZZZZ")
    text.async_write_ha_state.assert_not_called()
