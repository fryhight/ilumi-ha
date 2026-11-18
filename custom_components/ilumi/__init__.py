"""Ilumi Bluetooth bulbs, controlled locally through Home Assistant's Bluetooth stack.

One config entry holds the network key that all bulbs share. Every bulb is a
sub-entry of that entry and shows up as its own device.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import CONF_ADDRESS, DOMAIN
from .manager import async_get_manager

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Ilumi entry. The manager with the BLE connection is shared."""
    if CONF_ADDRESS in entry.data:
        # Version 0.2 and 0.3 made one entry per bulb. Those cannot be
        # converted without knowing the shared key, so they have to be added again.
        raise ConfigEntryError(
            "This is an entry from an older version, one entry per bulb. "
            "Delete it and add the Ilumi integration again, then add the bulb under it."
        )
    await async_get_manager(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when a bulb is added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload, and drop the shared manager with the last entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        others = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not others:
            manager = hass.data.get(DOMAIN, {}).pop("manager", None)
            if manager is not None:
                await manager.async_shutdown()
    return unloaded
