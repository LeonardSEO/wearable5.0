"""Do WHOOP's workout zones equal fixed percentages of heart rate reserve? And which load reproduces strain with those zones?

Heart rate reserve (HRR) = (HR - resting HR) / (max HR - resting HR). Raw HR comes from the strap; zone seconds, strain, and max HR
from an API snapshot.

  python re/hrr_zones.py <frames folder> <API snapshot folder>
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ZONE_KEYS = ("zone_zero_milli", "zone_one_milli", "zone_two_milli", "zone_three_milli", "zone_four_milli", "zone_five_milli")
EDGES = (0.4, 0.6, 0.7, 0.8, 0.9)


def unix(text: str) -> int:
    return int(dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def zone_seconds(hrs, rest: float, max_hr: float, edges=EDGES) -> list[int]:
    counts = [0] * (len(edges) + 1)
    for h in hrs:
        counts[sum((h - rest) / (max_hr - rest) >= e for e in edges)] += 1
    return counts


def zone_error(hrs, target, rest, max_hr, edges=EDGES) -> float:
    return sum(abs(a - b) for a, b in zip(zone_seconds(hrs, rest, max_hr, edges), target))


def loads(hrs, rest: float, max_hr: float) -> dict[str, float]:
    """Candidate training loads for one window of 1 Hz heart rate."""
    x = np.clip((np.asarray(hrs, float) - rest) / (max_hr - rest), 0, 1.2)
    zones = np.array([sum(v >= e for e in EDGES) for v in x])
    out = {"seconds_above_z0": float((zones >= 1).sum() / 60)}
    out["edwards_hrr"] = float(zones.sum() / 60)
    for b in (1.67, 1.92, 2.5, 3.0):
        out[f"banister_b{b}"] = float((x * 0.64 * np.exp(b * x)).sum() / 60)
    for floor in (0.3, 0.4, 0.5):
        y = np.clip(x - floor, 0, None)
        for p in (1, 2, 3, 4):
            out[f"excess{floor}^{p}"] = float((y ** p).sum() / 60)
    return out


def fit_log(load: np.ndarray, strain: np.ndarray) -> tuple[float, float, float, float]:
    """strain = a ln(1 + b load) by a search over b; returns a, b, mean error, largest error."""
    best = (0.0, 0.0, math.inf, math.inf)
    for b in np.logspace(-5, 2, 1400):
        x = np.log1p(b * load)
        a = float(x @ strain / (x @ x))
        res = np.abs(a * x - strain)
        if res.mean() < best[2]:
            best = (a, float(b), float(res.mean()), float(res.max()))
    return best


def main() -> None:
    from strain_model import hr_by_second
    hr = hr_by_second(sys.argv[1])
    load = lambda n: json.load(open(os.path.join(sys.argv[2], f"{n}.json")))
    max_hr = load("body_measurement")["max_heart_rate"]
    workouts = sorted(load("workouts"), key=lambda w: w["start"])
    print(f"maximum HR from the API: {max_hr}")
    windows = []
    rests = np.arange(50, 66)
    for w in workouts:
        hrs = [hr[t] for t in range(unix(w["start"]), unix(w["end"])) if t in hr]
        target = [w["score"]["zone_durations"][k] / 1000 for k in ZONE_KEYS]
        windows.append((f"workout {w['sport_name']}", hrs, w["score"]["strain"]))
        print(f"{w['sport_name']}: {len(hrs)} s; WHOOP seconds per zone {[int(v) for v in target]}")
    best = sorted((sum(zone_error([hr[t] for t in range(unix(w['start']), unix(w['end'])) if t in hr],
                                  [w["score"]["zone_durations"][k] / 1000 for k in ZONE_KEYS], r, max_hr) for w in workouts), int(r)) for r in rests)
    print("resting HR that fits best (total seconds off, resting HR):", best[:4])
    rest = best[0][1]
    for w in workouts:
        hrs = [hr[t] for t in range(unix(w["start"]), unix(w["end"])) if t in hr]
        print(f"  {w['sport_name']} at rest {rest}: ours {zone_seconds(hrs, rest, max_hr)}")
    print("other zone edges for comparison, total seconds off at each edge set's best rest:")
    for edges in (EDGES, (0.5, 0.6, 0.7, 0.8, 0.9), (0.3, 0.6, 0.7, 0.8, 0.9), (0.4, 0.5, 0.6, 0.7, 0.8)):
        errs = [sum(zone_error([hr[t] for t in range(unix(w['start']), unix(w['end'])) if t in hr],
                               [w["score"]["zone_durations"][k] / 1000 for k in ZONE_KEYS], r, max_hr, edges) for w in workouts) for r in rests]
        print(f"  {edges}: {min(errs):.0f} s of {sum(unix(w['end']) - unix(w['start']) for w in workouts)} s")

    for c in sorted(load("cycles"), key=lambda c: c["start"]):
        end = unix(c["end"]) if c.get("end") else unix(c["updated_at"])
        hrs = [hr[t] for t in range(unix(c["start"]), end) if t in hr]
        cover = len(hrs) / (end - unix(c["start"]))
        print(f"cycle: {cover:.1%} covered, strain {c['score']['strain']:.3f}")
        if cover >= 0.9:
            windows.append((f"cycle {c['start'][:10]}", hrs, c["score"]["strain"]))
    strain = np.array([v[2] for v in windows])
    table = [loads(v[1], rest, max_hr) for v in windows]
    print(f"\nstrain = a ln(1 + b load) on {len(windows)} windows, two free parameters:")
    rows = []
    for name in table[0]:
        values = np.array([t[name] for t in table])
        rows.append((*fit_log(values, strain)[2:], name, fit_log(values, strain)[:2]))
    for mean_err, worst, name, (a, b) in sorted(rows)[:8]:
        print(f"  {name:18} mean error {mean_err:.3f}  largest {worst:.3f}  a {a:.3f}  b {b:.5f}")


if __name__ == "__main__":
    main()
