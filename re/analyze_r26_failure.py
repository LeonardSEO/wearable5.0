"""Why R26 heart rate failed on a full day of data, and what `hr_from_r26` accepts now (FINDINGS §16).

Input: a folder with frames.jsonl snapshots (re/export_noop_db.py), the same folder validate_own_strap.py reads.
Writes re/results/r26_failure.txt: aggregates only, no timestamps, identifiers or frames.

The reference is the R18 heart rate over the burst's seconds. Awake and moving, R18 mostly has no R-R to check it
against, so that reference is the strap's own algorithm rather than independent truth.

Usage (workspace root): .venv/bin/python -I wearable5.0/re/analyze_r26_failure.py whoop5-data/own_strap
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from collections import defaultdict

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "python")]
from validate_own_strap import frames_in  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402
from whoop5.experimental import hr_from_r26  # noqa: E402

FS = 25.0
out = []


def p(line: str = "") -> None:
    print(line)
    out.append(line)


def old_peak_bpm(x: np.ndarray) -> float | None:
    """The method hr_from_r26 used before: 60 / median interval between inverted peaks."""
    b, a = butter(3, [0.6 / (FS / 2), 3.3 / (FS / 2)], "band")
    y = -filtfilt(b, a, x - np.median(x))
    pk, _ = find_peaks(y, distance=8, prominence=0.3 * np.std(y))
    ibi = np.diff(pk) / FS
    ibi = ibi[(ibi > 0.3) & (ibi < 2.0)]
    return 60.0 / float(np.median(ibi)) if len(ibi) >= 5 else None


def pulse_snr(x: np.ndarray, bpm: float) -> float:
    """Power at the reference heart rate relative to the median 0.6-3.5 Hz background."""
    b, a = butter(2, [0.5 / (FS / 2), 4 / (FS / 2)], "band")
    y = filtfilt(b, a, x - x.mean()) * np.hanning(len(x))
    power = np.abs(np.fft.rfft(y, n=len(y) * 4)) ** 2
    f = np.fft.rfftfreq(len(y) * 4, 1 / FS)
    hz = bpm / 60
    return float(power[np.abs(f - hz) <= 0.05].max() / np.median(power[(f > 0.6) & (f < 3.5) & (np.abs(f - hz) > 0.15)]))


def score(name: str, rows: list[dict], key: str) -> None:
    errs = [abs(r[key] - r["ref"]) for r in rows if r[key]]
    if not errs:
        p(f"  {name:32s} n=  0")
        return
    within = sum(e <= 3 for e in errs) / len(errs)
    p(f"  {name:32s} n={len(errs):3d} MAE {st.mean(errs):5.1f}  median {st.median(errs):5.1f}  within 3 bpm {within:4.0%}"
      f"  doubled {sum(r[key] > 1.5 * r['ref'] for r in rows if r[key])}")


def main(folder: str) -> None:
    seen, r18, r26 = set(), {}, {}
    imu = {}
    for f in frames_in(folder):
        if f in seen or len(f) not in (124, 88, 1244):
            continue
        seen.add(f)
        d = decode_frame(f)
        if d.get("layout") == 18:
            r18.setdefault(d["unix_s"], d)
        elif d.get("layout") == 26:
            r26.setdefault(d["record_index"], d)
        elif d.get("layout") == 21 and d.get("accel_count") == 100:
            imu[d["unix_s"]] = np.array([d["accel_x"], d["accel_y"], d["accel_z"]], float) / 4096
    by_time = defaultdict(list)
    for r in r26.values():
        by_time[r["unix_s"]].append(r)

    rows = []
    for b in hr_from_r26(list(r26.values())):
        span = range(b["start_unix"], b["end_unix"] + 1)
        recs = [r18[t] for t in span if t in r18]
        ref = [r["heart_rate"] for r in recs if 25 <= r["heart_rate"] <= 230]
        burst = [next(r for r in by_time[t] if r["burst_counter"] == b["burst_counter"]) for t in span]
        if not ref or not b["candidate_bpm"]:
            continue
        x = np.array([s for r in burst for s in r["samples"]], float)
        row = dict(b, ref=sum(ref) / len(ref), state=st.mode(r["band_state"] for r in recs), x=x,
                   motion=st.mean(r["motion_summary"] for r in burst), old=old_peak_bpm(x))
        accel = [imu[t] for t in span if t in imu]
        if len(accel) >= 0.8 * len(span):
            m = np.linalg.norm(np.hstack(accel), axis=0)
            spec = np.abs(np.fft.rfft((m - m.mean()) * np.hanning(len(m)), n=len(m) * 4)) ** 2
            f = np.fft.rfftfreq(len(m) * 4, 1 / 100)
            band = (f >= 0.5) & (f <= 3.5)
            row["imu_bpm"] = float(f[band][np.argmax(spec[band])] * 60)
        rows.append(row)
    rows.sort(key=lambda r: r["start_unix"])
    p(f"{len(rows)} R26 bursts with an R18 reference")

    p("\n1. The old estimator (inverted peaks, median interval), by band state")
    for s in ("SLEEP", "STILL", "UP", "WAKE"):
        score(s, [r for r in rows if r["state"] == s], "old")

    p("\n2. Old estimator: motion or high heart rate? (motion_summary 0.03; reference 90 bpm)")
    for hn, hi in (("reference < 90", False), ("reference >= 90", True)):
        for mn, mv in (("still", False), ("moving", True)):
            score(f"{hn}, {mn}", [r for r in rows if (r["ref"] >= 90) == hi and (r["motion"] >= 0.03) == mv], "old")

    p("\n3. Is the pulse visible? Median power at the reference heart rate over the background")
    for s in ("SLEEP", "WAKE"):
        v = [pulse_snr(r["x"], r["ref"]) for r in rows if r["state"] == s]
        p(f"  {s:6s} {st.median(v):8.1f}  (n={len(v)})")

    p("\n4. Motion lock: does the old estimate sit at the wrist-motion frequency, its double or half (within 8 %)?")
    with_imu = [r for r in rows if "imu_bpm" in r and r["old"]]
    for name, sel in (("right, within 3 bpm", lambda r: abs(r["old"] - r["ref"]) <= 3),
                      ("wrong, over 10 bpm", lambda r: abs(r["old"] - r["ref"]) > 10)):
        s = [r for r in with_imu if sel(r)]
        lock = sum(any(abs(r["old"] - k * r["imu_bpm"]) / (k * r["imu_bpm"]) < 0.08 for k in (0.5, 1, 2)) for r in s)
        p(f"  {name:22s} {lock} of {len(s)}" + (f" ({lock / len(s):.0%})" if s else ""))

    half = rows[len(rows) // 2]["start_unix"]
    p("\n5. hr_from_r26 now (autocorrelation; acceptance >= 0.5 and periodicity >= 0.3)")
    score("old estimator, all bursts", rows, "old")
    score("new candidate, all bursts", rows, "candidate_bpm")
    score("new, accepted", rows, "heart_rate_bpm")
    score("  first half of the data", [r for r in rows if r["start_unix"] < half], "heart_rate_bpm")
    score("  second half of the data", [r for r in rows if r["start_unix"] >= half], "heart_rate_bpm")
    for s in ("SLEEP", "WAKE"):
        sel = [r for r in rows if r["state"] == s]
        score(f"  {s} ({sum(1 for r in sel if r['heart_rate_bpm'])} of {len(sel)} accepted)", sel, "heart_rate_bpm")
    kept = [r["ref"] for r in rows if r["heart_rate_bpm"]]
    p(f"  accepted {len(kept)} of {len(rows)} bursts; reference range {min(kept):.0f}-{max(kept):.0f} bpm")

    path = os.path.join(HERE, "results", "r26_failure.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
