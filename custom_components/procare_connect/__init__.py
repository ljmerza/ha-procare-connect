"""Procare Connect: daycare activity sensors and events for Home Assistant."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import ProcareClient
from .const import DOMAIN
from .coordinator import ProcareConfigEntry, ProcareCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ProcareConfigEntry) -> bool:
    """Set up Procare Connect from a config entry."""
    client = ProcareClient(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    coordinator = ProcareCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Just after local midnight: refresh so the daily counters start over.
    entry.async_on_unload(
        async_track_time_change(hass, coordinator.async_midnight, hour=0, minute=0, second=30)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ProcareConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ProcareConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a child's device once the child is no longer on the account."""
    kids = entry.runtime_data.data.kids if entry.runtime_data.data else {}
    return not any(domain == DOMAIN and ident in kids for domain, ident in device.identifiers)
