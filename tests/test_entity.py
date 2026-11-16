"""Tests for entity.py: the shared base entity and the device info helpers."""

from __future__ import annotations

import importlib
import inspect

from unittest.mock import AsyncMock, patch

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

from .common import (
    ALL_DEVICES,
    fake_stick,
    feed,
    make_entry,
    setup_entry,
    unload_entry,
)

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


def test_device_description_sw_version_only_when_known() -> None:
    """An unknown version is left out, so a stored one is not cleared."""
    code = DuoFernId.from_hex("40A1B2")
    assert "sw_version" not in device_description(_Coordinator(), code, "40A1B2")
    for unknown in (None, ""):
        info = device_description(_Coordinator(), code, "40A1B2", sw_version=unknown)
        assert "sw_version" not in info
    known = device_description(_Coordinator(), code, "40A1B2", sw_version="2.1")
    assert known["sw_version"] == "2.1"


def test_device_description_channel_device() -> None:
    """Channel devices: 8-digit identifier, name with the channel in words."""
    info = device_description(_Coordinator(), DuoFernId.from_hex("43A1B2"), "43A1B202")
    assert info["identifiers"] == {(DOMAIN, "43A1B202")}
    assert info["serial_number"] == "43A1B202"
    assert info["name"] == "DuoFern Universalaktor (43A1B2) Channel 02"


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

        # a reload (or restart) must not clear the stored version: the device
        # has not sent a status frame yet at that point
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.data.devices["46044B"].status.version is None
        assert device().sw_version == version
        await unload_entry(hass, entry)


async def test_devices_are_registered_before_the_platforms(hass: HomeAssistant) -> None:
    """Every paired device has its registry entry before any entity is created."""
    async with fake_stick():
        entry = make_entry(hass, ["40A1B2", "43A1B2", "69A1B2", "A0A1B2"])
        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ):
            await setup_entry(hass, entry)
        registry = dr.async_get(hass)
        names = {
            next(iter(d.identifiers))[1]: d.name
            for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert names == {
            "6F1A2B": "DuoFern Stick (6F1A2B)",
            "40A1B2": "DuoFern RolloTron Standard (40A1B2)",
            "43A1B201": "DuoFern Universalaktor (43A1B2) Channel 01",
            "43A1B202": "DuoFern Universalaktor (43A1B2) Channel 02",
            "69A1B200": "DuoFern Umweltsensor (69A1B2) Channel 00",
            "69A1B201": "DuoFern Umweltsensor (69A1B2) Channel 01",
            "A0A1B2": "DuoFern Handsender (6 Gruppen-48 Geraete) (A0A1B2)",
        }
        with patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entity_ids_carry_the_device_name(hass: HomeAssistant) -> None:
    """No entity id is derived from the config entry title.

    That happened when an entity that only links to its device was registered
    before the device had a name. The platforms load concurrently, so it
    depended on their order.
    """
    async with fake_stick():
        entry = make_entry(hass, ALL_DEVICES)
        await setup_entry(hass, entry)
        entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        assert len(entities) > 500
        wrong = [e.entity_id for e in entities if "duofern_" not in e.entity_id]
        assert not wrong, wrong[:5]
        # device names are the same whichever platform wrote last
        registry = dr.async_get(hass)
        for code in ("43A1B201", "43A1B202", "65A1B201", "74A1B201"):
            device = registry.async_get_device_by_identifier(
                (DOMAIN, code), entry.entry_id
            )
            assert device.name.endswith(f"({code[:6]}) Channel {code[6:]}"), device.name
        await unload_entry(hass, entry)


async def test_update_keeps_existing_entity_ids(hass: HomeAssistant) -> None:
    """An existing installation keeps every entity id, however it was formed.

    The registry holds a device under its old name and entities with ids from
    older versions: one derived from the 8-digit device name, one derived
    from the config entry title, one renamed by the user.
    """
    async with fake_stick():
        entry = make_entry(hass, ["43A1B2"])
        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)
        old_device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "43A1B202")},
            name="DuoFern Universalaktor (43A1B202)",
        )
        existing = {
            ("switch", "duofern_43A1B202"): "switch.duofern_universalaktor_43a1b202",
            (
                "button",
                "duofern_43A1B202_get_status",
            ): "button.mock_title_request_status",
            ("sensor", "duofern_43A1B202_last_seen"): "sensor.licht_esstisch_zuletzt",
        }
        for (domain, unique_id), old_id in existing.items():
            created = entity_registry.async_get_or_create(
                domain,
                DOMAIN,
                unique_id,
                config_entry=entry,
                device_id=old_device.id,
                suggested_object_id=old_id.split(".", 1)[1],
            )
            assert created.entity_id == old_id

        await setup_entry(hass, entry)

        for (domain, unique_id), old_id in existing.items():
            assert (
                entity_registry.async_get_entity_id(domain, DOMAIN, unique_id) == old_id
            )
            assert hass.states.get(old_id) is not None
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, "43A1B202"), entry.entry_id
        )
        assert device.id == old_device.id  # same device entry
        assert device.name == "DuoFern Universalaktor (43A1B2) Channel 02"
        await unload_entry(hass, entry)


async def test_update_keeps_a_device_name_set_by_the_user(hass: HomeAssistant) -> None:
    async with fake_stick():
        entry = make_entry(hass, ["43A1B2"])
        await setup_entry(hass, entry)
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, "43A1B202"), entry.entry_id
        )
        device_registry.async_update_device(device.id, name_by_user="Licht Esstisch")
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        device = device_registry.async_get(device.id)
        assert device.name_by_user == "Licht Esstisch"
        await unload_entry(hass, entry)
