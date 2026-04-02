"""Tests for the DuoFern config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import serial
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.components import usb
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.duofern.const import (
    CONF_AUTO_DISCOVER,
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from custom_components.duofern.config_flow import _check_serial_port

from .conftest import (
    MOCK_DEVICE_CODE_COVER,
    MOCK_DEVICE_CODE_SWITCH,
    MOCK_PORT,
    MOCK_SYSTEM_CODE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _start_user_flow(hass: HomeAssistant):
    """Initialise a user config flow and return the result."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )


# ---------------------------------------------------------------------------
# User flow — step 1 (port + system code)
# ---------------------------------------------------------------------------


async def test_user_flow_shows_form(hass: HomeAssistant) -> None:
    """Step 1 shows the form when called with no user input."""
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R USB UART"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        result = await _start_user_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result.get("errors")


async def test_user_flow_invalid_system_code(hass: HomeAssistant) -> None:
    """Step 1 rejects a system code that fails validate_system_code."""
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R USB UART"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={
                CONF_SERIAL_PORT: MOCK_PORT,
                CONF_DEVICE_CODE: "BADHEX!",  # not a valid system code
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert CONF_DEVICE_CODE in result["errors"]
    assert result["errors"][CONF_DEVICE_CODE] == "invalid_system_code"


