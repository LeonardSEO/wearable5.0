"""Run the experimental metrics in python/whoop5/experimental.py (stdlib) on real captures and cross-check
them against independent numpy/scipy computations.

Inputs (local, never committed):
  <frames.jsonl>   one continuous overnight capture (R18 + R26), e.g.
                   sources/digitalerdude_hci/bluetoothd-hci-2026-07-10_06-09-15.redacted.frames.jsonl
  [whoop5-data]    the 5.0/MG-only corpus: frames/by_type/HISTORICAL_DATA_L18.jsonl and _L26.jsonl

Checks:
  sleep_periods       - onset/offset vs the raw band-state runs; HR min/mean vs numpy over the same seconds
  respiratory_rate    - per-window rates vs a whole-night Welch spectrum of the same R-R series (scipy), and
                        a synthetic RSA series with a known rate
  skin_temp_baseline  - nightly stats vs numpy over the same seconds
  hr_from_r26         - per burst vs the R18 heart_rate mean over the same seconds, and vs the scipy method of
                        re/analyze_r26.py on the same bursts
No reference exists for sleep staging or breathing on this capture; these are consistency checks.

Usage (workspace root): .venv/bin/python -I wearable5.0/re/analyze_experimental_metrics.py <frames.jsonl> [whoop5-data]
Writes wearable5.0/re/results/experimental_metrics.txt (summary values only, no identifiers, no frames).
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import os
import sys

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks, welch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402
from whoop5.experimental import (hr_from_r26, respiratory_rate, skin_temp_baseline,  # noqa: E402
                                 sleep_periods)


def load(lines):
    r18, r26 = {}, {}
    for line in lines:
        e = json.loads(line)
        if e.get("layout") not in (18, 26):
            continue
        d = decode_frame(bytes.fromhex(e["hex"]))
        if d.get("layout") == 18 and d.get("record") == "biometric_summary":
            r18.setdefault(d["unix_s"], d)
        elif d.get("layout") == 26 and d.get("record") == "compact_optical_window":
            r26.setdefault(d["record_index"], d)
    return [r18[t] for t in sorted(r18)], sorted(r26.values(), key=lambda d: (d["unix_s"], d["record_index"]))


def hm(t, t0):
    return f"+{(t - t0) / 3600:.2f} h"


def scipy_burst_hr(recs):
    x = np.concatenate([np.asarray(r["samples"], float) for r in recs])
    if len(x) < 25 * 12:
        return None
    b, a = butter(3, [0.6 / 12.5, 3.3 / 12.5], btype="band")
    y = -filtfilt(b, a, x - np.median(x))
    pk, _ = find_peaks(y, distance=8, prominence=0.3 * np.std(y))
    ibi = np.diff(pk) / 25.0
    ibi = ibi[(ibi > 0.3) & (ibi < 2.0)]
    return 60.0 / float(np.median(ibi)) if len(ibi) >= 5 else None


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and np.std(a) > 0 and np.std(b) > 0 else float("nan")


def overnight(path, p):
    r18, r26 = load(open(path))
    t0 = r18[0]["unix_s"]
    p(f"Overnight capture: {len(r18)} R18 records over {(r18[-1]['unix_s'] - t0) / 3600:.2f} h, "
      f"{len(r26)} R26 records; times below are relative to the first R18 record")
    states = collections.Counter(r["band_state"] for r in r18)
    p(f"  band_state counts: {dict(sorted(states.items()))}")

    p("\n1. sleep_periods (SLEEP only, 300 s majority smoothing, gaps <= 600 s merged, >= 1200 s)")
    periods = sleep_periods(r18)
    by_t = {r["unix_s"]: r for r in r18}
    for q in periods:
        hrs = np.array([by_t[t]["heart_rate"] for t in range(q["onset_unix"], q["offset_unix"] + 1)
                        if t in by_t and 25 <= by_t[t]["heart_rate"] <= 230], float)
        p(f"  onset {hm(q['onset_unix'], t0)}, offset {hm(q['offset_unix'], t0)}, duration "
          f"{q['duration_s'] / 3600:.2f} h, asleep {q['asleep_s'] / q['duration_s']:.1%} of the period, "
          f"records {q['records']}")
        p(f"  HR min {q['hr_min']} bpm, mean {q['hr_mean']:.1f} bpm (numpy over the same seconds: min "
          f"{hrs.min():.0f}, mean {hrs.mean():.1f})")
    last_sleep = max(r["unix_s"] for r in r18 if r["band_state"] == "SLEEP")
    p(f"  raw: last SLEEP record {hm(last_sleep, t0)}; the capture starts already in SLEEP, so onset is the "
      "capture start, not a detected sleep onset")

    p("\n2. respiratory_rate (60 s windows of R18 R-R)")
    rr = [x for r in r18 for x in r["rr_ms"]]
    rows = respiratory_rate(rr)
    vals = np.array([w["breaths_per_min"] for w in rows if w["breaths_per_min"] is not None])
    pf = np.array([w["peak_fraction"] for w in rows if w["peak_fraction"] is not None])
    p(f"  windows {len(rows)}, with a rate {len(vals)}; breaths/min median {np.median(vals):.1f}, "
      f"IQR {np.percentile(vals, 25):.1f}-{np.percentile(vals, 75):.1f}, p10-p90 "
      f"{np.percentile(vals, 10):.1f}-{np.percentile(vals, 90):.1f}; peak_fraction median {np.median(pf):.3f}")
    clear = vals[np.array([w["peak_fraction"] for w in rows if w["breaths_per_min"] is not None]) >= 0.1]
    if len(clear):
        p(f"  windows with peak_fraction >= 0.10: {len(clear)}, median {np.median(clear):.1f}, IQR "
          f"{np.percentile(clear, 25):.1f}-{np.percentile(clear, 75):.1f}")
    for name, n in (("first half", slice(0, len(rows) // 2)), ("second half", slice(len(rows) // 2, None))):
        v = [w["breaths_per_min"] for w in rows[n] if w["breaths_per_min"] is not None]
        p(f"  {name}: median {np.median(v):.1f} breaths/min over {len(v)} windows")
    # independent cross-check: whole-night Welch on wall-clock-anchored beats (scipy)
    bt = np.array([r["unix_s"] for r in r18 for _ in r["rr_ms"]], float)
    bv = np.array(rr, float)
    ok = (bv > 300) & (bv < 2000)
    g = np.arange(bt[0], bt[-1], 0.25)
    f, pw = welch(np.interp(g, bt[ok], bv[ok]) - bv[ok].mean(), fs=4, nperseg=512)
    m = (f >= 0.15) & (f <= 0.5)
    pk, _ = find_peaks(pw[m])
    fpk = f[m][pk[np.argmax(pw[m][pk])]] if len(pk) else float("nan")
    p(f"  cross-check (scipy Welch, wall-clock beat times, whole night, local peak in 0.15-0.5 Hz): "
      f"{fpk * 60:.1f} breaths/min (bin width {(f[1] - f[0]) * 60:.1f})")
    rng = np.random.default_rng(0)
    for true in (9.0, 14.0, 18.0):
        t, syn = 0.0, []
        while t < 600:
            x = 1150 + 60 * math.sin(2 * math.pi * true / 60 * t) + rng.normal(0, 15)
            syn.append(int(x))
            t += x / 1000
        v = [w["breaths_per_min"] for w in respiratory_rate(syn)]
        p(f"  synthetic RSA {true:.0f}/min (HR 52, 60 ms swing, 15 ms noise): median {np.median(v):.1f}/min")

    p("\n3. skin_temp_baseline (per sleep period)")
    for s in skin_temp_baseline(r18, periods):
        v = np.array([by_t[t]["skin_temp_c"] for t in range(s["onset_unix"], s["offset_unix"] + 1)
                      if t in by_t and by_t[t]["skin_temp_c"] is not None])
        p(f"  samples {s['samples']}, mean {s['mean_c']:.2f} C, min {s['min_c']:.2f}, max {s['max_c']:.2f}, "
          f"sd {s['sd_c']:.2f}; deviation {s['deviation_c']} (single night: no baseline)")
        p(f"  numpy: mean {v.mean():.2f}, min {v.min():.2f}, max {v.max():.2f}, sd {v.std():.2f}")
        late = v[len(v) // 4:]
        p(f"  after the first quarter of the night (sensor settled): mean {late.mean():.2f}, sd {late.std():.2f}")

    p("\n4. hr_from_r26 vs R18 heart_rate (mean over the burst's seconds) and vs scipy (analyze_r26.py method)")
    bursts = hr_from_r26(r26)
    groups = collections.defaultdict(list)
    for r in r26:
        groups[(r["burst_counter"])].append(r)
    ours, ref, sp = [], [], []
    for b in bursts:
        if b["heart_rate_bpm"] is None:
            continue
        sec = [by_t[t]["heart_rate"] for t in range(b["start_unix"], b["end_unix"] + 1) if t in by_t]
        recs = [r for r in groups[b["burst_counter"]] if b["start_unix"] <= r["unix_s"] <= b["end_unix"]]
        s = scipy_burst_hr(recs)
        if len(sec) >= 0.6 * b["seconds"] and s is not None:
            ours.append(b["heart_rate_bpm"])
            ref.append(float(np.mean(sec)))
            sp.append(s)
    ours, ref, sp = map(np.asarray, (ours, ref, sp))
    p(f"  bursts {len(bursts)}, with an estimate {sum(b['heart_rate_bpm'] is not None for b in bursts)}, scored {len(ours)}")
    p(f"  vs R18: r={corr(ours, ref):+.2f}  MAE={np.mean(np.abs(ours - ref)):.1f} bpm  bias={np.mean(ours - ref):+.1f}"
      f"  ref {ref.min():.0f}-{ref.max():.0f} bpm")
    p(f"  vs scipy: r={corr(ours, sp):+.3f}  max |diff|={np.max(np.abs(ours - sp)):.2f} bpm"
      f"  (scipy vs R18: r={corr(sp, ref):+.2f}, MAE={np.mean(np.abs(sp - ref)):.1f})")
    return periods


def corpus(root, p):
    p("\n5. Corpus (5.0/MG only, frames/by_type)")
    lines = []
    for name in ("HISTORICAL_DATA_L18.jsonl", "HISTORICAL_DATA_L26.jsonl"):
        lines += open(os.path.join(root, "frames", "by_type", name)).readlines()
    r18, r26 = load(lines)
    periods = sleep_periods(r18)
    p(f"  R18 records {len(r18)}: sleep periods {len(periods)}; durations h: "
      + ", ".join(f"{q['duration_s'] / 3600:.2f}" for q in periods))
    for s in skin_temp_baseline(r18, periods):
        dev = f"{s['deviation_c']:+.2f}" if s["deviation_c"] is not None else "n/a"
        p(f"    night mean {s['mean_c']:.2f} C (min {s['min_c']:.2f}, max {s['max_c']:.2f}), deviation {dev}")
    bursts = hr_from_r26(r26)
    est = [b for b in bursts if b["heart_rate_bpm"] is not None]
    by_t = {r["unix_s"]: r["heart_rate"] for r in r18}
    pairs = []
    for b in est:
        sec = [by_t[t] for t in range(b["start_unix"], b["end_unix"] + 1) if t in by_t]
        if len(sec) >= 0.6 * b["seconds"]:
            pairs.append((b["heart_rate_bpm"], float(np.mean(sec))))
    p(f"  R26 records {len(r26)}: bursts {len(bursts)}, with an estimate {len(est)}, with R18 reference {len(pairs)}")
    if pairs:
        a, r = np.asarray(pairs).T
        p(f"    vs R18: r={corr(a, r):+.2f}  MAE={np.mean(np.abs(a - r)):.1f} bpm")
    nr = [b["heart_rate_bpm"] for b in est]
    p(f"    all estimates: {min(nr):.0f}-{max(nr):.0f} bpm")


def main(argv):
    out = []
    p = out.append
    p("Experimental metrics on real captures (analyze_experimental_metrics.py)")
    p(f"generated {dt.date.today().isoformat()}; library: python/whoop5/experimental.py (stdlib)\n")
    overnight(argv[1], p)
    root = argv[2] if len(argv) > 2 else os.path.join(HERE, "..", "..", "whoop5-data")
    if os.path.isdir(root):
        corpus(root, p)
    text = "\n".join(out) + "\n"
    with open(os.path.join(HERE, "results", "experimental_metrics.txt"), "w") as fh:
        fh.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main(sys.argv)
