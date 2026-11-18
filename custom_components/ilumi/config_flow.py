"""Config flow for Ilumi Bluetooth bulbs."""
from __future__ import annotations

import random
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ADDRESS,
    CONF_NETWORK_KEY,
    CONF_NODE_ID,
    CONF_SETUP,
    DOMAIN,
    SETUP_GROUP_ID,
)
from .manager import async_get_manager
from .protocol import commission, set_color

_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")

# Option value for "type the address in myself". Cannot clash with an address.
MANUAL = "manual_entry"


def looks_like_ilumi(name: str | None) -> bool:
    """Recognise a bulb by its Bluetooth name, the same rule the SDK uses."""
    if not name:
        return False
    return "ilumi" in name.lower() or name.startswith("L0") or name.startswith("Nrdic")


def _parse_key(raw: str) -> int | None:
    """Accept the key as decimal or 0x-prefixed hex, return None if invalid."""
    text = raw.strip()
    try:
        value = int(text, 0)
    except ValueError:
        try:
            value = int(text, 10)
        except ValueError:
            return None
    return value if 0 <= value <= 0xFFFFFFFF else None


class IlumiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one bulb, picked from the bulbs in range or typed in by hand."""

    VERSION = 1

    def __init__(self) -> None:
        self._candidates: dict[str, BluetoothServiceInfoBleak] = {}
        self._address: str = ""
        self._default_name: str = ""
        # Only used when no bulb exists yet. Picked once so that a form that
        # is shown again after an error does not change the number.
        self._new_key = str(random.randint(1000, 999999))

    def _default_key(self) -> str:
        """All bulbs share one key: reuse the first bulb's, else a new one."""
        for entry in self._async_current_entries():
            return str(entry.data[CONF_NETWORK_KEY])
        return self._new_key

    def _next_node_id(self) -> int:
        """Node numbers just count up, like in the SDK's enroll.py."""
        used = [e.data.get(CONF_NODE_ID, 0) for e in self._async_current_entries()]
        return max(used, default=0) + 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a bulb from the ones that were heard nearby."""
        if user_input is not None:
            choice = user_input[CONF_ADDRESS]
            if choice == MANUAL:
                return await self.async_step_manual()
            info = self._candidates.get(choice)
            self._address = choice
            self._default_name = info.name if info is not None else ""
            return await self.async_step_details()

        configured = self._async_current_ids()
        self._candidates = {
            info.address: info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if looks_like_ilumi(info.name)
            and format_mac(info.address) not in configured
        }
        if not self._candidates:
            return await self.async_step_manual()

        options = [
            SelectOptionDict(
                value=address, label=f"{info.name} ({address}, {info.rssi} dBm)"
            )
            for address, info in sorted(
                self._candidates.items(), key=lambda item: item[1].rssi, reverse=True
            )
        ]
        options.append(SelectOptionDict(value=MANUAL, label="Enter address manually"))
        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name and key for a bulb that was picked from the list."""
        return await self._async_details("details", user_input, manual=False)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Address, name and key typed in by hand."""
        return await self._async_details("manual", user_input, manual=True)

    async def _async_details(
        self, step_id: str, user_input: dict[str, Any] | None, manual: bool
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_address = user_input[CONF_ADDRESS] if manual else self._address
            address = raw_address.strip().upper().replace("-", ":")
            key = _parse_key(user_input[CONF_NETWORK_KEY])
            if not _MAC_RE.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            if key is None:
                errors[CONF_NETWORK_KEY] = "invalid_key"
            setup = user_input.get(CONF_SETUP, False)
            if setup and key == 0:
                errors[CONF_NETWORK_KEY] = "key_zero"
            if not errors:
                await self.async_set_unique_id(format_mac(address))
                self._abort_if_unique_id_configured()
                node_id = self._next_node_id()
                if setup:
                    try:
                        await self._async_commission(address, key, node_id)
                    except HomeAssistantError:
                        errors["base"] = "cannot_connect"
                if not errors:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME].strip() or address,
                        data={
                            CONF_ADDRESS: address,
                            CONF_NETWORK_KEY: key,
                            CONF_NODE_ID: node_id,
                        },
                    )

        fields: dict[Any, Any] = {}
        if manual:
            fields[vol.Required(CONF_ADDRESS)] = str
        fields[vol.Required(CONF_NAME, default=self._default_name)] = str
        fields[vol.Required(CONF_NETWORK_KEY, default=self._default_key())] = str
        fields[vol.Required(CONF_SETUP, default=True)] = bool
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema(fields), errors=errors
        )

    async def _async_commission(self, address: str, key: int, node_id: int) -> None:
        """Write the network key into a (reset) bulb, then light it up.

        The second packet proves that the key works and shows the person
        that the right bulb was set up: it lights bright white.
        """
        manager = await async_get_manager(self.hass)
        await manager.async_send(
            address,
            [
                (lambda seq: commission(key, seq, node_id, SETUP_GROUP_ID), True),
                (lambda seq: set_color(key, seq, 0, 0, 0, 255, 255), True),
            ],
        )
