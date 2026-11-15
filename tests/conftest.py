"""Shared pytest fixtures for DuoFern integration tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern.const import (
    CONF_AUTO_DISCOVER,
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

# ---------------------------------------------------------------------------
# Constants shared across tests
# ---------------------------------------------------------------------------

MOCK_PORT = "/dev/ttyUSB0"
MOCK_SYSTEM_CODE = "6F1A2B"
MOCK_DEVICE_CODE_COVER = "406B2D"
MOCK_DEVICE_CODE_SWITCH = "436C1A"

MOCK_ENTRY_DATA = {
    CONF_SERIAL_PORT: MOCK_PORT,
    CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
    CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
}

MOCK_ENTRY_OPTIONS = {
    CONF_AUTO_DISCOVER: False,
}


# ---------------------------------------------------------------------------
# Config entry fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock DuoFern config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data=MOCK_ENTRY_DATA,
        options=MOCK_ENTRY_OPTIONS,
        version=2,
    )


# ---------------------------------------------------------------------------
# Serial port / stick mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_serial_port_valid() -> Generator[None, None, None]:
    """Patch _check_serial_port to return True (port exists)."""
    with patch(
        "custom_components.duofern.config_flow._check_serial_port",
        return_value=True,
    ):
        yield


@pytest.fixture
def mock_serial_port_missing() -> Generator[None, None, None]:
    """Patch _check_serial_port to return False (port not found)."""
    with patch(
        "custom_components.duofern.config_flow._check_serial_port",
        return_value=False,
    ):
        yield


@pytest.fixture
def mock_serial_comports() -> Generator[None, None, None]:
    """Patch serial.tools.list_ports.comports to return one port."""
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R USB UART"
    with patch(
        "serial.tools.list_ports.comports",
        return_value=[mock_port],
    ):
        yield


# ---------------------------------------------------------------------------
# Coordinator mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_coordinator(hass) -> MagicMock:
    """Return a MagicMock coordinator with sane defaults."""
    coordinator = MagicMock(spec=DuoFernCoordinator)
    coordinator.hass = hass
    coordinator.system_code = DuoFernId.from_hex(MOCK_SYSTEM_CODE)
    coordinator.last_update_success = True

    # Build a minimal DuoFernData with one cover device
    device_id = DuoFernId.from_hex(MOCK_DEVICE_CODE_COVER)
    device_state = DuoFernDeviceState(device_code=device_id)
    data = DuoFernData()
    data.devices[MOCK_DEVICE_CODE_COVER] = device_state
    coordinator.data = data

    coordinator.async_connect = AsyncMock()
    coordinator.async_request_all_status = AsyncMock()
    coordinator.async_pair_device_by_code = AsyncMock()
    coordinator.register_on_new_device_paired = MagicMock()
    return coordinator


@pytest.fixture
def mock_setup_entry() -> Generator[None, None, None]:
    """Patch async_setup_entry so config-flow tests don't need a real stick."""
    with patch(
        "custom_components.duofern.async_setup_entry",
        return_value=True,
    ):
        yield


@pytest.fixture
def mock_coordinator_connect() -> Generator[None, None, None]:
    """Patch DuoFernCoordinator.async_connect to succeed silently."""
    with patch.object(DuoFernCoordinator, "async_connect", new_callable=AsyncMock):
        yield


@pytest.fixture
def mock_coordinator_connect_fail() -> Generator[None, None, None]:
    """Patch DuoFernCoordinator.async_connect to raise an exception."""
    with patch.object(
        DuoFernCoordinator,
        "async_connect",
        new_callable=AsyncMock,
        side_effect=Exception("serial port not found"),
    ):
        yield
