"""Light platform for Ilumi Bluetooth bulbs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGBW_COLOR,
    EFFECT_OFF,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_ADDRESS,
    CONF_MODEL,
    CONF_NETWORK_KEY,
    DOMAIN,
    EFFECT_SCENE_INDEX,
    MODEL_A19,
    MODEL_ICONS,
)
from .effects import EFFECT_CANDLE, EFFECT_LIST, EFFECT_NAMES, EFFECTS
from .manager import IlumiManager, Packet
from .protocol import (
    candle_mode,
    normalize_for_bulb,
    pattern_packets,
    set_color,
    start_pattern,
)

_LOGGER = logging.getLogger(__name__)

# What a bulb shows when it gets power: bright white, no startup animation
# once it is set up. Home Assistant adopts this state when the bulb comes
# back, so Adaptive Lighting sees an "on" light and sets the right colour.
POWER_UP_RGBW = (0, 0, 0, 255)
POWER_UP_BRIGHTNESS = 255

# Home Assistant only calls our advertisement callback when an advertisement
# differs from the previous one, so a bulb that comes back with the same data
# would never be noticed. This check asks directly instead.
PRESENCE_CHECK_SECONDS = 15


PARALLEL_UPDATES = 0  # commands to different bulbs may run at the same time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one light per bulb sub-entry."""
    manager: IlumiManager = hass.data[DOMAIN]["manager"]
    for subentry_id, subentry in entry.subentries.items():
        async_add_entities(
            [IlumiLight(manager, entry, subentry)], config_subentry_id=subentry_id
        )


