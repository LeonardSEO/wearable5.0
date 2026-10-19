"""Schema-driven decoder for WHOOP 5/MG format-1 frames.

Every fixed-offset field comes from `whoop5_protocol.json`; only array-shaped records (R20 optical
blocks, R21 IMU columns, R22/R26 delta streams, R-R lists) have code here. Unknown layouts are
returned with their header and raw bytes, never dropped and never zero-filled.
"""
from __future__ import annotations

import json
import struct
from functools import lru_cache
from importlib import resources
from typing import Any

from .framing import Frame, validate

_FMT = {"u8": "<B", "i8": "<b", "u16": "<H", "i16": "<h", "u32": "<I", "i32": "<i", "f32": "<f"}


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(resources.files(__package__).joinpath("whoop5_protocol.json").read_text())


def _read(buf: bytes, offset: int, typ: str) -> Any:
    fmt = _FMT[typ]
    if offset + struct.calcsize(fmt) > len(buf):
        return None
    return struct.unpack_from(fmt, buf, offset)[0]


def _fields(buf: bytes, specs: list[dict], base: int = 0) -> dict:
    out: dict[str, Any] = {}
    for f in specs:
        v = _read(buf, base + f.get("offset", f.get("rel", 0)), f["type"])
        if v is not None and "scale" in f:
            scaled = round(v * f["scale"], 4)
            lo, hi = f.get("valid", (None, None))
            out[f["name"] + "_raw"] = v
            v = scaled if (lo is None or lo <= scaled <= hi) else None
        out[f["name"]] = v
    return out


def rr_ticks_to_ms(ticks: int) -> int:
    """Convert BLE-spec 1/1024 s R-R ticks to ms. WHOOP 5/MG does NOT use this unit (see rr_list)."""
    return (ticks * 1000 + 512) // 1024


def _rr_list(raw: bytes, offset: int, count: int, limit: int) -> list[int]:
    out = []
    for i in range(min(count, limit)):
        o = offset + 2 * i
        if o + 2 > len(raw) - 4:
            break
        t = struct.unpack_from("<H", raw, o)[0]
        if t:
            out.append(t)  # WHOOP 5/MG sends R-R in milliseconds (FINDINGS: R-R unit)
    return out


def _enum(table: dict, key: int) -> str:
    return table.get(str(key), f"UNKNOWN_{key}")


def decode_frame(raw: bytes) -> dict:
    """Validate and decode one complete frame. Raises FrameError on an invalid frame."""
    frame = validate(raw)
    s = schema()
    t = frame.packet_type
    out: dict[str, Any] = {"packet_type": t, "packet": _enum(s["packet_types"], t), "length": len(raw)}
    if t == 36:
        out.update(_command_response(raw))
    elif t == 40:
        spec = s["realtime_hr_40"]
        out.update(_fields(raw[:-4], spec["fields"]))
        out["rr_ms"] = _rr_list(raw, spec["rr_offset"], out["rr_count"] or 0, 64)
    elif t == 48:
        out.update(_fields(raw[:-4], s["event_48"]["fields"]))
        out["event_name"] = _enum(s["events"], out["event"])
        out["payload_hex"] = raw[16:-4].hex()
    elif t == 49:
        out.update(_fields(raw[:-4], s["metadata_49"]["fields"]))
        out["meta_name"] = _enum(s["metadata_types"], out["meta_type"])
        if out["meta_type"] == 2 and len(raw) - 4 >= 29:
            out["end_token_hex"] = _end_token(raw).hex()
        else:
            out.pop("trim_cursor", None)  # the cursor exists only in a HISTORY_END token
    elif t in (43, 47):
        out.update(_data_record(frame))
    elif t in (51, 52):
        out.update(_imu_stream(raw))
    else:
        out["body_hex"] = frame.body.hex()
    return out


def _end_token(raw: bytes) -> bytes:
    """The 8-byte HISTORY_END token (trim u32 + write-wrap u32) at frame [21, 29). Echo it verbatim."""
    return raw[21:29]


