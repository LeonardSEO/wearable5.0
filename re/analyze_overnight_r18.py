"""Describe one continuous overnight run of R18 biometric records (no sleep staging, no SpO2).

Reports per 5-minute bin: heart rate, RMSSD from R18 R-R (ms), band-state mix, dynamic acceleration,
skin and auxiliary temperatures; how heart rate and motion differ by band state; and how the
provisional R18 bytes (75-82, 106-113) behave across the night (distinct values, relation to band
state and to heart rate / temperature). Descriptive only: there is no sleep or SpO2 reference.

Usage: python re/analyze_overnight_r18.py <frames.jsonl>
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402

PROVISIONAL = {"b75_u16": (75, "<H"), "b77_u16": (77, "<H"), "b79_u16": (79, "<H"), "b81_state_bits": (81, "<B"),
               "b82_u8": (82, "<B"), "b106": (106, "<B"), "b107": (107, "<B"), "b108": (108, "<B"),
               "b109": (109, "<B"), "b113_f32": (113, "<f")}


def rmssd(rr):
    rr = np.asarray([x for x in rr if 300 <= x <= 2000], float)
    if len(rr) < 20:
        return None
    d = np.diff(rr)
    d = d[np.abs(d) < 200]  # drop gross artefacts / missed beats
    return float(np.sqrt(np.mean(d ** 2))) if len(d) >= 10 else None


def main(path):
    recs = {}
    for line in open(path):
        r = json.loads(line)
        if r.get("layout") != 18:
            continue
        raw = bytes.fromhex(r["hex"])
        d = decode_frame(raw)
        d["_raw"] = raw
        recs[d["unix_s"]] = d
    ts = sorted(recs)
    f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M")
    print(f"{len(ts)} R18 records, {f(ts[0])}-{f(ts[-1])} UTC, gaps > 60 s: "
          f"{sum(1 for a, b in zip(ts, ts[1:]) if b - a > 60)}")

    print("\n5-min bins: time  HR  RMSSD(ms)  SLEEP%  dyn_accel(g)  skin(C)  aux1/aux2(C)")
    for start in range(ts[0], ts[-1], 300):
        w = [recs[t] for t in ts if start <= t < start + 300]
        if len(w) < 200:
            continue
        hr = np.mean([d["heart_rate"] for d in w if d["heart_rate"]])
        rv = rmssd([x for d in w for x in d["rr_ms"]])
        sl = 100 * np.mean([d["band_state"] == "SLEEP" for d in w])
        acc = np.mean([d["dynamic_accel_g"] for d in w if d["dynamic_accel_g"] is not None])
        sk = np.mean([d["skin_temp_c"] for d in w if d["skin_temp_c"]])
        a1 = np.mean([d["temp_aux1_c"] for d in w if d["temp_aux1_c"]])
        a2 = np.mean([d["temp_aux2_c"] for d in w if d["temp_aux2_c"]])
        rv_s = f"{rv:6.1f}" if rv else "    - "
        print(f"  {f(start)}  {hr:5.1f}  {rv_s}  {sl:5.0f}  {acc:.4f}  {sk:6.2f}  {a1:5.1f}/{a2:5.1f}")

    print("\nBy band state: n, HR mean, dynamic accel mean")
    groups = collections.defaultdict(list)
    for d in recs.values():
        groups[d["band_state"]].append(d)
    for k, v in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"  {k:6s} n={len(v):6d}  HR={np.mean([d['heart_rate'] for d in v]):5.1f}  "
              f"accel={np.mean([d['dynamic_accel_g'] for d in v]):.4f}")

    rv_night = rmssd([x for t in ts for x in recs[t]["rr_ms"]])
    print(f"\nwhole-night RMSSD (ms, artefact-filtered): {rv_night:.1f}")

    print("\nProvisional bytes: distinct values, top values, Spearman-like rank r vs HR and vs skin temp")
    hr = np.array([recs[t]["heart_rate"] for t in ts], float)
    sk = np.array([recs[t]["skin_temp_c"] or np.nan for t in ts], float)

    def rank_r(x, y):
        m = ~(np.isnan(x) | np.isnan(y))
        if m.sum() < 50 or np.std(x[m]) == 0:
            return float("nan")
        return float(np.corrcoef(np.argsort(np.argsort(x[m])), np.argsort(np.argsort(y[m])))[0, 1])
    for name, (off, fmt) in PROVISIONAL.items():
        vals = np.array([struct.unpack_from(fmt, recs[t]["_raw"], off)[0] for t in ts], float)
        c = collections.Counter(vals.tolist())
        top = ", ".join(f"{v:g}x{n}" for v, n in c.most_common(4))
        print(f"  {name:15s} distinct={len(c):5d}  top: {top:48s}  r(HR)={rank_r(vals, hr):+.2f}  r(skin)={rank_r(vals, sk):+.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
