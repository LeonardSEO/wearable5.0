"""Is the WHOOP 5/MG R-R interval in 1/1024 s ticks (BLE spec) or in milliseconds?

Three tests on HCI captures in which the phone also received the strap's standard Heart Rate
Measurement (0x2A37, ATT handle 0x0022 in these captures):
  1. 0x2A37 R-R summed over windows where every beat was reported, against the phone's own capture
     clock (independent of the strap). The right unit makes the sum equal the elapsed time.
  2. Beat-for-beat comparison of raw 0x2A37 R-R values with raw R18 R-R values.
  3. R18 alone: summed R-R against elapsed record seconds in full-coverage minutes.

Usage: python re/analyze_rr_unit.py <capture.pklg|btsnoop> <frames.jsonl from pklg_extract.py> [...pairs]
"""
from __future__ import annotations

import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from pklg_extract import btsnoop_records, records  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402

HR_HANDLE = 0x0022


def hr_notifications(path):
    blob = open(path, "rb").read()
    src = btsnoop_records(blob) if blob[:8] == b"btsnoop\0" else records(blob)
    out = []
    for ts, ptype, data in src:
        if ptype != 3 or len(data) < 9 or (struct.unpack_from("<H", data, 0)[0] >> 12) & 3 not in (0, 2):
            continue
        att = data[8:]
        if struct.unpack_from("<H", data, 6)[0] != 4 or att[:1] != b"\x1b":
            continue
        if struct.unpack_from("<H", att, 1)[0] != HR_HANDLE:
            continue
        v = att[3:]
        flags, o = v[0], (3 if v[0] & 1 else 2) + (2 if v[0] & 8 else 0)
        rr = [struct.unpack_from("<H", v, k)[0] for k in range(o, len(v) - 1, 2)] if flags & 0x10 else []
        out.append((ts, v[1], rr))
    return out


def r18_raw(frames_path):
    out = []
    for line in open(frames_path):
        r = json.loads(line)
        if r["layout"] != 18:
            continue
        raw = bytes.fromhex(r["hex"])
        d = decode_frame(raw)
        ticks = [struct.unpack_from("<H", raw, 24 + 2 * i)[0] for i in range(min(raw[23], 4))]
        out.append((d["unix_s"], d["heart_rate"], [t for t in ticks if t]))
    return sorted(out)


def clock_test(notes):
    res, i = [], 0
    while i < len(notes):
        j = i
        while j + 1 < len(notes) and notes[j + 1][0] - notes[j][0] < 2.0 and notes[j + 1][0] - notes[i][0] <= 120:
            j += 1
        span = notes[j][0] - notes[i][0]
        if span >= 100:
            raw = sum(sum(r) for _, _, r in notes[i + 1:j + 1])
            beats = sum(len(r) for _, _, r in notes[i + 1:j + 1])
            hr = np.mean([h for _, h, _ in notes[i:j + 1]])
            if abs(beats - hr * span / 60) / (hr * span / 60) < 0.03:
                res.append(raw / 1000 / span)
        i = j + 1
    return np.array(res)


def beat_match(a, b, length=25):
    best = (float("inf"), None)
    for i in range(0, min(len(a) - length, 400)):
        seg = a[i:i + length]
        for j in range(0, len(b) - length):
            e = float(np.mean(np.abs(seg - b[j:j + length])))
            if e < best[0]:
                best = (e, (i, j))
    return best


def r18_sum_test(rows):
    ts = [t for t, _, _ in rows]
    out = []
    for m in range(0, len(rows) - 60, 60):
        if ts[m + 59] - ts[m] != 59:
            continue
        w = rows[m:m + 60]
        n, e = sum(len(r) for _, _, r in w), sum(h / 60 for _, h, _ in w if h)
        if e and abs(n - e) / e < 0.03:
            out.append(sum(x for _, _, r in w for x in r) / 60000)
    return np.array(out)


def main(args):
    for cap, frames in zip(args[0::2], args[1::2]):
        notes, rows = hr_notifications(cap), r18_raw(frames)
        print(f"== {os.path.basename(cap)}: {len(notes)} 0x2A37 notifications, {len(rows)} R18 records")
        c = clock_test(notes)
        if len(c):
            print(f"  1. 0x2A37 sum(R-R)/phone-clock elapsed, {len(c)} full-coverage windows: "
                  f"as ms {np.median(c):.4f} | as 1/1024 s {np.median(c) * 1000 / 1024:.4f}")
        else:
            print("  1. no full-coverage 0x2A37 windows")
        a = np.array([x for _, _, r in notes for x in r], float)
        b = np.array([x for _, _, r in rows for x in r], float)
        if len(a) > 30 and len(b) > 30:
            e, at = beat_match(a, b)
            print(f"  2. best mean |raw 0x2A37 - raw R18| over 25 consecutive beats: {e:.2f} units at {at}")
        s = r18_sum_test(rows)
        if len(s):
            print(f"  3. R18 sum(R-R)/elapsed, {len(s)} full-coverage minutes: as ms {np.median(s):.4f} | "
                  f"as 1/1024 s {np.median(s) * 1000 / 1024:.4f}")
        else:
            print("  3. no full-coverage R18 minutes")


if __name__ == "__main__":
    main(sys.argv[1:])
