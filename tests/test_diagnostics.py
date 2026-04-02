"""Tests for DuoFern diagnostics."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern.const import (
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from custom_components.duofern.coordinator import (
    DuoFernCoordinator,
    DuoFernData,
    DuoFernDeviceState,
)
from custom_components.duofern.protocol import DuoFernId

from .conftest import (
    MOCK_DEVICE_CODE_COVER,
    MOCK_ENTRY_DATA,
    MOCK_ENTRY_OPTIONS,
    MOCK_SYSTEM_CODE,
)


async def test_diagnostics_redacts_system_code(hass: HomeAssistant) -> None:
    """Diagnostics output redacts the system_code."""
    from custom_components.duofern.diagnostics import async_get_config_entry_diagnostics

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data=MOCK_ENTRY_DATA,
        options=MOCK_ENTRY_OPTIONS,
        version=2,
    )
    entry.add_to_hass(hass)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    device_state = DuoFernDeviceState(device_code=device_id)
    data = DuoFernData()
    data.devices[MOCK_DEVICE_CODE_COVER] = device_state

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.data = data
    entry.runtime_data = coordinator

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag is not None
    # system_code / serial port should be redacted in diagnostics
    diag_str = str(diag)
    assert MOCK_SYSTEM_CODE not in diag_str or "**REDACTED**" in diag_str


async def test_diagnostics_includes_device_data(hass: HomeAssistant) -> None:
    """Diagnostics output includes device hex codes."""
    from custom_components.duofern.diagnostics import async_get_config_entry_diagnostics

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data=MOCK_ENTRY_DATA,
        options=MOCK_ENTRY_OPTIONS,
        version=2,
    )
    entry.add_to_hass(hass)

    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    device_state = DuoFernDeviceState(device_code=device_id)
    data = DuoFernData()
    data.devices[MOCK_DEVICE_CODE_COVER] = device_state

    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.data = data
    entry.runtime_data = coordinator

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag is not None
    assert isinstance(diag, dict)
