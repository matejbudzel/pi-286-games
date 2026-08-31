"""Minimal RFC 6455 wire helpers for the trusted single-client stream path."""
from __future__ import annotations

import base64
import hashlib
import os
import struct

MAX_FRAME = 2 * 1024 * 1024


def accept_key(key: str) -> str:
    value = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
    return base64.b64encode(hashlib.sha1(value).digest()).decode("ascii")


def pack_frame(payload: bytes, opcode: int = 2, masked: bool = False) -> bytes:
    if len(payload) > MAX_FRAME:
        raise ValueError("websocket frame too large")
    first = 0x80 | opcode
    mask_bit = 0x80 if masked else 0
    if len(payload) < 126:
        header = bytes((first, mask_bit | len(payload)))
    elif len(payload) <= 0xffff:
        header = bytes((first, mask_bit | 126)) + struct.pack(">H", len(payload))
    else:
        header = bytes((first, mask_bit | 127)) + struct.pack(">Q", len(payload))
    if not masked:
        return header + payload
    mask = os.urandom(4)
    return header + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))


def read_exact(reader, length: int) -> bytes:
    data = reader.read(length)
    if data is None or len(data) != length:
        raise EOFError("websocket peer closed")
    return data


def read_frame(reader, require_mask: bool) -> tuple[int, bytes]:
    first, second = read_exact(reader, 2)
    if first & 0x70 or not first & 0x80:
        raise ValueError("fragmented websocket frames are unsupported")
    opcode, masked, length = first & 0x0f, bool(second & 0x80), second & 0x7f
    if masked != require_mask:
        raise ValueError("unexpected websocket masking")
    if length == 126:
        length = struct.unpack(">H", read_exact(reader, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read_exact(reader, 8))[0]
    if length > MAX_FRAME:
        raise ValueError("websocket frame too large")
    mask = read_exact(reader, 4) if masked else b""
    payload = read_exact(reader, length)
    if masked:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return opcode, payload