class IlumiLight(LightEntity, RestoreEntity):
    """An Ilumi bulb. State is assumed, the bulb cannot be read back cheaply."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.RGBW
    _attr_supported_color_modes = {ColorMode.RGBW}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = EFFECT_LIST

    def __init__(
        self, manager: IlumiManager, entry: ConfigEntry, subentry: ConfigSubentry
    ) -> None:
        self._manager = manager
        self._address: str = subentry.data[CONF_ADDRESS]
        self._network_key: int = entry.data[CONF_NETWORK_KEY]
        model: str = subentry.data.get(CONF_MODEL, MODEL_A19)
        self._attr_unique_id = format_mac(self._address)
        self._attr_icon = MODEL_ICONS.get(model)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            connections={(CONNECTION_BLUETOOTH, self._address)},
            manufacturer="Ilumi",
            model=model,
            name=subentry.title,
        )
        self._attr_is_on = False
        self._attr_effect: str | None = None
        self._want_effect: str | None = None
        self._attr_brightness = 255
        self._attr_rgbw_color = (255, 255, 255, 0)
        # What the user asked for most recently. The attributes above only
        # change once the bulb was really sent the command.
        self._want_on = False
        self._want_brightness = 255
        self._want_rgbw: tuple[int, int, int, int] = (255, 255, 255, 0)
        self._attr_available = True
        self._generation = 0
        self._lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Restore the last known state."""
        await super().async_added_to_hass()
        self._attr_available = bluetooth.async_address_present(
            self.hass, self._address, connectable=True
        )
        self.async_on_remove(
            bluetooth.async_track_unavailable(
                self.hass, self._async_bulb_gone, self._address, connectable=True
            )
        )
        self.async_on_remove(
            bluetooth.async_register_callback(
                self.hass,
                self._async_bulb_seen,
                BluetoothCallbackMatcher(address=self._address, connectable=True),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._async_check_presence,
                timedelta(seconds=PRESENCE_CHECK_SECONDS),
            )
        )
        last = await self.async_get_last_state()
        if last is None:
            return
        self._attr_is_on = last.state == STATE_ON
        brightness = last.attributes.get(ATTR_BRIGHTNESS)
        if brightness is not None:
            self._attr_brightness = int(brightness)
        rgbw = last.attributes.get(ATTR_RGBW_COLOR)
        if rgbw:
            self._attr_rgbw_color = tuple(int(v) for v in rgbw)  # type: ignore[assignment]
        self._want_on = self._attr_is_on
        self._want_brightness = self._attr_brightness
        self._want_rgbw = self._attr_rgbw_color  # type: ignore[assignment]

    @callback
    def _async_check_presence(self, _now: datetime) -> None:
        """Safety net next to the two callbacks: ask whether the bulb is heard."""
        present = bluetooth.async_address_present(
            self.hass, self._address, connectable=True
        )
        if present and not self._attr_available:
            self._async_bulb_seen(None, None)
        elif not present and self._attr_available:
            self._async_bulb_gone(None)

    @callback
    def _async_bulb_gone(self, _info: Any) -> None:
        """No advertisements any more: the bulb lost power or is out of range."""
        if self._attr_available:
            _LOGGER.debug("Ilumi bulb %s is no longer seen", self._address)
            self._attr_available = False
            self.async_write_ha_state()

    @callback
    def _async_bulb_seen(self, _info: Any, _change: Any) -> None:
        """First advertisement after the bulb was gone: it just got power.

        A bulb that starts up is on and bright white, whatever it showed
        before, so Home Assistant takes over that state.
        """
        if self._attr_available:
            return
        _LOGGER.debug("Ilumi bulb %s is back, assuming it starts up white", self._address)
        self._attr_available = True
        self._attr_is_on = True
        self._attr_rgbw_color = POWER_UP_RGBW
        self._attr_brightness = POWER_UP_BRIGHTNESS
        self._want_on = True
        self._want_rgbw = POWER_UP_RGBW
        self._want_brightness = POWER_UP_BRIGHTNESS
        self._attr_effect = None
        self._want_effect = None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally with colour and brightness."""
        if ATTR_BRIGHTNESS in kwargs:
            self._want_brightness = int(kwargs[ATTR_BRIGHTNESS])
        if ATTR_RGBW_COLOR in kwargs:
            self._want_rgbw = tuple(int(v) for v in kwargs[ATTR_RGBW_COLOR])  # type: ignore[assignment]
            # A new colour ends a running effect.
            self._want_effect = None
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            self._want_effect = (
                None if effect in (None, EFFECT_OFF) else str(effect)
            )
        self._want_on = True
        await self._async_sync()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        self._want_on = False
        self._want_effect = None
        await self._async_sync()

    async def _async_sync(self) -> None:
        """Bring the bulb to the wanted state.

        Dragging a slider fires many calls in a row. Every call bumps a
        generation counter, and calls that were overtaken while waiting
        for the lock simply return, so the bulb only gets the latest value.
        """
        self._generation += 1
        generation = self._generation
        async with self._lock:
            if generation != self._generation:
                return
            want_on = self._want_on
            rgbw = self._want_rgbw
            brightness = self._want_brightness
            key = self._network_key

            # Colour and brightness alone switch the bulb on, like the SDK's own
            # scripts do. A separate TURN_ON made the bulb flash its default
            # white before the colour arrived. Off is brightness 0 for the
            # same reason, so on and off use the same command.
            effect = self._want_effect if want_on else None
            if effect is not None and effect != EFFECT_CANDLE and effect not in EFFECT_NAMES:
                _LOGGER.warning("Unknown effect %s ignored", effect)
                effect = self._want_effect = None
            if want_on:
                r, g, b, w, level = normalize_for_bulb(rgbw, brightness)
            else:
                r, g, b, w, level = 0, 0, 0, 0, 0
            if effect is None:
                packets: list[Packet] = [
                    (lambda seq: set_color(key, seq, r, g, b, w, level), True)
                ]
            elif effect == EFFECT_CANDLE:
                packets = [
                    (lambda seq: candle_mode(key, seq, r, g, b, w, level), True)
                ]
            else:
                frames = EFFECTS[EFFECT_NAMES[effect]]
                scale = brightness
                packets = [
                    (
                        lambda seq: pattern_packets(
                            key, seq, EFFECT_SCENE_INDEX, frames, scale
                        ),
                        True,
                    ),
                    (lambda seq: start_pattern(key, seq, EFFECT_SCENE_INDEX), True),
                ]

            try:
                await self._manager.async_send(self._address, packets)
            except HomeAssistantError:
                self._want_on = bool(self._attr_is_on)
                self._want_brightness = self._attr_brightness or 255
                self._want_rgbw = self._attr_rgbw_color  # type: ignore[assignment]
                self._want_effect = self._attr_effect
                raise

            self._attr_is_on = want_on
            self._attr_effect = effect
            if want_on:
                self._attr_rgbw_color = rgbw
                self._attr_brightness = brightness
            self.async_write_ha_state()
