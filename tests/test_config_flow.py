"""Tests for the DuoFern config flow, options flow, reconfigure and discovery.

All flows run through the real Home Assistant flow manager. The serial port
check and the port list are patched, the integration setup is patched so no
stick is needed.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USB,
    SOURCE_USER,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.usb import UsbServiceInfo
from pytest_homeassistant.common import MockConfigEntry

from custom_components.duofern.config_flow import _parse_device_codes
from custom_components.duofern.const import (
    CONF_AUTO_DISCOVER,
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)

from .conftest import MOCK_DEVICE_CODE_COVER, MOCK_PORT, MOCK_SYSTEM_CODE

CHECK = "custom_components.duofern.config_flow.check_serial_connection"
OTHER_PORT = "/dev/ttyUSB1"
NETWORK_PORT = "socket://192.168.1.50:4001"

USB_INFO = UsbServiceInfo(
    device=MOCK_PORT,
    vid="0403",
    pid="6001",
    serial_number="WR04ZFP4",
    manufacturer="Rademacher",
    description="DuoFern USB-Stick",
)


@pytest.fixture(autouse=True)
def _flow_environment(
    enable_custom_integrations: None,
    mock_serial_comports: None,
    mock_setup_entry: None,
) -> Generator[None, None, None]:
    """Custom integrations on, one serial port listed, setup patched.

    The integration depends on the "usb" component; its setup is patched so
    the flows do not start USB scanning.
    """
    with patch("homeassistant.components.usb.async_setup", return_value=True):
        yield


def _option_values(result: dict, key: str = CONF_SERIAL_PORT) -> list[str]:
    """Return the dropdown option values of a selector field in a form."""
    for marker, field in result["data_schema"].schema.items():
        if marker == key:
            return [opt["value"] for opt in field.config["options"]]
    raise AssertionError(f"field {key} not in form")


def _default(result: dict, key: str):
    """Return the default value of a field in a form."""
    for marker in result["data_schema"].schema:
        if marker == key:
            return marker.default()
    raise AssertionError(f"field {key} not in form")


async def _start_user_flow(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def _to_devices_step(hass: HomeAssistant) -> dict:
    result = await _start_user_flow(hass)
    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: MOCK_PORT, CONF_DEVICE_CODE: MOCK_SYSTEM_CODE},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "devices"
    return result


# ---------------------------------------------------------------------------
# User step
# ---------------------------------------------------------------------------


async def test_user_form_lists_ports(hass: HomeAssistant) -> None:
    """The first form offers the detected serial port and has no errors."""
    result = await _start_user_flow(hass)
    assert result["errors"] == {}
    assert _option_values(result) == [MOCK_PORT]
    assert _default(result, CONF_SERIAL_PORT) == ""


async def test_full_flow_creates_entry(hass: HomeAssistant) -> None:
    """Port + system code, then device codes, creates the entry."""
    result = await _to_devices_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRED_DEVICES: "406b2d, 436C1A\n406B2D"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"DuoFern ({MOCK_SYSTEM_CODE})"
    assert result["data"] == {
        CONF_SERIAL_PORT: MOCK_PORT,
        CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
        CONF_PAIRED_DEVICES: ["406B2D", "436C1A"],
    }
    assert result["result"].unique_id == MOCK_SYSTEM_CODE


async def test_full_flow_without_devices(hass: HomeAssistant) -> None:
    """An empty device list is valid."""
    result = await _to_devices_step(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PAIRED_DEVICES] == []


async def test_user_input_is_normalised(hass: HomeAssistant) -> None:
    """Whitespace is stripped and the system code is upper-cased."""
    result = await _start_user_flow(hass)
    with patch(CHECK, return_value=True) as check:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: f"  {NETWORK_PORT} ", CONF_DEVICE_CODE: " 6f1a2b "},
        )
    check.assert_called_once_with(NETWORK_PORT)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["data"][CONF_SERIAL_PORT] == NETWORK_PORT
    assert result["data"][CONF_DEVICE_CODE] == "6F1A2B"


@pytest.mark.parametrize("code", ["123456", "6F1A2", "6F1A2B0", "6FXX2B", ""])
async def test_user_invalid_system_code(hass: HomeAssistant, code: str) -> None:
    """A system code that is not 6F + 4 hex digits is rejected."""
    result = await _start_user_flow(hass)
    with patch(CHECK, return_value=True) as check:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: MOCK_PORT, CONF_DEVICE_CODE: code}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_DEVICE_CODE: "invalid_system_code"}
    check.assert_not_called()

    # corrected input completes the flow
    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: MOCK_PORT, CONF_DEVICE_CODE: MOCK_SYSTEM_CODE},
        )
    assert result["step_id"] == "devices"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MOCK_SYSTEM_CODE


async def test_user_cannot_connect_then_recovers(hass: HomeAssistant) -> None:
    """A port that cannot be opened shows an error; a retry succeeds."""
    result = await _start_user_flow(hass)
    user_input = {CONF_SERIAL_PORT: MOCK_PORT, CONF_DEVICE_CODE: MOCK_SYSTEM_CODE}
    with patch(CHECK, return_value=False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SERIAL_PORT: "cannot_connect"}

    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    assert result["step_id"] == "devices"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MOCK_SYSTEM_CODE


async def test_user_unknown_error(hass: HomeAssistant) -> None:
    """An unexpected exception during the port check is reported as unknown."""
    result = await _start_user_flow(hass)
    with patch(CHECK, side_effect=RuntimeError("boom")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: MOCK_PORT, CONF_DEVICE_CODE: MOCK_SYSTEM_CODE},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}

    # the next attempt works and completes the flow
    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: MOCK_PORT, CONF_DEVICE_CODE: MOCK_SYSTEM_CODE},
        )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MOCK_SYSTEM_CODE


async def test_user_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The same system code cannot be set up twice."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_user_flow(hass)
    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SERIAL_PORT: OTHER_PORT, CONF_DEVICE_CODE: MOCK_SYSTEM_CODE},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Devices step
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codes", ["XYZ123", "406B2D, 12345", "406B2D 406B2D0"])
async def test_devices_invalid_code_then_recovers(
    hass: HomeAssistant, codes: str
) -> None:
    """An invalid device code keeps the form open; a valid list is accepted."""
    result = await _to_devices_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRED_DEVICES: codes}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "devices"
    assert result["errors"] == {CONF_PAIRED_DEVICES: "invalid_device_code"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PAIRED_DEVICES: MOCK_DEVICE_CODE_COVER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PAIRED_DEVICES] == [MOCK_DEVICE_CODE_COVER]


# ---------------------------------------------------------------------------
# USB discovery
# ---------------------------------------------------------------------------


async def test_usb_discovery_prefills_port(hass: HomeAssistant) -> None:
    """A discovered stick leads to the user step with its port pre-selected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USB}, data=USB_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert _default(result, CONF_SERIAL_PORT) == MOCK_PORT


