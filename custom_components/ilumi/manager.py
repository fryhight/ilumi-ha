"""Serialised Bluetooth access to Ilumi bulbs.

Only one bulb is connected at any time. That keeps the load on the
Bluetooth proxy at a single connection slot, no matter how many bulbs
are set up. Home Assistant's Bluetooth stack picks the best adapter or
proxy for the connection by itself.
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


class IlumiManager:
    """Owns the one active BLE connection and the shared sequence counter."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, SEQ_STORAGE_VERSION, SEQ_STORAGE_KEY)
        self._lock = asyncio.Lock()
        self._client: Any = None
        self._address: str | None = None
        self._idle_cancel: CALLBACK_TYPE | None = None
        # One counter for all bulbs, like the SDK, which keeps a single
        # seq_num for the whole network.
        self._seq = 0

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

    async def async_send(self, address: str, packets: list[Packet]) -> None:
        """Send packets to one bulb, one after the other.

        Raises HomeAssistantError if the bulb cannot be reached.
        """
        async with self._lock:
            self._cancel_idle()
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    client = await self._async_ensure_connected(address)
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
                    await self._async_disconnect()
            if last_error is not None:
                raise HomeAssistantError(
                    f"Could not send command to Ilumi bulb {address}: {last_error}"
                ) from last_error
            self._schedule_idle_disconnect()

    async def async_shutdown(self) -> None:
        """Drop the connection, used when the last entry is unloaded."""
        async with self._lock:
            self._cancel_idle()
            await self._async_disconnect()

    async def _async_ensure_connected(self, address: str) -> Any:
        if (
            self._client is not None
            and self._client.is_connected
            and self._address == address
        ):
            return self._client
        await self._async_disconnect()
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
            disconnected_callback=self._on_disconnect,
            max_attempts=3,
        )
        try:
            await client.start_notify(CHAR_UUID, _ignore_notification)
        except (BleakError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Could not subscribe to notifications on %s: %s", address, err)
        self._client = client
        self._address = address
        return client

    async def _async_disconnect(self) -> None:
        client, self._client, self._address = self._client, None, None
        if client is None:
            return
        try:
            await client.disconnect()
        except (BleakError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.debug("Error while disconnecting: %s", err)

    def _on_disconnect(self, client: Any) -> None:
        if client is self._client:
            _LOGGER.debug("Ilumi bulb %s disconnected", self._address)
            self._client = None
            self._address = None

    def _schedule_idle_disconnect(self) -> None:
        self._cancel_idle()
        self._idle_cancel = async_call_later(
            self._hass, IDLE_DISCONNECT_SECONDS, self._idle_fired
        )

    @callback
    def _cancel_idle(self) -> None:
        if self._idle_cancel is not None:
            self._idle_cancel()
            self._idle_cancel = None

    async def _idle_fired(self, _now: datetime) -> None:
        self._idle_cancel = None
        async with self._lock:
            await self._async_disconnect()


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
