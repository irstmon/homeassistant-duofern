"""Tests for entity.py: the shared base entity and the device info helpers."""

from __future__ import annotations

import importlib
import inspect

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity

from custom_components.duofern.const import DOMAIN
from custom_components.duofern.entity import (
    DuoFernEntity,
    device_description,
    device_link,
)
from custom_components.duofern.protocol import DuoFernId

from .common import fake_stick, feed, make_entry, setup_entry, unload_entry

PLATFORMS = [
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "event",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
]


class _Coordinator:
    stick_device_id = "stick-device-id"


def test_device_link_only_refers_to_the_device() -> None:
    assert device_link("40A1B2") == {"identifiers": {(DOMAIN, "40A1B2")}}


def test_device_description_default_name() -> None:
    info = device_description(_Coordinator(), DuoFernId.from_hex("40A1B2"), "40A1B2")
    assert info == {
        "identifiers": {(DOMAIN, "40A1B2")},
        "name": "DuoFern RolloTron Standard (40A1B2)",
        "manufacturer": "Rademacher",
        "model": "RolloTron Standard",
        "serial_number": "40A1B2",
        "via_device_id": "stick-device-id",
    }


def test_device_description_sw_version_only_when_given() -> None:
    """Not given: key absent. None: key present, "not known yet"."""
    code = DuoFernId.from_hex("40A1B2")
    assert "sw_version" not in device_description(_Coordinator(), code, "40A1B2")
    unknown = device_description(_Coordinator(), code, "40A1B2", sw_version=None)
    assert "sw_version" in unknown and unknown["sw_version"] is None
    known = device_description(_Coordinator(), code, "40A1B2", sw_version="2.1")
    assert known["sw_version"] == "2.1"


def test_device_description_channel_device_and_custom_name() -> None:
    code = DuoFernId.from_hex("43A1B2")
    info = device_description(
        _Coordinator(), code, "43A1B202", name="DuoFern Universalaktor (43A1B2) Ch 2"
    )
    assert info["identifiers"] == {(DOMAIN, "43A1B202")}
    assert info["serial_number"] == "43A1B202"
    assert info["name"] == "DuoFern Universalaktor (43A1B2) Ch 2"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_entity_class_uses_the_base_entity(platform: str) -> None:
    """All entity classes of a platform derive from DuoFernEntity."""
    module = importlib.import_module(f"custom_components.duofern.{platform}")
    classes = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__ and issubclass(cls, Entity)
    ]
    assert classes, platform
    for cls in classes:
        assert issubclass(cls, DuoFernEntity), cls.__name__


async def test_firmware_version_reaches_the_device_registry(
    hass: HomeAssistant,
) -> None:
    """The version of a status frame is written to the device entry, once."""
    async with fake_stick():
        entry = make_entry(hass, ["46044B"])
        coordinator = await setup_entry(hass, entry)
        registry = dr.async_get(hass)

        def device():
            return registry.async_get_device_by_identifier(
                (DOMAIN, "46044B"), entry.entry_id
            )

        assert device().sw_version is None
        # real status frame of a Steckdosenaktor, firmware 3.0
        feed(coordinator, "0FFF0F2200000001753000E430001146044B6F5C7E01")
        await hass.async_block_till_done()
        version = coordinator.data.devices["46044B"].status.version
        assert version and device().sw_version == version

        # has_entity_name comes from the base class: every entity of the
        # integration is registered with it
        entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        assert entities and all(e.has_entity_name for e in entities)

        # after a reload the version is (again) there with the next status frame
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        feed(entry.runtime_data, "0FFF0F2200000001753000E430001146044B6F5C7E01")
        await hass.async_block_till_done()
        assert device().sw_version == version
        await unload_entry(hass, entry)
