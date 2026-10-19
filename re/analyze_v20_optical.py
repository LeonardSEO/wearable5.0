"""Which R20 optical channels carry the cardiac pulse, and does a pulse-derived HR track a VARYING reference?

Input: a NOOP RawHistoryArchive JSONL of v20 frames and the paired ground-truth CSV donated in
ryanbr/noop#1992 (see re/README.md for the download step). Ground truth is the strap's own banked
1 Hz HR, independent of this decode.

Guard against the known artifact (ryanbr/noop AGENTS.md, #194): records are one second long, so a
spectral peak at 1 Hz (60 bpm) can appear from the record boundary alone and coincidentally match a
resting HR. This script therefore (a) uses time-domain beat detection, not a spectral peak, (b) scores
by correlation across a reference that moves (51-86 bpm here), not by mean error alone, and
(c) reports a shuffled-record control that keeps every record's content but destroys continuity.

Usage: python re/analyze_v20_optical.py <rejected_history.jsonl> <ground_truth_window.csv>
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402

FS = 25.0


def load_records(path):
    by_index = {}
    for line in open(path):
        d = decode_frame(bytes.fromhex(json.loads(line)["frameHex"]))
        if d.get("layout") == 20:
            by_index.setdefault(d["record_index"], d)  # replays repeat an index; keep the first copy
    return [by_index[k] for k in sorted(by_index)]


def load_reference(path):
    hr = {}
    for row in csv.DictReader(open(path)):
        if row["stream"] == "hr_bpm":
            hr[int(row["ts_unix"])] = int(row["value"])
    return hr


def segments(records):
    """Split into runs of consecutive seconds with full 25-sample blocks."""
    seg, out = [], []
    for r in records:
        if seg and r["unix_s"] != seg[-1]["unix_s"] + 1:
            out.append(seg)
            seg = []
        seg.append(r)
    if seg:
        out.append(seg)
    return out


def channel_series(seg, block, slot):
    xs, ts = [], []
    for r in seg:
        b = r["blocks"][block]
        vals = b["slot_a" if slot == "A" else "slot_b"]
        n = len(vals)
        xs.extend(vals)
        ts.extend(r["unix_s"] + np.arange(n) / max(n, 1))
    return np.asarray(xs, float), np.asarray(ts, float)


def bandpass(x, lo=0.6, hi=3.3):
    b, a = butter(3, [lo / (FS / 2), hi / (FS / 2)], btype="band")
    return filtfilt(b, a, x - np.median(x))


def beats(x):
    y = -bandpass(x)  # PPG pulses are absorption dips; invert so a beat is a peak
    prom = 0.3 * np.std(y)
    peaks, _ = find_peaks(y, distance=int(FS * 0.33), prominence=prom)
    return peaks


def windowed_hr(ts, peaks, t0, t1, win=10.0, step=2.0):
    pt = ts[peaks]
    out = []
    t = t0 + win
    while t <= t1:
        sel = pt[(pt > t - win) & (pt <= t)]
        if len(sel) >= 4:
            ibi = np.diff(sel)
            ibi = ibi[(ibi > 0.3) & (ibi < 2.0)]
            if len(ibi) >= 3:
                out.append((int(t), 60.0 / np.median(ibi)))
        t += step
    return out


def score(est, ref):
    pairs = [(h, ref[t]) for t, h in est if t in ref]
    if len(pairs) < 20:
        return None
    a, b = np.array(pairs).T
    return {"n": len(pairs), "pearson_r": float(np.corrcoef(a, b)[0, 1]), "mae_bpm": float(np.mean(np.abs(a - b))),
            "ref_range": [int(b.min()), int(b.max())]}


def main(jsonl, ref_csv):
    records = load_records(jsonl)
    ref = load_reference(ref_csv)
    segs = segments(records)
    print(f"{len(records)} unique v20 records, {len(segs)} contiguous segments, "
          f"longest {max(len(s) for s in segs)} s")

    # 1. block configuration across the corpus
    print("\nBlock configuration (source, drive, detector, range, offset) for slots A | B, frequency across records:")
    for bi in range(5):
        cfg = Counter((b["source_a"], b["drive_a"], b["detector_a"], b["range_a"], b["offset_a"],
                       b["source_b"], b["drive_b"], b["detector_b"], b["range_b"], b["offset_b"], b["count"])
                      for b in (r["blocks"][bi] for r in records))
        for c, n in cfg.most_common(3):
            print(f"  block {bi}: A(src={c[0]} drv={c[1]} det={c[2]} rng={c[3]} off={c[4]}) "
                  f"B(src={c[5]} drv={c[6]} det={c[7]} rng={c[8]} off={c[9]}) count={c[10]}  x{n}")

    # 2. per-channel pulsatility and HR tracking on the longest segments
    results = defaultdict(list)
    rng = np.random.default_rng(0)
    for seg in sorted(segs, key=len, reverse=True):
        if len(seg) < 60:
            continue
        for bi in range(5):
            for slot in "AB":
                x, ts = channel_series(seg, bi, slot)
                if len(x) < FS * 60 or np.ptp(x) == 0:
                    continue
                dc = float(np.median(x))
                ac = float(np.std(bandpass(x)))
                est = windowed_hr(ts, beats(x), ts[0], ts[-1])
                s = score(est, ref)
                # control: shuffle whole records, keeping each record's samples intact
                order = rng.permutation(len(seg))
                xc, _ = channel_series([seg[i] for i in order], bi, slot)
                sc = score(windowed_hr(ts, beats(xc), ts[0], ts[-1]), ref)
                results[(bi, slot)].append((len(seg), dc, ac, s, sc))

    print("\nChannel pulsatility and HR tracking vs reference (windowed 10 s, median inter-beat interval):")
    print("  chan   seconds   DC          AC/DC      r(HR)   MAE    | shuffled-control r  MAE")
    for (bi, slot), rows in sorted(results.items()):
        secs = sum(r[0] for r in rows)
        dc = np.average([r[1] for r in rows], weights=[r[0] for r in rows])
        pi = np.average([r[2] / abs(r[1]) if r[1] else 0 for r in rows], weights=[r[0] for r in rows])
        good = [r[3] for r in rows if r[3]]
        ctrl = [r[4] for r in rows if r[4]]
        if good:
            rr = np.average([g["pearson_r"] for g in good], weights=[g["n"] for g in good])
            mae = np.average([g["mae_bpm"] for g in good], weights=[g["n"] for g in good])
        else:
            rr = mae = float("nan")
        if ctrl:
            cr = np.average([g["pearson_r"] for g in ctrl], weights=[g["n"] for g in ctrl])
            cm = np.average([g["mae_bpm"] for g in ctrl], weights=[g["n"] for g in ctrl])
        else:
            cr = cm = float("nan")
        print(f"  {bi}{slot}    {secs:6d}   {dc:10.0f}  {pi:9.5f}   {rr:6.2f}  {mae:5.1f}  | {cr:6.2f}         {cm:5.1f}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
