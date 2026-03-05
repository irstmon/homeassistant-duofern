"""Config flow for DuoFern integration.

Provides a UI-based setup flow:
  Step 1: User enters serial port path and system code
  Step 2: User enters paired device codes (comma-separated)

USB auto-discovery is supported via manifest.json usb entry
(VID 0x0403, PID 0x6001, "DuoFern USB-Stick").

An options flow allows editing the device list after initial setup.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import serial.tools.list_ports  # type: ignore[import-untyped]
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    SOURCE_INTEGRATION_DISCOVERY,
)
from homeassistant.components import usb

from .const import (
    CONF_AUTO_DISCOVER,
    CONF_DEVICE_CODE,
    CONF_PAIRED_DEVICES,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from .protocol import validate_device_code, validate_system_code

_LOGGER = logging.getLogger(__name__)


class DuoFernConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for DuoFern."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_port: str | None = None
        self._user_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Serial port and system code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            serial_port = user_input[CONF_SERIAL_PORT]
            system_code = user_input[CONF_DEVICE_CODE].upper().strip()

            # Validate system code format
            if not validate_system_code(system_code):
                errors[CONF_DEVICE_CODE] = "invalid_system_code"
            else:
                # Check uniqueness by system code
                await self.async_set_unique_id(system_code)
                self._abort_if_unique_id_configured()

                # Try to verify the serial port exists
                try:
                    port_valid = await self.hass.async_add_executor_job(
                        _check_serial_port, serial_port
                    )
                    if not port_valid:
                        errors[CONF_SERIAL_PORT] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Error checking serial port")
                    errors["base"] = "unknown"

                if not errors:
                    # Save step 1 data and proceed to step 2
                    self._user_data = {
                        CONF_SERIAL_PORT: serial_port,
                        CONF_DEVICE_CODE: system_code,
                    }
                    return await self.async_step_devices()

        # Build the list of available serial ports for the dropdown
        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        port_list = {p.device: f"{p.device} ({p.description})" for p in ports}

        # If we have a discovered port, pre-select it
        default_port = self._discovered_port or ""
        if default_port and default_port not in port_list:
            port_list[default_port] = default_port

        # If no ports found, allow manual text entry
        if port_list:
            port_schema = vol.In(port_list)
        else:
            port_schema = str

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SERIAL_PORT, default=default_port): port_schema,
                vol.Required(CONF_DEVICE_CODE): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Collect paired device codes."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_codes = user_input.get(CONF_PAIRED_DEVICES, "")
            device_codes = _parse_device_codes(raw_codes)

            if not device_codes:
                errors[CONF_PAIRED_DEVICES] = "no_devices"
            else:
                # Validate each code
                invalid = [c for c in device_codes if not validate_device_code(c)]
                if invalid:
                    errors[CONF_PAIRED_DEVICES] = "invalid_device_code"
                else:
                    return self.async_create_entry(
                        title=f"DuoFern ({self._user_data[CONF_DEVICE_CODE]})",
                        data={
                            **self._user_data,
                            CONF_PAIRED_DEVICES: device_codes,
                        },
                    )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PAIRED_DEVICES): str,
            }
        )

        return self.async_show_form(
            step_id="devices",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_usb(
        self, discovery_info: usb.UsbServiceInfo
    ) -> ConfigFlowResult:
        """Handle USB auto-discovery.

        Triggered when a device matching our manifest.json usb entry is found:
        VID=0x0403, PID=0x6001, description contains "DuoFern USB-Stick"
        """
        _LOGGER.info(
            "USB device discovered: %s (VID=%s, PID=%s, serial=%s)",
            discovery_info.description,
            discovery_info.vid,
            discovery_info.pid,
            discovery_info.serial_number,
        )

        # Store the discovered port for the user step
        self._discovered_port = discovery_info.device

        # We still need the user to provide the system code and devices
        # So we proceed to the user step with the port pre-filled
        return await self.async_step_user()

    async def async_step_integration_discovery(
        self, discovery_info: dict
    ) -> ConfigFlowResult:
        """Handle a device discovered by the coordinator.

        Shown in HA's 'Entdeckt' / discovered inbox when auto_discover is
        enabled and an unknown but decodable DuoFern device sends a frame.
        The entry has a unique_id of '<entry_id>_<device_hex>' so HA
        ensures the same device only appears once in the inbox.
        """
        device_hex: str = discovery_info["device_hex"]
        device_name: str = discovery_info["device_name"]
        entry_id: str = discovery_info["entry_id"]

        # raise_on_progress=False: allow a new flow even if a previous
        # flow for this device was already in progress or aborted.
        await self.async_set_unique_id(
            f"{entry_id}_{device_hex}", raise_on_progress=False
        )
        self._abort_if_unique_id_configured()

        # Store for use in async_step_confirm
        self._discovered_device_hex = device_hex
        self._discovered_device_name = device_name
        self._discovered_entry_id = entry_id

        self.context["title_placeholders"] = {
            "device_name": device_name,
            "device_hex": device_hex,
        }
        return await self.async_step_confirm_discovery()

    async def async_step_confirm_discovery(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm adding the discovered device."""
        if user_input is not None:
            # Add device to existing config entry's paired list
            entry = self.hass.config_entries.async_get_entry(self._discovered_entry_id)
            if entry is not None:
                current: list[str] = list(entry.data.get(CONF_PAIRED_DEVICES, []))
                if self._discovered_device_hex not in current:
                    current.append(self._discovered_device_hex)
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_PAIRED_DEVICES: current},
                    )
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(entry.entry_id)
                    )
            return self.async_abort(reason="device_added")

        return self.async_show_form(
            step_id="confirm_discovery",
            description_placeholders={
                "device_name": self._discovered_device_name,
                "device_hex": self._discovered_device_hex,
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DuoFernOptionsFlow:
        """Return the options flow handler."""
        return DuoFernOptionsFlow(config_entry)


class DuoFernOptionsFlow(OptionsFlow):
    """Handle DuoFern options (add/remove paired devices)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the paired devices list."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_codes = user_input.get(CONF_PAIRED_DEVICES, "")
            device_codes = _parse_device_codes(raw_codes)

            if not device_codes:
                errors[CONF_PAIRED_DEVICES] = "no_devices"
            else:
                invalid = [c for c in device_codes if not validate_device_code(c)]
                if invalid:
                    errors[CONF_PAIRED_DEVICES] = "invalid_device_code"
                else:
                    # Update entry.data with new device list
                    auto_discover: bool = user_input.get(CONF_AUTO_DISCOVER, False)
                    # Update entry.data with new device list
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data={
                            **self._config_entry.data,
                            CONF_PAIRED_DEVICES: device_codes,
                        },
                    )
                    # Reload the integration to re-run init with new devices
                    await self.hass.config_entries.async_reload(
                        self._config_entry.entry_id
                    )
                    # async_create_entry(data=...) is what HA uses to persist
                    # entry.options — do NOT call async_update_entry for options
                    # as async_create_entry would overwrite it with {}.
                    return self.async_create_entry(
                        data={CONF_AUTO_DISCOVER: auto_discover}
                    )

        # Pre-fill with current device codes
        current_codes: list[str] = self._config_entry.data.get(CONF_PAIRED_DEVICES, [])
        default_value = ", ".join(current_codes) if current_codes else ""

        current_auto_discover: bool = self._config_entry.options.get(
            CONF_AUTO_DISCOVER, False
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PAIRED_DEVICES, default=default_value): str,
                vol.Required(CONF_AUTO_DISCOVER, default=current_auto_discover): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _parse_device_codes(raw: str) -> list[str]:
    """Parse a string of device codes into a clean uppercase list.

    Accepts comma-separated, space-separated, or newline-separated codes.
    Returns deduplicated list preserving order.
    """
    parts = re.split(r"[,\s]+", raw.strip())
    codes = [p.upper().strip() for p in parts if p.strip()]
    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _check_serial_port(port: str) -> bool:
    """Check if a serial port path exists and is accessible.

    Runs in executor thread (blocking I/O).
    """
    import os

    if not os.path.exists(port):
        _LOGGER.warning("Serial port does not exist: %s", port)
        return False

    try:
        import serial  # type: ignore[import-untyped]

        ser = serial.Serial(port, timeout=1)
        ser.close()
        return True
    except serial.SerialException as err:
        _LOGGER.warning("Cannot open serial port %s: %s", port, err)
        return False
    except Exception as err:
        _LOGGER.warning("Error checking serial port %s: %s", port, err)
        return False
