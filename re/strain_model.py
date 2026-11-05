"""Reverse-engineer WHOOP's day strain from your own per-second heart rate, empirically.

Day strain is a 0-21 logarithmic scale of cardiovascular load accumulated over the cycle, driven by time spent in
heart-rate zones (zones are % of max HR). This builds the load from the 1 Hz R18 heart rate this library decodes and,
when the WHOOP export's Day Strain is given for the same days, fits the mapping load -> strain so a client can show it.

Method (reusable regardless of the fit): per second, place HR in a WHOOP zone by % of max HR (50/60/70/80/90 %), sum
minutes per zone, and form Edwards TRIMP = sum(minutes_in_zone_i * i) for i = 1..5 (higher zones weigh more). Strain is
logarithmic, so the fit is day_strain ~ a * ln(1 + TRIMP) + b.

A cycle counts once it has a WHOOP Day Strain and at least 80 % HR coverage; the fit needs 5 such cycles. Re-read each
strain cycle's whole span (re/REREAD_HISTORY.md), not just its night. HR comes from frames.jsonl files and HCI captures.

  python re/strain_model.py <frames-folder> [export.zip]
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_own_strap import frames_in  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402

ZONE_EDGES = [0.50, 0.60, 0.70, 0.80, 0.90]  # WHOOP HR zones as a fraction of max HR; zone i is edge i..i+1


def hr_by_second(folder: str) -> dict[int, int]:
    hr = {}
    for frame in frames_in(folder):
        d = decode_frame(frame)
        if d.get("layout") == 18 and d.get("unix_s") and 25 <= (d.get("heart_rate") or 0) <= 230:
            hr[d["unix_s"]] = d["heart_rate"]
    return hr


def zone_minutes(hrs: list[int], hr_max: float) -> list[float]:
    """Minutes in each of the 5 WHOOP zones; one HR sample is one second. Below zone 1 is ignored (WHOOP's floor)."""
    edges = [e * hr_max for e in ZONE_EDGES]
    mins = [0.0] * 5
    for h in hrs:
        z = sum(1 for e in edges if h >= e)  # 0..5
        if z >= 1:
            mins[z - 1] += 1 / 60
    return mins


def edwards_trimp(mins: list[float]) -> float:
    return sum(m * (i + 1) for i, m in enumerate(mins))


def per_day(hr: dict[int, int], hr_max: float) -> dict[str, dict]:
    days: dict[str, list[int]] = {}
    for t, h in hr.items():
        days.setdefault(dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d"), []).append(h)
    out = {}
    for day, hrs in days.items():
        mins = zone_minutes(hrs, hr_max)
        out[day] = {"covered_h": round(len(hrs) / 3600, 1), "zone_min": [round(m) for m in mins],
                    "trimp": round(edwards_trimp(mins), 1)}
    return out


def fit_strain(pairs: list[tuple[float, float]]) -> dict:
    """day_strain ~ a*ln(1+TRIMP)+b. Needs several days with both; reports R2 and in-sample MAE."""
    if len(pairs) < 5:
        return {"days": len(pairs), "enough": False}
    x = np.array([math.log1p(t) for t, _ in pairs])
    y = np.array([s for _, s in pairs])
    a, b = np.polyfit(x, y, 1)
    pred = a * x + b
    ss_res, ss_tot = float(((y - pred) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    return {"days": len(pairs), "enough": True, "a": round(float(a), 3), "b": round(float(b), 3),
            "r2": 1 - ss_res / ss_tot if ss_tot else None, "mae": float(np.abs(y - pred).mean())}


def report(folder: str, export: str | None) -> None:
    hr = hr_by_second(folder)
    if not hr:
        print("no R18 heart rate found")
        return
    hr_max = max(hr.values())
    print(f"{len(hr)} HR seconds; max HR seen {hr_max} (zone reference)\n")
    days = per_day(hr, hr_max)
    strain = {}
    for day in sorted(days):
        d = days[day]
        print(f"  {day}  {d['covered_h']:>4.1f}h HR  zones {d['zone_min']}  TRIMP {d['trimp']}")
    # Strain is per WHOOP cycle, not per calendar day: a cycle can span ~48 h (a merged night). Sum TRIMP over the
    # cycle's exact [start, end) window and require the window to be near-fully covered by HR.
    if export:
        print(f"\n{'cycle start':>19} {'hours':>6} {'cover%':>6} {'TRIMP':>8} {'WHOOP strain':>12}")
        pairs = []
        for start_s, end_s, ws in cycle_strains(export):
            hrs = [h for t, h in hr.items() if start_s <= t < end_s]
            span_h = (end_s - start_s) / 3600
            cover = len(hrs) / (end_s - start_s) if end_s > start_s else 0
            trimp = round(edwards_trimp(zone_minutes(hrs, hr_max)), 1)
            if cover >= 0.8:
                pairs.append((trimp, ws))
            print(f"{dt.datetime.fromtimestamp(start_s):%Y-%m-%d %H:%M} {span_h:>5.1f}h {cover:>6.0%} {trimp:>8} {ws:>12}")
        print("\nfit (needs >=5 cycles with a WHOOP strain and >=80% HR coverage):", fit_strain(pairs))
        if not pairs:
            print("  no cycle has both yet — re-read each strain cycle's full [start,end) span, not just its night.")


def cycle_strains(export: str) -> list[tuple[int, int, float]]:
    """(start_unix, end_unix, day_strain) per export cycle that has a strain and an end time."""
    import csv as _csv, io as _io, zipfile as _zip
    texts = []
    if export.lower().endswith(".zip"):
        with _zip.ZipFile(export) as z:
            texts = [z.read(n).decode("utf-8-sig") for n in z.namelist()
                     if os.path.basename(n).lower() == "physiological_cycles.csv"]
    else:
        texts = [open(export, encoding="utf-8-sig").read()]

    def ts(v: str, tz: str) -> int | None:
        if not v:
            return None
        t = dt.datetime.fromisoformat(v.strip().replace("T", " ")[:19])
        if tz and tz.upper().startswith("UTC") and len(tz) > 3:
            sign = -1 if tz[3] == "-" else 1
            hh, _, mm = tz[4:].partition(":")
            t = t.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(hh), minutes=int(mm or 0))))
        return int((t if t.tzinfo else t.astimezone()).timestamp())

    out = []
    for text in texts:
        for row in _csv.DictReader(_io.StringIO(text)):
            g = lambda p: next((v for k, v in row.items() if k.strip().lower().startswith(p)), None)
            tz = g("cycle timezone") or ""
            start, end, ds = ts(g("cycle start") or "", tz), ts(g("cycle end") or "", tz), g("day strain")
            if start and end and ds not in (None, ""):
                out.append((start, end, float(ds)))
    return out


def _self_test() -> None:
    assert abs(zone_minutes([150] * 60, 180)[3] - 1.0) < 1e-9  # 150/180 = 0.83 -> zone 4 (80-90%), 60 s = 1 min
    assert zone_minutes([80] * 60, 180) == [0.0] * 5  # 80/180 = 0.44 < zone 1 floor
    assert abs(edwards_trimp([1, 1, 1, 1, 1]) - 15) < 1e-9
    assert fit_strain([(10, 5)] * 3) == {"days": 3, "enough": False}
    f = fit_strain([(t, 2 * math.log1p(t) + 1) for t in (5, 20, 60, 120, 300, 600)])
    assert f["enough"] and f["r2"] > 0.999, f


if __name__ == "__main__":
    _self_test()
    if len(sys.argv) >= 2:
        report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__.strip().splitlines()[-1])
