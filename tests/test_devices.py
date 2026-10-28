"""Tests for per-child devices: added, removed, and manual removal."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.procare_connect import async_remove_config_entry_device
from custom_components.procare_connect.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import ALEX, SAM, FakeProcare, activity

NEW_KID = "00000000-0000-4000-8000-000000000003"


def _device(
    device_registry: dr.DeviceRegistry, entry: MockConfigEntry, kid_id: str
) -> dr.DeviceEntry | None:
    """The entry's device for a child (works on 2026.3 and on 2026.10+)."""
    return next(
        (
            d
            for d in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
            if (DOMAIN, kid_id) in d.identifiers
        ),
        None,
    )


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_devices(
    hass: HomeAssistant, setup_entry: MockConfigEntry, device_registry: dr.DeviceRegistry
) -> None:
    """One device per child, named '<first name> daycare'."""
    devices = dr.async_entries_for_config_entry(device_registry, setup_entry.entry_id)
    assert sorted(d.name for d in devices) == ["Alex daycare", "Sam daycare"]
    alex = _device(device_registry, setup_entry, ALEX)
    assert alex.manufacturer == "Procare"
    assert alex.model == "Daily activities"


async def test_new_kid_added(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A child added to the account gets a device and entities; no backlog events."""
    procare.kids.append(
        {"id": NEW_KID, "first_name": "Jamie", "last_name": "Example", "is_signed_in": True}
    )
    procare.add(NEW_KID, activity(701, "bottle", "15:00", {"amount": "3", "bottle_consumed": ""}))
    await _refresh(hass, setup_entry)
    assert _device(device_registry, setup_entry, NEW_KID).name == "Jamie daycare"
    assert hass.states.get("sensor.jamie_daycare_bottles_today").state == "1"
    assert hass.states.get("event.jamie_daycare_activity").state == "unknown"

    procare.add(NEW_KID, activity(702, "bottle", "15:30", {"amount": "3", "bottle_consumed": ""}))
    await _refresh(hass, setup_entry)
    assert hass.states.get("event.jamie_daycare_activity").attributes["event_type"] == "bottle"


async def test_kid_removed(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A child missing from a non-empty kids list loses its device and entities."""
    procare.kids = [k for k in procare.kids if k["id"] != SAM]
    await _refresh(hass, setup_entry)
    assert _device(device_registry, setup_entry, SAM) is None
    assert entity_registry.async_get("sensor.sam_daycare_bottles_today") is None
    assert hass.states.get("sensor.sam_daycare_bottles_today") is None
    assert _device(device_registry, setup_entry, ALEX) is not None


async def test_empty_kids_list_prunes_nothing(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    procare: FakeProcare,
    device_registry: dr.DeviceRegistry,
) -> None:
    """An empty kids list is treated as a failed poll, not as every child leaving."""
    procare.kids = []
    await _refresh(hass, setup_entry)
    assert not setup_entry.runtime_data.last_update_success
    devices = dr.async_entries_for_config_entry(device_registry, setup_entry.entry_id)
    assert len(devices) == 2


async def test_manual_removal(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A current child's device can't be removed; a stale one can."""
    alex = _device(device_registry, setup_entry, ALEX)
    assert not await async_remove_config_entry_device(hass, setup_entry, alex)
    stale = device_registry.async_get_or_create(
        config_entry_id=setup_entry.entry_id, identifiers={(DOMAIN, NEW_KID)}
    )
    assert await async_remove_config_entry_device(hass, setup_entry, stale)
