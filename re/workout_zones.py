"""Which maximum heart rate and time shift reproduce WHOOP's zone shares for one workout, from raw strap heart rate?

Zones are 50/60/70/80/90 % of the maximum. Only the zones are fitted. WHOOP's mean and maximum are not, so they check the fit.

  python re/workout_zones.py <export.zip> <frames folder> [workout row, default 0]
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
EDGES = (0.5, 0.6, 0.7, 0.8, 0.9)
SHIFTS = range(-3600, 3601, 30)
MAX_HRS = range(160, 231)


def zone_shares(hrs: list[int], max_hr: int) -> list[float]:
    counts = [0] * 6
    for h in hrs:
        counts[sum(h / max_hr >= e for e in EDGES)] += 1
    return [100 * c / len(hrs) for c in counts][1:]


def fit(hr: dict[int, int], start: int, end: int, target: list[float]) -> list[dict]:
    results = []
    for shift in SHIFTS:
        hrs = [hr[t + shift] for t in range(start, end + 1) if t + shift in hr]
        if len(hrs) < 0.9 * (end - start + 1):
            continue
        for m in MAX_HRS:
            shares = zone_shares(hrs, m)
            results.append({"error": sum(abs(a - b) for a, b in zip(shares, target)), "shift_s": shift, "max_hr": m,
                            "mean": sum(hrs) / len(hrs), "max": max(hrs), "shares": [round(s, 1) for s in shares]})
    return sorted(results, key=lambda r: r["error"])


def main() -> None:
    from strain_model import hr_by_second
    with zipfile.ZipFile(sys.argv[1]) as z:
        name = next(n for n in z.namelist() if os.path.basename(n).lower() == "workouts.csv")
        w = list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig"))))[int(sys.argv[3]) if len(sys.argv) > 3 else 0]
    start, end = (int(dt.datetime.fromisoformat(w[k]).timestamp()) for k in ("Workout start time", "Workout end time"))
    target = [float(w[f"HR Zone {i} %"]) for i in range(1, 6)]
    print(f"{w['Activity name']}: zones {target}, WHOOP mean {w['Average HR (bpm)']}, max {w['Max HR (bpm)']}")
    for r in fit(hr_by_second(sys.argv[2]), start, end, target)[:5]:
        print(f"error {r['error']:.2f}  shift {r['shift_s']} s  max HR {r['max_hr']}  mean {r['mean']:.1f}  max {r['max']}  {r['shares']}")


if __name__ == "__main__":
    main()
