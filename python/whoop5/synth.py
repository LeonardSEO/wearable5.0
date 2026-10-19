"""Constructed (synthetic) frames for tests and golden vectors. No captured user data."""
from __future__ import annotations

import struct

from .framing import FORMAT1, SOF, crc16_modbus, crc32


def wrap(body: bytes, destination: int = 0x01, source: int = 0x00) -> bytes:
    """Wrap an inner body (starting with packet type) in a format-1 envelope, padding to 4 bytes."""
    body = bytearray(body)
    while len(body) % 4:
        body.append(0)
    header = bytearray([SOF, FORMAT1]) + struct.pack("<H", len(body) + 4) + bytes([destination, source])
    header += struct.pack("<H", crc16_modbus(bytes(header)))
    return bytes(header + body + struct.pack("<I", crc32(bytes(body))))


def record(layout: int, total_length: int, fill: dict[int, bytes], index: int = 7, unix: int = 1_790_000_000,
           packet_type: int = 47, marker: int = 0x80) -> bytes:
    """A data record of exactly `total_length` bytes with bytes placed at absolute frame offsets."""
    body = bytearray(total_length - 12)
    body[0], body[1], body[2] = packet_type, layout, marker
    struct.pack_into("<II", body, 3, index, unix)
    for off, data in fill.items():
        body[off - 8: off - 8 + len(data)] = data
    return wrap(bytes(body))


def r18(hr: int = 58, rr_ticks: tuple[int, ...] = (1024, 980), skin_raw: int = 3412, steps: int = 1234,
        state_bits: int = 0x20) -> bytes:
    fill = {22: bytes([hr, len(rr_ticks)]), 57: struct.pack("<H", steps), 73: struct.pack("<H", skin_raw),
            81: bytes([state_bits]), 41: struct.pack("<ffff", 0.02, 0.0, 0.0, 1.0),
            69: struct.pack("<hh", 331, 329)}
    for i, t in enumerate(rr_ticks):
        fill[24 + 2 * i] = struct.pack("<H", t)
    return record(18, 124, fill)


def r21(n: int = 3) -> bytes:
    fill = {24: struct.pack("<H", n), 630: struct.pack("<H", n)}
    for k, off in enumerate((28, 228, 428, 640, 840, 1040)):
        fill[off] = struct.pack(f"<{n}h", *[(k + 1) * 100 + i for i in range(n)])
    return record(21, 1244, fill)


def r26(base: int = 100_000, deltas: tuple[int, ...] = (5, -3, 32767, -32768)) -> bytes:
    d = list(deltas) + [0] * (24 - len(deltas))
    return record(26, 88, {21: struct.pack("<H", 9), 23: struct.pack("<I", base), 27: struct.pack("<24h", *d)})


def realtime_hr(hr: int = 61, rr_ticks: tuple[int, ...] = (1000,), unix: int = 1_790_000_000) -> bytes:
    body = bytes([40, 0]) + struct.pack("<IH", unix, 0) + bytes([hr, len(rr_ticks)])
    return wrap(body + b"".join(struct.pack("<H", t) for t in rr_ticks))


def data_range(write: int, trim: int, total: int = 131072, newest: int = 1_790_000_123) -> bytes:
    body = bytearray(65)
    body[0] = 1
    struct.pack_into("<I", body, 9, write)
    struct.pack_into("<I", body, 13, trim)
    struct.pack_into("<I", body, 21, total)
    struct.pack_into("<I", body, 57, newest)
    return wrap(bytes([36, 5, 34, 4, 1]) + bytes(body))


def event(number: int, unix: int = 1_790_000_000) -> bytes:
    return wrap(bytes([48, 3, number, 1]) + struct.pack("<I", unix) + b"\x00" * 4)
