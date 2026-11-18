"""Ilumi Bluetooth bulbs, controlled locally through Home Assistant's Bluetooth stack."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .manager import async_get_manager

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a bulb. The manager with the BLE connection is shared."""
    await async_get_manager(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a bulb, and drop the shared manager with the last one."""
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