def history_ack(end_token: bytes, sequence: int = 0) -> bytes:
    """HISTORICAL_DATA_RESULT (23) acknowledging one committed chunk: body 01 + the verbatim token."""
    from .framing import build_command
    if len(end_token) != 8:
        raise ValueError("end token must be 8 bytes")
    return build_command(23, b"\x01" + bytes(end_token), sequence)


def _command_response(raw: bytes) -> dict:
    s = schema()
    spec = s["command_response"]
    out = _fields(raw[:-4], spec["fields"])
    out["command_name"] = _enum(s["commands"], out["command"])
    out["result_name"] = _enum(s["result_codes"], out["result"])
    body = raw[spec["body_offset"]:-4]
    resp = s["responses"].get(out["command_name"])
    if resp and out["result"] == 1:
        need = resp.get("body_length")
        if need is None or len(body) >= need:
            out["fields"] = _fields(body, resp["fields"])
            if out["command_name"] == "GET_DATA_RANGE":
                out["fields"]["pages_behind"] = pages_behind(out["fields"])
                out["fields"]["newest_unix"] = data_range_newest(out["fields"])
    out["body_hex"] = body.hex()
    return out


def pages_behind(f: dict) -> int | None:
    w, u, t = f.get("write_page"), f.get("trim_page"), f.get("total_pages")
    if None in (w, u, t) or t == 0 or w >= t or u >= t:
        return None
    return w - u if w >= u else (t - u) + w


def data_range_newest(f: dict) -> int | None:
    """Last-written page clock, or None for a sentinel/zero clock. Field-exact; no byte scanning."""
    v = f.get("newest_clock_s")
    return None if v in (None, 0, 0xFFFFFFFF) else v


def _data_record(frame: Frame) -> dict:
    s = schema()
    raw = frame.raw
    out = _fields(raw[:-4], s["data_record_header"]["fields"])
    layout = out["layout"]
    rec = s["records"].get(str(layout))
    if rec is None:
        out["record"] = f"UNKNOWN_LAYOUT_{layout}"
        out["body_hex"] = frame.body.hex()
        return out
    out["record"] = rec["name"]
    if rec.get("length") and len(raw) != rec["length"]:
        out["record"] += "_unexpected_length"
        out["body_hex"] = frame.body.hex()
        return out
    if layout == 18:
        out.update(_fields(raw[:-4], rec["fields"]))
        out["rr_ms"] = _rr_list(raw, rec["rr_offset"], out["rr_count"] or 0, rec["rr_max"])
        bs = rec["band_state_from_state_bits"]
        out["band_state"] = bs["labels"][str((out["state_bits"] >> bs["shift"]) & bs["mask"])]
        out["activity_class"] = rec["fields"][[f["name"] for f in rec["fields"]].index("activity_class")]["enum"].get(
            str(out["activity_class"]), f"raw_{out['activity_class']}")
    elif layout == 20:
        out["blocks"] = [_r20_block(raw, b, rec) for b in rec["block_bases"]]
    elif layout == 21:
        out.update(_r21(raw, rec))
    elif layout == 26:
        out.update(_fields(raw[:-4], rec["fields"]))
        out["samples"] = _cumulative(out["base"], [
            struct.unpack_from("<h", raw, rec["delta_offset"] + 2 * i)[0] for i in range(rec["delta_count"])])
    elif layout == 22:
        out.update(_r22(raw, rec))
    elif layout in (16, 17):
        out.update(_ecg(raw, layout, schema()["records"]["16"]["status_fields"], rec))
    return out


