"""Reference decoder for the WHOOP 5.0 / MG Bluetooth LE protocol (format-1 envelope)."""
from .decode import decode_frame, history_ack, pages_behind, rr_ticks_to_ms, schema
from .framing import Frame, FrameError, Reassembler, build_command, crc16_modbus, crc32, validate

__version__ = "0.1.0"
__all__ = ["decode_frame", "history_ack", "pages_behind", "rr_ticks_to_ms", "schema", "Frame", "FrameError",
           "Reassembler", "build_command", "crc16_modbus", "crc32", "validate"]
