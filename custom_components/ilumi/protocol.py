"""Packet builders for the Ilumi BLE protocol.

Pure Python, no Home Assistant imports, so it can be tested on its own.
Layout (see PROTOCOL.md of the ilumi-sdk project):

    bytes 0-3  network key, uint32 little endian, plaintext
    byte  4    sequence number (even, +2 per command, wraps at 256)
    byte  5    command type
    bytes 6..  payload

Single packets are at most 13 bytes. Only the colour pattern upload is longer
than one 20 byte write and is split into chunks (see pattern_packets).
"""
from __future__ import annotations

import struct

CMD_SET_COLOR = 0
CMD_TURN_ON = 4
CMD_TURN_OFF = 5
CMD_SET_COLOR_PATTERN = 7
CMD_START_COLOR_PATTERN = 8
CMD_CANDLE_MODE = 35
CMD_DATA_CHUNK = 52
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


def candle_mode(
    network_key: int, seq: int, r: int, g: int, b: int, w: int, brightness: int
) -> bytes:
    """CANDLE_MODE: flickering light in the given colour."""
    return pack_header(network_key, seq, CMD_CANDLE_MODE) + struct.pack(
        "<7B", _clamp(r), _clamp(g), _clamp(b), _clamp(w), _clamp(brightness), 0, 0
    )


def start_pattern(network_key: int, seq: int, scene_idx: int) -> bytes:
    """START_COLOR_PATTERN for a pattern that is already stored in the bulb."""
    return pack_header(network_key, seq, CMD_START_COLOR_PATTERN) + struct.pack(
        "<B", scene_idx
    )


def pattern_packets(
    network_key: int,
    seq: int,
    scene_idx: int,
    frames,
    brightness_scale: int = 255,
    repeatable: int = 255,
    start_now: int = 1,
) -> list[bytes]:
    """Upload a colour pattern (a list of frames) and return the packets to write.

    Same layout as the SDK's set_color_pattern. The whole message is longer
    than 20 bytes, so it travels as DATA_CHUNK packets: each carries the
    total length, its offset and 10 bytes of the message (zero padded). The
    packets use consecutive sequence numbers, seq, seq+2, ... : the first
    one is for the message itself, the others for its chunks.

    brightness_scale (0-255) dims every frame, 255 leaves them as they are.
    """
    frame_bytes = bytearray()
    for f in frames:
        level = _clamp(f.get("brightness", 255) * _clamp(brightness_scale) // 255)
        frame_bytes += struct.pack(
            "<6B",
            _clamp(f.get("r", 0)),
            _clamp(f.get("g", 0)),
            _clamp(f.get("b", 0)),
            _clamp(f.get("w", 0)),
            level,
            0,
        )
        frame_bytes += struct.pack(
            "<IIBBBB", f.get("sustain_ms", 500), f.get("transit_ms", 100), 0, 0, 0, 0
        )
    header = pack_header(network_key, seq, CMD_SET_COLOR_PATTERN)
    scene = struct.pack(
        "<HBBBBB", 13 + len(frame_bytes), scene_idx, len(frames), repeatable, scene_idx, start_now
    )
    message = header + scene + bytes(frame_bytes)
    packets = []
    for number, offset in enumerate(range(0, len(message), 10), start=1):
        chunk = message[offset : offset + 10].ljust(10, b"\0")
        packets.append(
            pack_header(network_key, seq + 2 * number, CMD_DATA_CHUNK)
            + struct.pack("<HH10s", len(message), offset, chunk)
        )
    return packets


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