def _ecg(raw: bytes, layout: int, status: list[dict], rec: dict) -> dict:
    """R16 raw (18-bit, 500 slots + lead I/Q) and R17 filtered (i16, 100 slots) MG ECG."""
    out = _fields(raw[:-4], status)
    n, cap = out["sample_count"], rec["sample_capacity"]
    if n > cap:
        out["error"] = "count above capacity"
        return out
    off = rec["sample_offset"]
    if layout == 17:
        out["samples"] = list(struct.unpack_from(f"<{n}h", raw, off))
        return out
    samples, flag6, flag7 = [], [], []
    for i in range(n):
        b0, b1, b2 = raw[off + 3 * i: off + 3 * i + 3]
        v = ((b0 & 0x03) << 16) | (b1 << 8) | b2
        samples.append(v - 262144 if v >= 131072 else v)
        flag6.append((b0 >> 6) & 1)
        flag7.append((b0 >> 7) & 1)
    out.update({"samples": samples, "flag6": flag6, "flag7": flag7})
    lc = raw[rec["lead_count_offset"]]
    out["lead_count"] = lc
    k = min(lc, rec["lead_capacity"])
    out["lead_i"] = list(struct.unpack_from(f"<{k}h", raw, rec["lead_i_offset"]))
    out["lead_q"] = list(struct.unpack_from(f"<{k}h", raw, rec["lead_q_offset"]))
    return out


def _r20_block(raw: bytes, base: int, rec: dict) -> dict:
    blk = _fields(raw[:-4], rec["block_fields"], base)
    n = blk["count"]
    if n > 50:
        blk["error"] = "count above capacity"
        n = 0
    blk["slot_a"] = list(struct.unpack_from(f"<{n}i", raw, base + rec["slot_a_rel"]))
    blk["slot_b"] = list(struct.unpack_from(f"<{n}i", raw, base + rec["slot_b_rel"]))
    return blk


def _r21(raw: bytes, rec: dict) -> dict:
    cap = rec["capacity"]
    na = struct.unpack_from("<H", raw, rec["accel_count_offset"])[0]
    ng = struct.unpack_from("<H", raw, rec["gyro_count_offset"])[0]
    out: dict[str, Any] = {"accel_count": na, "gyro_count": ng}
    if na > cap or ng > cap:
        out["error"] = "count above capacity"
        return out
    for axis, off in zip("xyz", rec["accel_xyz_offsets"]):
        out[f"accel_{axis}"] = list(struct.unpack_from(f"<{na}h", raw, off))
    for axis, off in zip("xyz", rec["gyro_xyz_offsets"]):
        out[f"gyro_{axis}"] = list(struct.unpack_from(f"<{ng}h", raw, off))
    return out


def _r22(raw: bytes, rec: dict) -> dict:
    version = raw[rec["inner_version_offset"]]
    out: dict[str, Any] = {"inner_version": version, "inner_subversion": raw[rec["inner_version_offset"] + 1]}
    if version != 9:
        out["body_hex"] = raw[rec["inner_version_offset"]:-4].hex()
        return out
    v = rec["v9"]
    initial = struct.unpack_from("<I", raw, v["initial_offset"])[0]
    deltas = [struct.unpack_from("<h", raw, v["delta_offset"] + 2 * i)[0] for i in range(v["delta_count"])]
    out["channel"] = raw[v["channel_offset"]]
    out["metadata"] = struct.unpack_from("<H", raw, v["metadata_offset"])[0]
    out["flag"] = raw[v["flag_offset"]]
    out["sample_bits"] = [(x & 0xFFFFFFFF) for x in _cumulative(initial, deltas)]
    return out


def _imu_stream(raw: bytes) -> dict:
    """Packets 51/52: count/span layout, bounds-checked against the CRC boundary."""
    end = len(raw) - 4
    if end < 28:
        return {"error": "too short"}
    na, ng = struct.unpack_from("<HH", raw, 24)
    if 28 + 6 * na + 6 * ng > end:
        return {"accel_count": na, "gyro_count": ng, "error": "span exceeds frame"}
    out: dict[str, Any] = {"accel_count": na, "gyro_count": ng}
    o = 28
    for name, n in (("accel_x", na), ("accel_y", na), ("accel_z", na), ("gyro_x", ng), ("gyro_y", ng), ("gyro_z", ng)):
        out[name] = list(struct.unpack_from(f"<{n}h", raw, o))
        o += 2 * n
    return out


def _cumulative(base: int, deltas: list[int]) -> list[int]:
    out = [base]
    for d in deltas:
        out.append(out[-1] + d)
    return out
