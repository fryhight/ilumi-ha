"""Config flow for Ilumi Bluetooth bulbs.

The main flow creates the one entry that holds the network key all bulbs
share. Each bulb is then added as a sub-entry of that entry.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
    async_register_callback,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
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
    CONF_MODEL,
    CONF_NETWORK_KEY,
    CONF_NODE_ID,
    CONF_SETUP,
    DOMAIN,
    IDENTIFY_COLOR,
    MODEL_A19,
    MODELS,
    RESET_COLOR,
    SERVICE_UUID,
    SETUP_GROUP_ID,
    SUBENTRY_BULB,
)
from .manager import async_get_manager
from .protocol import commission, set_color

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")

# Option values that cannot clash with an address.
MANUAL = "manual_entry"
SHOW_ALL = "show_all"
# How many devices the "all devices" list shows, strongest signal first.
MAX_ALL_DEVICES = 30
# A bulb's name is in its scan response, which scanners only ask for when
# active scanning is requested. The list is built after this many seconds.
SCAN_SECONDS = 5


def looks_like_ilumi(name: str | None) -> bool:
    """Recognise a bulb by its Bluetooth name, the same rule the SDK uses."""
    if not name:
        return False
    return "ilumi" in name.lower() or name.startswith("L0") or name.startswith("Nrdic")


def advertises_service(info: BluetoothServiceInfoBleak) -> bool:
    """True if the device lists the Ilumi GATT service in its advertisement."""
    uuids = getattr(info, "service_uuids", None) or []
    return SERVICE_UUID in [str(u).lower() for u in uuids]


def has_name(info: BluetoothServiceInfoBleak) -> bool:
    """Home Assistant puts the address in place of a name that was not heard."""
    return bool(info.name) and info.name.upper() != info.address.upper()


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


def _model_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=m, label=m) for m in MODELS],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class IlumiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single Ilumi entry with the shared network key."""

    VERSION = 1

    def __init__(self) -> None:
        # Picked once so that a form shown again after an error keeps it.
        self._new_key = str(random.randint(1000, 999999))

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Each bulb is a sub-entry."""
        return {SUBENTRY_BULB: BulbSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the network key. All bulbs will share it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            key = _parse_key(user_input[CONF_NETWORK_KEY])
            if key is None:
                errors[CONF_NETWORK_KEY] = "invalid_key"
            elif key == 0:
                errors[CONF_NETWORK_KEY] = "key_zero"
            else:
                return self.async_create_entry(
                    title="Ilumi", data={CONF_NETWORK_KEY: key}
                )
        schema = vol.Schema(
            {vol.Required(CONF_NETWORK_KEY, default=self._new_key): str}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class BulbSubentryFlow(ConfigSubentryFlow):
    """Add or edit one bulb, picked from the bulbs in range or typed in."""

    def __init__(self) -> None:
        self._candidates: dict[str, BluetoothServiceInfoBleak] = {}
        self._address: str = ""
        self._default_name: str = ""
        self._scanned = False

    def _configured(self) -> set[str]:
        entry = self._get_entry()
        return {
            format_mac(sub.data[CONF_ADDRESS]) for sub in entry.subentries.values()
        }

    def _next_node_id(self) -> int:
        """Node numbers just count up, like in the SDK's enroll.py."""
        entry = self._get_entry()
        used = [sub.data.get(CONF_NODE_ID, 0) for sub in entry.subentries.values()]
        return max(used, default=0) + 1

    def _display_name(self, info: BluetoothServiceInfoBleak) -> str:
        if has_name(info):
            return info.name
        if advertises_service(info):
            return "Ilumi bulb"
        return "no name"

    def _heard(self) -> list[BluetoothServiceInfoBleak]:
        """Everything connectable that Home Assistant hears, strongest first."""
        configured = self._configured()
        infos = [
            info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if format_mac(info.address) not in configured
        ]
        return sorted(infos, key=lambda info: info.rssi, reverse=True)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick a bulb from the ones that were heard nearby.

        Bulbs are recognised by their name. If none is recognised, all
        devices that are heard are listed instead, so that the person can see
        what Home Assistant hears and pick the bulb by its address.
        """
        if user_input is not None:
            choice = user_input[CONF_ADDRESS]
            if choice == MANUAL:
                return await self.async_step_manual()
            if choice == SHOW_ALL:
                return await self._async_show_list(show_all=True)
            info = self._candidates.get(choice)
            self._address = choice
            if info is not None and has_name(info):
                self._default_name = info.name
            elif info is not None and advertises_service(info):
                self._default_name = "Ilumi"
            else:
                self._default_name = ""
            return await self.async_step_confirm()

        return await self._async_show_list(show_all=False)

    async def _async_scan(self) -> None:
        """Ask for active scanning for a few seconds, so that names are heard."""

        def _ignore(_info: BluetoothServiceInfoBleak, _change: Any) -> None:
            """Only the request for active scanning matters, not the data."""

        cancel = async_register_callback(
            self.hass,
            _ignore,
            BluetoothCallbackMatcher(connectable=True),
            BluetoothScanningMode.ACTIVE,
        )
        try:
            await asyncio.sleep(SCAN_SECONDS)
        finally:
            cancel()

    async def _async_show_list(self, show_all: bool) -> SubentryFlowResult:
        if not self._scanned:
            self._scanned = True
            await self._async_scan()
        heard = self._heard()
        _LOGGER.debug("Ilumi: %s connectable devices heard", len(heard))
        by_name = [info for info in heard if looks_like_ilumi(info.name)]
        by_service = [
            info for info in heard if advertises_service(info) and info not in by_name
        ]
        bulbs = by_name + by_service
        unnamed = [info for info in heard if not has_name(info)]
        if show_all:
            shown = heard[:MAX_ALL_DEVICES]
        elif bulbs:
            shown = bulbs
        else:
            # No bulb recognised. A bulb whose name was not heard looks like
            # any unnamed device, so those are offered, other named devices not.
            shown = unnamed
            show_all = not shown
            if show_all:
                shown = heard[:MAX_ALL_DEVICES]
        if not shown:
            return await self.async_step_manual()
        self._candidates = {info.address: info for info in shown}

        options = [
            SelectOptionDict(
                value=info.address,
                label=f"{self._display_name(info)} "
                f"({info.address}, {info.rssi} dBm)",
            )
            for info in shown
        ]
        if not show_all:
            options.append(
                SelectOptionDict(
                    value=SHOW_ALL,
                    label="Show all Bluetooth devices",
                )
            )
        options.append(
            SelectOptionDict(
                value=MANUAL,
                label="Enter address manually",
            )
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def _async_light(self, address: str, color: tuple[int, ...]) -> None:
        """Set a colour on a bulb that was just reset (network key 0)."""
        manager = await async_get_manager(self.hass)
        await manager.async_send(
            address, [(lambda seq: set_color(0, seq, *color), True)]
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Light the picked bulb up and ask whether it is the one meant."""
        if user_input is not None:
            if user_input["correct"]:
                return await self.async_step_details()
            try:
                await self._async_light(self._address, RESET_COLOR)
            except HomeAssistantError:
                pass  # best effort, the person chose another bulb anyway
            self._address = ""
            return await self._async_show_list(show_all=False)

        errors: dict[str, str] = {}
        try:
            await self._async_light(self._address, IDENTIFY_COLOR)
        except HomeAssistantError:
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required("correct", default=True): bool}),
            errors=errors,
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name, shape and setup for a bulb that was picked from the list."""
        return await self._async_details("details", user_input, manual=False)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Address, name, shape and setup typed in by hand."""
        return await self._async_details("manual", user_input, manual=True)

    async def _async_details(
        self, step_id: str, user_input: dict[str, Any] | None, manual: bool
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_address = user_input[CONF_ADDRESS] if manual else self._address
            address = raw_address.strip().upper().replace("-", ":")
            if not _MAC_RE.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif format_mac(address) in self._configured():
                return self.async_abort(reason="already_configured")
            if not errors:
                key = self._get_entry().data[CONF_NETWORK_KEY]
                node_id = self._next_node_id()
                if user_input.get(CONF_SETUP, False):
                    try:
                        await self._async_commission(address, key, node_id)
                    except HomeAssistantError:
                        errors["base"] = "cannot_connect"
                if not errors:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME].strip() or address,
                        data={
                            CONF_ADDRESS: address,
                            CONF_MODEL: user_input[CONF_MODEL],
                            CONF_NODE_ID: node_id,
                        },
                        unique_id=format_mac(address),
                    )

        fields: dict[Any, Any] = {}
        if manual:
            fields[vol.Required(CONF_ADDRESS)] = str
        fields[vol.Required(CONF_NAME, default=self._default_name)] = str
        fields[vol.Required(CONF_MODEL, default=MODEL_A19)] = _model_selector()
        fields[vol.Required(CONF_SETUP, default=True)] = bool
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change the name or the shape of a bulb."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME].strip() or subentry.title,
                data_updates={CONF_MODEL: user_input[CONF_MODEL]},
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=subentry.title): str,
                vol.Required(
                    CONF_MODEL, default=subentry.data.get(CONF_MODEL, MODEL_A19)
                ): _model_selector(),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

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
