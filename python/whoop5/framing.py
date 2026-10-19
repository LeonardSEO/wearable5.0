"""Format-1 envelope: CRCs, validation, request building and BLE reassembly."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

SOF = 0xAA
FORMAT1 = 0x01
BODY_OFFSET = 8
MIN_FRAME = 16


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    raw: bytes

    @property
    def declared_length(self) -> int:
        return struct.unpack_from("<H", self.raw, 2)[0]

    @property
    def packet_type(self) -> int:
        return self.raw[8]

    @property
    def body(self) -> bytes:
        """Bytes [8, end-4): everything the CRC32 covers."""
        return self.raw[BODY_OFFSET:-4]


def validate(raw: bytes) -> Frame:
    """Return a Frame if `raw` is one complete, CRC-valid format-1 frame; raise FrameError otherwise."""
    if len(raw) < MIN_FRAME:
        raise FrameError("too short")
    if raw[0] != SOF or raw[1] != FORMAT1:
        raise FrameError("not a format-1 frame")
    declared = struct.unpack_from("<H", raw, 2)[0]
    if declared + 8 != len(raw):
        raise FrameError(f"length mismatch: declared {declared}, got {len(raw) - 8}")
    if (declared - 4) % 4:
        raise FrameError("body not 4-aligned")
    if crc16_modbus(raw[:6]) != struct.unpack_from("<H", raw, 6)[0]:
        raise FrameError("header CRC16 mismatch")
    if crc32(raw[BODY_OFFSET:-4]) != struct.unpack_from("<I", raw, len(raw) - 4)[0]:
        raise FrameError("body CRC32 mismatch")
    return Frame(bytes(raw))


def build_command(command: int, args: bytes = b"", sequence: int = 0,
                  destination: int = 0x00, source: int = 0x01) -> bytes:
    """Build a format-1 COMMAND (type 35) frame. Pure; sends nothing."""
    body = bytearray([35, sequence & 0xFF, command & 0xFF]) + bytes(args)
    while len(body) % 4:
        body.append(0)
    declared = len(body) + 4
    header = bytearray([SOF, FORMAT1]) + struct.pack("<H", declared) + bytes([destination, source])
    header += struct.pack("<H", crc16_modbus(bytes(header)))
    return bytes(header + body + struct.pack("<I", crc32(bytes(body))))


class Reassembler:
    """Joins BLE notification fragments into complete frames.

    Large records (up to 2,140 bytes) span many notifications; only the first fragment starts
    with SOF. Bytes that cannot start a frame are skipped one at a time, so a corrupt fragment
    costs at most one frame.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        out: list[bytes] = []
        while True:
            start = self._buf.find(bytes([SOF, FORMAT1]))
            if start < 0:
                # keep a trailing SOF that may pair with the next chunk's first byte
                self._buf = self._buf[-1:] if self._buf[-1:] == bytes([SOF]) else bytearray()
                return out
            del self._buf[:start]
            if len(self._buf) < 4:
                return out
            total = struct.unpack_from("<H", self._buf, 2)[0] + 8
            if total < MIN_FRAME or total > 4096:
                del self._buf[:1]
                continue
            if len(self._buf) < total:
                return out
            candidate = bytes(self._buf[:total])
            try:
                validate(candidate)
            except FrameError:
                del self._buf[:1]
                continue
            out.append(candidate)
            del self._buf[:total]
