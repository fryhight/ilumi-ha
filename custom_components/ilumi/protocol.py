"""Packet builders for the Ilumi BLE protocol.

Pure Python, no Home Assistant imports, so it can be tested on its own.
Layout (see PROTOCOL.md of the ilumi-sdk project):

    bytes 0-3  network key, uint32 little endian, plaintext
    byte  4    sequence number (even, +2 per command, wraps at 256)
    byte  5    command type
    bytes 6..  payload

All packets built here are at most 13 bytes, so no chunking is needed.
"""
from __future__ import annotations

import struct

CMD_SET_COLOR = 0
CMD_TURN_ON = 4
CMD_TURN_OFF = 5
CMD_COMMISSION_WITH_ID = 58


def commission(new_key: int, seq: int, node_id: int, group_id: int) -> bytes:
    """COMMISSION_WITH_ID: give a bulb its network key, node id and group.

    Exactly what the SDK's commission() sends: the header already carries
    the NEW key, and the payload is key (uint32), node id and group id
    (uint16 each).
    """
    return pack_header(new_key, seq, CMD_COMMISSION_WITH_ID) + struct.pack(
        "<IHH", new_key & 0xFFFFFFFF, node_id & 0xFFFF, group_id & 0xFFFF
    )


def _clamp(value: int) -> int:
    return max(0, min(255, int(value)))


def pack_header(network_key: int, seq: int, command: int) -> bytes:
    """Return the 6-byte header."""
    return struct.pack("<IBB", network_key & 0xFFFFFFFF, seq & 0xFF, command)


def turn_on(network_key: int, seq: int, delay_ms: int = 0, transit_ms: int = 0) -> bytes:
    """TURN_ON with optional delay and fade-in (milliseconds)."""
    return pack_header(network_key, seq, CMD_TURN_ON) + struct.pack(
        "<HH", delay_ms, transit_ms
    )


def turn_off(network_key: int, seq: int, delay_ms: int = 0, transit_ms: int = 0) -> bytes:
    """TURN_OFF with optional delay and fade-out (milliseconds)."""
    return pack_header(network_key, seq, CMD_TURN_OFF) + struct.pack(
        "<HH", delay_ms, transit_ms
    )


def set_color(
    network_key: int, seq: int, r: int, g: int, b: int, w: int, brightness: int
) -> bytes:
    """SET_COLOR (fast variant, meant to be written without response)."""
    return pack_header(network_key, seq, CMD_SET_COLOR) + struct.pack(
        "<7B", _clamp(r), _clamp(g), _clamp(b), _clamp(w), _clamp(brightness), 0, 0
    )


def normalize_for_bulb(rgbw, brightness):
    """Turn Home Assistant's rgbw tuple plus brightness into bulb values.

    Home Assistant lets the colour sliders scale the colour values themselves
    (dark red = small red value). The bulb ignores that size and only looks
    at its brightness byte, so the size is moved into that byte instead.
    Returns (r, g, b, w, level), with the largest colour channel at 255.
    """
    r, g, b, w = (_clamp(c) for c in rgbw)
    scale = max(r, g, b, w)
    if scale == 0:
        return 0, 0, 0, 0, 0
    r, g, b, w = ((c * 255 + scale // 2) // scale for c in (r, g, b, w))
    level = max(1, min(255, (_clamp(brightness) * scale + 127) // 255))
    return r, g, b, w, level
