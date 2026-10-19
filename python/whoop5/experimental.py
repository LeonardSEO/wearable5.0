"""Experimental metrics derived from decoded WHOOP 5/MG records.

Backed by real captures (see FINDINGS) but not yet checked against a clinical or WHOOP-app reference
on more than one wearer. Twin: `Whoop5Experimental` in the Swift package.
"""
from __future__ import annotations

import math
from statistics import median


def spo2_windows(records: list[dict], max_gap: int = 2, min_valid_seconds: int = 5) -> list[dict]:
    """One SpO2 value per strap measurement window.

    `records` are decoded R18 dicts (decode_frame output). A window is a run of records whose SpO2 byte
    is non-zero, allowing gaps of at most `max_gap` seconds. Each window reports the median of its valid
    seconds (70-100 %), or None when fewer than `min_valid_seconds` seconds were valid (a lone value in a
    window of status codes is noise).
    """
    rows = sorted((r["unix_s"], r["spo2_byte_82"], r.get("spo2_percent")) for r in records
                  if r.get("layout") == 18 and r.get("spo2_byte_82") is not None)
    windows, cur = [], []
    for t, raw, pct in rows:
        if raw == 0:
            continue
        if cur and t - cur[-1][0] > max_gap:
            windows.append(cur)
            cur = []
        cur.append((t, pct))
    if cur:
        windows.append(cur)
    out = []
    for w in windows:
        valid = [p for _, p in w if p is not None]
        out.append({"start_unix": w[0][0], "end_unix": w[-1][0], "seconds": len(w), "valid_seconds": len(valid),
                    "spo2_percent": float(median(valid)) if len(valid) >= max(1, min_valid_seconds) else None})
    return out


def rmssd_ms(rr_ms: list[int], max_step_ms: int = 200) -> float | None:
    """RMSSD over consecutive R-R intervals in ms; steps above `max_step_ms` (missed beats, artefacts)
    and intervals outside 300-2000 ms are dropped. None with fewer than 10 usable differences."""
    rr = [x for x in rr_ms if 300 <= x <= 2000]
    diffs = [b - a for a, b in zip(rr, rr[1:]) if abs(b - a) < max_step_ms]
    if len(diffs) < 10:
        return None
    return math.sqrt(sum(d * d for d in diffs) / len(diffs))