async def test_user_flow_port_not_found(hass: HomeAssistant) -> None:
    """Step 1 shows cannot_connect when the port does not exist."""
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with (
        patch("serial.tools.list_ports.comports", return_value=[mock_port]),
        patch(
            "custom_components.duofern.config_flow._check_serial_port",
            return_value=False,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={
                CONF_SERIAL_PORT: "/dev/ttyUSB99",
                CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"][CONF_SERIAL_PORT] == "cannot_connect"


async def test_user_flow_port_check_exception(hass: HomeAssistant) -> None:
    """Step 1 shows unknown error when port check raises."""
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with (
        patch("serial.tools.list_ports.comports", return_value=[mock_port]),
        patch(
            "custom_components.duofern.config_flow._check_serial_port",
            side_effect=OSError("permission denied"),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={
                CONF_SERIAL_PORT: MOCK_PORT,
                CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "unknown"


async def test_user_flow_no_ports_available(hass: HomeAssistant) -> None:
    """Step 1 renders a free-text field when no serial ports are detected."""
    with patch("serial.tools.list_ports.comports", return_value=[]):
        result = await _start_user_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


# ---------------------------------------------------------------------------
# User flow — step 2 (devices)
# ---------------------------------------------------------------------------


async def _complete_step1(hass: HomeAssistant):
    """Run step 1 successfully and return the flow_id."""
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with (
        patch("serial.tools.list_ports.comports", return_value=[mock_port]),
        patch(
            "custom_components.duofern.config_flow._check_serial_port",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={
                CONF_SERIAL_PORT: MOCK_PORT,
                CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            },
        )
    assert result["step_id"] == "devices"
    return result["flow_id"]


async def test_devices_step_shows_form(hass: HomeAssistant) -> None:
    """Step 2 shows the devices form after step 1 succeeds."""
    flow_id = await _complete_step1(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, user_input=None)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "devices"


async def test_devices_step_empty_input(hass: HomeAssistant) -> None:
    """Step 2 rejects empty device list."""
    flow_id = await _complete_step1(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input={CONF_PAIRED_DEVICES: ""}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "devices"
    assert result["errors"][CONF_PAIRED_DEVICES] == "no_devices"


async def test_devices_step_invalid_code(hass: HomeAssistant) -> None:
    """Step 2 rejects an invalid device code."""
    flow_id = await _complete_step1(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, user_input={CONF_PAIRED_DEVICES: "ZZZZZZ"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "devices"
    assert result["errors"][CONF_PAIRED_DEVICES] == "invalid_device_code"


async def test_full_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """Complete user flow creates a config entry with correct data."""
    flow_id = await _complete_step1(hass)

    with patch(
        "custom_components.duofern.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={CONF_PAIRED_DEVICES: MOCK_DEVICE_CODE_COVER},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == f"DuoFern ({MOCK_SYSTEM_CODE})"
    data = result["data"]
    assert data[CONF_SERIAL_PORT] == MOCK_PORT
    assert data[CONF_DEVICE_CODE] == MOCK_SYSTEM_CODE
    assert MOCK_DEVICE_CODE_COVER in data[CONF_PAIRED_DEVICES]


async def test_full_user_flow_multiple_devices(hass: HomeAssistant) -> None:
    """Multiple comma-separated device codes are all parsed and stored."""
    flow_id = await _complete_step1(hass)

    with patch("custom_components.duofern.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_PAIRED_DEVICES: f"{MOCK_DEVICE_CODE_COVER}, {MOCK_DEVICE_CODE_SWITCH}"
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    devices = result["data"][CONF_PAIRED_DEVICES]
    assert MOCK_DEVICE_CODE_COVER in devices
    assert MOCK_DEVICE_CODE_SWITCH in devices


async def test_full_user_flow_deduplicates_devices(hass: HomeAssistant) -> None:
    """Duplicate device codes entered by the user are deduplicated."""
    flow_id = await _complete_step1(hass)

    with patch("custom_components.duofern.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id,
            user_input={
                CONF_PAIRED_DEVICES: (
                    f"{MOCK_DEVICE_CODE_COVER}, {MOCK_DEVICE_CODE_COVER}"
                )
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    devices = result["data"][CONF_PAIRED_DEVICES]
    assert devices.count(MOCK_DEVICE_CODE_COVER) == 1


# ---------------------------------------------------------------------------
# Unique entry enforcement
# ---------------------------------------------------------------------------


async def test_abort_if_already_configured(hass: HomeAssistant) -> None:
    """Flow aborts when the same system code is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
        },
        version=2,
    )
    entry.add_to_hass(hass)

    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with (
        patch("serial.tools.list_ports.comports", return_value=[mock_port]),
        patch(
            "custom_components.duofern.config_flow._check_serial_port",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={
                CONF_SERIAL_PORT: MOCK_PORT,
                CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            },
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# USB discovery flow
# ---------------------------------------------------------------------------


async def test_usb_discovery_flow(hass: HomeAssistant) -> None:
    """USB discovery pre-fills the port and continues to user step."""
    discovery_info = usb.UsbServiceInfo(
        device=MOCK_PORT,
        vid="0403",
        pid="6001",
        serial_number="ABCD1234",
        description="DuoFern USB-Stick",
        manufacturer="Rademacher",
    )

    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "usb"},
            data=discovery_info,
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_usb_discovery_abort_if_already_configured(
    hass: HomeAssistant,
) -> None:
    """USB discovery aborts when the USB serial number is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ABCD1234",
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        version=2,
    )
    entry.add_to_hass(hass)

    discovery_info = usb.UsbServiceInfo(
        device=MOCK_PORT,
        vid="0403",
        pid="6001",
        serial_number="ABCD1234",
        description="DuoFern USB-Stick",
        manufacturer="Rademacher",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "usb"},
        data=discovery_info,
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_usb_discovery_no_serial_number(hass: HomeAssistant) -> None:
    """USB discovery without serial number still proceeds to user step."""
    discovery_info = usb.UsbServiceInfo(
        device=MOCK_PORT,
        vid="0403",
        pid="6001",
        serial_number=None,
        description="DuoFern USB-Stick",
        manufacturer="Rademacher",
    )

    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "usb"},
            data=discovery_info,
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


# ---------------------------------------------------------------------------
# Integration discovery (auto-discover) flow
# ---------------------------------------------------------------------------


async def test_integration_discovery_shows_confirm(hass: HomeAssistant) -> None:
    """Integration discovery presents a confirm form."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={
            "device_hex": MOCK_DEVICE_CODE_COVER,
            "device_name": "RolloTron Standard",
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_discovery"


async def test_integration_discovery_confirm_adds_device(hass: HomeAssistant) -> None:
    """Confirming integration discovery adds device to paired list."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={
            "device_hex": MOCK_DEVICE_CODE_COVER,
            "device_name": "RolloTron Standard",
            "entry_id": entry.entry_id,
        },
    )

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload",
        new_callable=AsyncMock,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "device_added"
    assert MOCK_DEVICE_CODE_COVER in entry.data[CONF_PAIRED_DEVICES]


async def test_integration_discovery_abort_duplicate(hass: HomeAssistant) -> None:
    """Second discovery flow for the same device is aborted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        version=2,
    )
    entry.add_to_hass(hass)

    # First flow — should open
    result1 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={
            "device_hex": MOCK_DEVICE_CODE_COVER,
            "device_name": "RolloTron Standard",
            "entry_id": entry.entry_id,
        },
    )
    assert result1["type"] == FlowResultType.FORM

    # Second flow for same device — should abort (already_in_progress or already_configured)
    result2 = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={
            "device_hex": MOCK_DEVICE_CODE_COVER,
            "device_name": "RolloTron Standard",
            "entry_id": entry.entry_id,
        },
    )
    assert result2["type"] == FlowResultType.ABORT


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_flow_shows_form(hass: HomeAssistant) -> None:
    """Options flow shows the form pre-filled with current devices."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
        },
        options={CONF_AUTO_DISCOVER: False},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_updates_devices(hass: HomeAssistant) -> None:
    """Options flow saves new device list and auto_discover flag."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
        },
        options={CONF_AUTO_DISCOVER: False},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    with patch("custom_components.duofern.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_PAIRED_DEVICES: f"{MOCK_DEVICE_CODE_COVER}, {MOCK_DEVICE_CODE_SWITCH}",
                CONF_AUTO_DISCOVER: True,
            },
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert MOCK_DEVICE_CODE_COVER in entry.data[CONF_PAIRED_DEVICES]
    assert MOCK_DEVICE_CODE_SWITCH in entry.data[CONF_PAIRED_DEVICES]
    assert entry.options[CONF_AUTO_DISCOVER] is True


async def test_options_flow_empty_device_list(hass: HomeAssistant) -> None:
    """Options flow rejects an empty device list."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
        },
        options={CONF_AUTO_DISCOVER: False},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_PAIRED_DEVICES: "", CONF_AUTO_DISCOVER: False},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_PAIRED_DEVICES] == "no_devices"


async def test_options_flow_invalid_device_code(hass: HomeAssistant) -> None:
    """Options flow rejects invalid device codes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
        },
        options={CONF_AUTO_DISCOVER: False},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_PAIRED_DEVICES: "GGGGGG", CONF_AUTO_DISCOVER: False},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_PAIRED_DEVICES] == "invalid_device_code"


# ---------------------------------------------------------------------------
# _check_serial_port — internal branches
# ---------------------------------------------------------------------------


def test_check_serial_port_returns_false_when_path_missing() -> None:
    """_check_serial_port returns False immediately when the path does not exist."""
    with patch(
        "custom_components.duofern.config_flow.os.path.exists", return_value=False
    ):
        result = _check_serial_port("/dev/ttyUSB99")
    assert result is False


def test_check_serial_port_returns_false_on_serial_exception() -> None:
    """_check_serial_port returns False when serial.Serial raises SerialException."""
    with (
        patch(
            "custom_components.duofern.config_flow.os.path.exists", return_value=True
        ),
        patch(
            "serial.Serial",
            side_effect=serial.SerialException("port busy"),
        ),
    ):
        result = _check_serial_port("/dev/ttyUSB0")
    assert result is False


def test_check_serial_port_returns_false_on_generic_exception() -> None:
    """_check_serial_port returns False when serial.Serial raises a generic Exception."""
    with (
        patch(
            "custom_components.duofern.config_flow.os.path.exists", return_value=True
        ),
        patch(
            "serial.Serial",
            side_effect=PermissionError("no access"),
        ),
    ):
        result = _check_serial_port("/dev/ttyUSB0")
    assert result is False


def test_check_serial_port_returns_true_on_success() -> None:
    """_check_serial_port opens and closes the port then returns True."""
    mock_ser = MagicMock()
    with (
        patch(
            "custom_components.duofern.config_flow.os.path.exists", return_value=True
        ),
        patch("serial.Serial", return_value=mock_ser),
    ):
        result = _check_serial_port("/dev/ttyUSB0")
    assert result is True
    mock_ser.close.assert_called_once()


# ---------------------------------------------------------------------------
# async_step_confirm_discovery — edge cases
# ---------------------------------------------------------------------------


async def test_confirm_discovery_entry_none_still_aborts(
    hass: HomeAssistant,
) -> None:
    """Confirming discovery when entry_id doesn't exist still returns device_added."""
    # Use a nonexistent entry_id — hass.config_entries.async_get_entry returns None
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={
            "device_hex": MOCK_DEVICE_CODE_COVER,
            "device_name": "RolloTron Standard",
            "entry_id": "nonexistent-entry-id",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_discovery"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "device_added"


async def test_confirm_discovery_device_already_paired_skips_update(
    hass: HomeAssistant,
) -> None:
    """Confirming discovery for a device already in paired list skips the update."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],  # already paired
        },
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "integration_discovery"},
        data={
            "device_hex": MOCK_DEVICE_CODE_COVER,  # same device already in list
            "device_name": "RolloTron Standard",
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "device_added"
    # Device count must be unchanged — no duplicate added
    assert entry.data[CONF_PAIRED_DEVICES].count(MOCK_DEVICE_CODE_COVER) == 1


# ---------------------------------------------------------------------------
# USB discovery — discovered port not in comports list
# ---------------------------------------------------------------------------


async def test_usb_discovery_adds_undiscovered_port_to_list(
    hass: HomeAssistant,
) -> None:
    """When the discovered USB port is not in comports, it is still added to the schema."""
    discovered_port = "/dev/ttyUSB99"  # NOT the same as MOCK_PORT
    discovery_info = usb.UsbServiceInfo(
        device=discovered_port,
        vid="0403",
        pid="6001",
        serial_number=None,
        description="DuoFern USB-Stick",
        manufacturer="Rademacher",
    )

    # comports returns MOCK_PORT which is different from discovered_port
    mock_port = MagicMock()
    mock_port.device = MOCK_PORT
    mock_port.description = "FT232R"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "usb"},
            data=discovery_info,
        )

    # The flow should still present the user form (port was added to the list)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
