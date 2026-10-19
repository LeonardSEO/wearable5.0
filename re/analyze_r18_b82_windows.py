"""R18 byte 82 (SpO2, experimental) and the scheduled measurement windows it appears in.

Finds runs of R18 records in which byte 82 is non-zero or the status word at 77 leaves its resting
value, reports their schedule (start, length, interval), the byte-82 value classes inside them, and the
per-window median of values in 70..100. No public 5/MG capture yet includes the WHOOP app's SpO2 for
the same night, so the values are experimental.

Usage: python re/analyze_r18_b82_windows.py <frames.jsonl> [...]
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402


def windows(path):
    r18 = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("layout") == 18:
            raw = bytes.fromhex(r["hex"])
            d = decode_frame(raw)
            if d.get("record") == "biometric_summary":
                r18[d["unix_s"]] = raw
    resting = collections.Counter(int.from_bytes(raw[77:79], "little") for raw in r18.values()).most_common(1)
    rest77 = resting[0][0] if resting else None
    marked = sorted(t for t, raw in r18.items() if raw[82] != 0 or int.from_bytes(raw[77:79], "little") != rest77)
    runs, cur = [], []
    for t in marked:
        if cur and t - cur[-1] > 2:
            runs.append(cur)
            cur = []
        cur.append(t)
    if cur:
        runs.append(cur)
    return r18, runs


def main(paths):
    f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for p in paths:
        r18, runs = windows(p)
        print(f"== {os.path.basename(p)}: {len(r18)} R18 records, {len(runs)} marked windows")
        if not runs:
            continue
        starts = [r[0] for r in runs]
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        print(f"   window length s: {collections.Counter(r[-1] - r[0] + 1 for r in runs).most_common(3)}; "
              f"interval s: {collections.Counter(gaps).most_common(3)}")
        classes = collections.Counter()
        for run in runs:
            vals = [r18[t][82] for t in run if t in r18]
            plaus = [v for v in vals if 70 <= v <= 100]
            classes.update("70-100" if 70 <= v <= 100 else ("0" if v == 0 else f"code {v}") for v in vals)
            bands = collections.Counter(("WAKE", "STILL", "SLEEP", "UP")[(r18[t][81] >> 4) & 3] for t in run)
            med = f"{statistics.median(plaus):5.1f} (n={len(plaus):2d}, range {min(plaus)}-{max(plaus)})" if plaus else "    -"
            print(f"   {f(run[0])}  len {run[-1] - run[0] + 1:3d} s  median 70-100: {med}  band {dict(bands)}")
        print("   byte-82 value classes in windows:", dict(classes.most_common(10)))
        outside = collections.Counter(r18[t][82] for t in r18 if not any(r[0] <= t <= r[-1] for r in runs))
        print("   byte 82 outside windows:", dict(outside.most_common(3)))


if __name__ == "__main__":
    main(sys.argv[1:])