async def test_usb_discovery_adds_unlisted_port(hass: HomeAssistant) -> None:
    """A discovered port that is not in the port list is added to the dropdown."""
    info = UsbServiceInfo(
        device="/dev/serial/by-id/usb-Rademacher_DuoFern_USB-Stick_WR04ZFP4-if00",
        vid="0403",
        pid="6001",
        serial_number=None,
        manufacturer="Rademacher",
        description="DuoFern USB-Stick",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USB}, data=info
    )
    assert result["step_id"] == "user"
    assert _option_values(result) == [MOCK_PORT, info.device]
    assert _default(result, CONF_SERIAL_PORT) == info.device


async def test_usb_discovery_already_configured(hass: HomeAssistant) -> None:
    """A stick whose USB serial number is already known is not offered again."""
    MockConfigEntry(domain=DOMAIN, unique_id=USB_INFO.serial_number).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USB}, data=USB_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Reconfigure
# ---------------------------------------------------------------------------


async def test_reconfigure_form(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The reconfigure form shows the current port."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"]["current_port"] == MOCK_PORT
    assert _default(result, CONF_SERIAL_PORT) == MOCK_PORT
    assert _option_values(result) == [MOCK_PORT]


async def test_reconfigure_lists_current_network_port(hass: HomeAssistant) -> None:
    """A current port that is not a local port is still offered."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        version=2,
        data={
            CONF_SERIAL_PORT: NETWORK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert _option_values(result) == [MOCK_PORT, NETWORK_PORT]


async def test_reconfigure_new_port(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A new port is stored; the other entry data stays untouched."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with (
        patch(CHECK, return_value=True),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: f" {OTHER_PORT} "}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        CONF_SERIAL_PORT: OTHER_PORT,
        CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
        CONF_PAIRED_DEVICES: [MOCK_DEVICE_CODE_COVER],
    }
    # Changed data: the update listener reloads, no explicit reload.
    reload.assert_not_called()


async def test_reconfigure_same_port_reloads(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An unchanged port reloads the entry explicitly."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with (
        patch(CHECK, return_value=True),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: MOCK_PORT}
        )
    assert result["reason"] == "reconfigure_successful"
    reload.assert_called_once_with(mock_config_entry.entry_id)


async def test_reconfigure_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A port that cannot be opened keeps the form open and the data unchanged."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with patch(CHECK, return_value=False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: OTHER_PORT}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SERIAL_PORT: "cannot_connect"}
    assert mock_config_entry.data[CONF_SERIAL_PORT] == MOCK_PORT

    # a reachable port completes the reconfiguration
    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: OTHER_PORT}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_SERIAL_PORT] == OTHER_PORT


async def test_reconfigure_unknown_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An unexpected exception during the port check is reported as unknown."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    with patch(CHECK, side_effect=RuntimeError("boom")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: OTHER_PORT}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}
    assert mock_config_entry.data[CONF_SERIAL_PORT] == MOCK_PORT

    # the next attempt works and completes the reconfiguration
    with patch(CHECK, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_PORT: OTHER_PORT}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_SERIAL_PORT] == OTHER_PORT


# ---------------------------------------------------------------------------
# Integration discovery (unknown device seen by the coordinator)
# ---------------------------------------------------------------------------


async def _start_discovery(
    hass: HomeAssistant, entry_id: str, device_hex: str = "436C1A"
) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={
            "device_hex": device_hex,
            "device_name": "Universalaktor",
            "entry_id": entry_id,
        },
    )


async def test_discovery_confirm_adds_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Confirming a discovered device appends it to the paired devices."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_discovery(hass, mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm_discovery"
    assert result["description_placeholders"] == {"name": "Universalaktor (436C1A)"}

    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]
    assert flow["context"]["title_placeholders"] == {
        "name": "DuoFern Universalaktor (436C1A)",
        "device_name": "Universalaktor",
        "device_hex": "436C1A",
    }
    assert flow["context"]["unique_id"] == f"{mock_config_entry.entry_id}_436C1A"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "device_added"
    assert mock_config_entry.data[CONF_PAIRED_DEVICES] == [
        MOCK_DEVICE_CODE_COVER,
        "436C1A",
    ]


async def test_discovery_same_device_only_once(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A second frame of the same unknown device does not open a second flow."""
    mock_config_entry.add_to_hass(hass)
    await _start_discovery(hass, mock_config_entry.entry_id)
    result = await _start_discovery(hass, mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"
    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == 1


async def test_discovery_confirm_device_already_paired(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A device that is paired in the meantime is not added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_discovery(
        hass, mock_config_entry.entry_id, MOCK_DEVICE_CODE_COVER
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "device_added"
    assert mock_config_entry.data[CONF_PAIRED_DEVICES] == [MOCK_DEVICE_CODE_COVER]


async def test_discovery_confirm_entry_removed(hass: HomeAssistant) -> None:
    """Confirming after the config entry was removed does not fail."""
    result = await _start_discovery(hass, "entry_that_no_longer_exists")
    assert result["step_id"] == "confirm_discovery"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "device_added"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_form_prefilled(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The options form shows the current devices and the auto-discover flag."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _default(result, CONF_PAIRED_DEVICES) == MOCK_DEVICE_CODE_COVER
    assert _default(result, CONF_AUTO_DISCOVER) is False


async def test_options_form_empty_device_list(hass: HomeAssistant) -> None:
    """An entry without devices shows an empty field and the stored flag."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SYSTEM_CODE,
        version=2,
        data={
            CONF_SERIAL_PORT: MOCK_PORT,
            CONF_DEVICE_CODE: MOCK_SYSTEM_CODE,
            CONF_PAIRED_DEVICES: [],
        },
        options={CONF_AUTO_DISCOVER: True},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _default(result, CONF_PAIRED_DEVICES) == ""
    assert _default(result, CONF_AUTO_DISCOVER) is True


async def test_options_update_devices_and_auto_discover(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Saving stores the device list in data and the flag in options."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PAIRED_DEVICES: "406b2d 436c1a,436C1A", CONF_AUTO_DISCOVER: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_AUTO_DISCOVER: True}
    assert mock_config_entry.options == {CONF_AUTO_DISCOVER: True}
    assert mock_config_entry.data[CONF_PAIRED_DEVICES] == ["406B2D", "436C1A"]
    assert mock_config_entry.data[CONF_SERIAL_PORT] == MOCK_PORT


async def test_options_clear_device_list(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An empty device list is valid in the options flow."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PAIRED_DEVICES: "", CONF_AUTO_DISCOVER: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.data[CONF_PAIRED_DEVICES] == []


async def test_options_invalid_code(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An invalid device code keeps the form open and the data unchanged."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PAIRED_DEVICES: "406B2D, nothex", CONF_AUTO_DISCOVER: True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PAIRED_DEVICES: "invalid_device_code"}
    assert mock_config_entry.data[CONF_PAIRED_DEVICES] == [MOCK_DEVICE_CODE_COVER]
    assert mock_config_entry.options == {CONF_AUTO_DISCOVER: False}

    # a valid list completes the options flow
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PAIRED_DEVICES: "406B2D, 436C1A", CONF_AUTO_DISCOVER: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.data[CONF_PAIRED_DEVICES] == ["406B2D", "436C1A"]
    assert mock_config_entry.options == {CONF_AUTO_DISCOVER: True}


# ---------------------------------------------------------------------------
# _parse_device_codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("   ", []),
        ("406B2D", ["406B2D"]),
        ("406b2d", ["406B2D"]),
        ("406B2D,436C1A", ["406B2D", "436C1A"]),
        ("406B2D 436C1A", ["406B2D", "436C1A"]),
        ("406B2D\n436C1A\r\n49367C", ["406B2D", "436C1A", "49367C"]),
        (" 406B2D ,, 436C1A , ", ["406B2D", "436C1A"]),
        ("406B2D, 406b2d, 436C1A, 406B2D", ["406B2D", "436C1A"]),
    ],
)
def test_parse_device_codes(raw: str, expected: list[str]) -> None:
    """Codes are split on commas and whitespace, upper-cased and deduplicated."""
    assert _parse_device_codes(raw) == expected
