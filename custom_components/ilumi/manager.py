"""Bluetooth access to Ilumi bulbs.

By default only one bulb is connected at any time. That keeps the load on
the Bluetooth proxy at a single connection slot, no matter how many bulbs
are set up. The setting "Parallel connections" allows up to three bulbs to be
connected at once, which makes scenes with many bulbs faster. Home Assistant's
Bluetooth stack picks the best adapter or proxy for each connection by itself.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    CHAR_UUID,
    CHUNK_DONE_SECONDS,
    CHUNK_GAP_SECONDS,
    DOMAIN,
    COMMAND_GAP_SECONDS,
    IDLE_DISCONNECT_SECONDS,
    MAX_CONNECTIONS,
    SEQ_STORAGE_KEY,
    SEQ_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# A packet is built at send time, because the sequence number is only
# known once the packet is really next in line. A factory may return a
# list of packets (a chunked upload); it can then use the sequence numbers
# seq, seq+2, ... and the manager skips the ones it used.
PacketFactory = Callable[[int], "bytes | list[bytes]"]
Packet = tuple[PacketFactory, bool]  # (factory, write_with_response)


def _ignore_notification(_sender: Any, _data: bytearray) -> None:
    """The SDK subscribes to notifications, so we do too. Content is unused."""


class _Slot:
    """One connection that serves one bulb at a time."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.client: Any = None
        self.address: str | None = None
        self.idle_cancel: CALLBACK_TYPE | None = None
        self.pending = 0  # sends that wait for or hold this slot


class IlumiManager:
    """Owns the BLE connections and the shared sequence counter."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, SEQ_STORAGE_VERSION, SEQ_STORAGE_KEY)
        self._slots: list[_Slot] = [_Slot()]
        # The slot that serves a bulb, so one bulb never has two connections.
        self._assigned: dict[str, _Slot] = {}
        # One counter for all bulbs, like the SDK, which keeps a single
        # seq_num for the whole network.
        self._seq = 0

    def set_connections(self, count: int) -> None:
        """Set how many bulbs may be connected at once (used at setup)."""
        count = max(1, min(count, MAX_CONNECTIONS))
        while len(self._slots) < count:
            self._slots.append(_Slot())

    async def async_load(self) -> None:
        """Restore the sequence counter from storage."""
        data = await self._store.async_load()
        if data:
            self._seq = int(data.get("seq", 0)) & 0xFE

    @callback
    def _data_to_save(self) -> dict[str, int]:
        return {"seq": self._seq}

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 2) % 256
        self._store.async_delay_save(self._data_to_save, 10)
        return seq

    def _pick_slot(self, address: str) -> _Slot:
        """Choose the slot for a bulb. Runs without awaiting, so it is race free."""
        slot = self._assigned.get(address)
        if slot is not None:
            return slot
        free = [s for s in self._slots if s.pending == 0]
        # Prefer a slot that has no bulb yet, then one that is just idle.
        free.sort(key=lambda s: s.address is not None)
        slot = free[0] if free else min(self._slots, key=lambda s: s.pending)
        if slot.pending == 0:
            for known, owner in list(self._assigned.items()):
                if owner is slot:
                    del self._assigned[known]
        self._assigned[address] = slot
        return slot

    async def async_send(self, address: str, packets: list[Packet]) -> None:
        """Send packets to one bulb, one after the other.

        Raises HomeAssistantError if the bulb cannot be reached.
        """
        slot = self._pick_slot(address)
        slot.pending += 1
        try:
            async with slot.lock:
                await self._async_send_locked(slot, address, packets)
        finally:
            slot.pending -= 1

    async def _async_send_locked(
        self, slot: _Slot, address: str, packets: list[Packet]
    ) -> None:
        self._cancel_idle(slot)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                client = await self._async_ensure_connected(slot, address)
                previous_was_chunked = False
                for index, (factory, response) in enumerate(packets):
                    if index:
                        await asyncio.sleep(
                            CHUNK_DONE_SECONDS
                            if previous_was_chunked
                            else COMMAND_GAP_SECONDS
                        )
                    built = factory(self._next_seq())
                    items = built if isinstance(built, list) else [built]
                    if isinstance(built, list):
                        for _ in built:
                            self._next_seq()  # one number per chunk
                    for number, data in enumerate(items):
                        if number:
                            await asyncio.sleep(CHUNK_GAP_SECONDS)
                        await client.write_gatt_char(
                            CHAR_UUID, data, response=response
                        )
                    previous_was_chunked = len(items) > 1
                last_error = None
                break
            except (BleakError, asyncio.TimeoutError, OSError) as err:
                last_error = err
                _LOGGER.debug(
                    "Attempt %s to reach Ilumi bulb %s failed: %s",
                    attempt + 1,
                    address,
                    err,
                )
                await self._async_disconnect(slot)
        if last_error is not None:
            raise HomeAssistantError(
                f"Could not send command to Ilumi bulb {address}: {last_error}"
            ) from last_error
        self._schedule_idle_disconnect(slot)

    async def async_shutdown(self) -> None:
        """Drop all connections, used when the last entry is unloaded."""
        for slot in self._slots:
            async with slot.lock:
                self._cancel_idle(slot)
                await self._async_disconnect(slot)

    async def _async_ensure_connected(self, slot: _Slot, address: str) -> Any:
        if (
            slot.client is not None
            and slot.client.is_connected
            and slot.address == address
        ):
            return slot.client
        await self._async_disconnect(slot)
        device = bluetooth.async_ble_device_from_address(
            self._hass, address, connectable=True
        )
        if device is None:
            raise HomeAssistantError(
                f"Ilumi bulb {address} is not in range of any Bluetooth adapter or proxy"
            )
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            address,
            disconnected_callback=lambda c: self._on_disconnect(slot, c),
            max_attempts=3,
        )
        try:
            await client.start_notify(CHAR_UUID, _ignore_notification)
        except (BleakError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Could not subscribe to notifications on %s: %s", address, err)
        slot.client = client
        slot.address = address
        return client

    async def _async_disconnect(self, slot: _Slot) -> None:
        client, slot.client, slot.address = slot.client, None, None
        if client is None:
            return
        try:
            await client.disconnect()
        except (BleakError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Error while disconnecting: %s", err)

    def _on_disconnect(self, slot: _Slot, client: Any) -> None:
        if client is slot.client:
            _LOGGER.debug("Ilumi bulb %s disconnected", slot.address)
            slot.client = None
            slot.address = None

    def _schedule_idle_disconnect(self, slot: _Slot) -> None:
        self._cancel_idle(slot)

        async def _fired(_now: datetime) -> None:
            slot.idle_cancel = None
            async with slot.lock:
                await self._async_disconnect(slot)

        slot.idle_cancel = async_call_later(
            self._hass, IDLE_DISCONNECT_SECONDS, _fired
        )

    @callback
    def _cancel_idle(self, slot: _Slot) -> None:
        if slot.idle_cancel is not None:
            slot.idle_cancel()
            slot.idle_cancel = None


async def async_get_manager(hass: HomeAssistant) -> IlumiManager:
    """Return the one shared manager, creating it on first use."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock: asyncio.Lock = domain_data.setdefault("lock", asyncio.Lock())
    async with lock:
        if "manager" not in domain_data:
            manager = IlumiManager(hass)
            await manager.async_load()
            domain_data["manager"] = manager
        return domain_data["manager"]
