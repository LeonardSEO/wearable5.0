"""Test the registered score formulas on an export, with their coefficients frozen.

The models and their coefficients come from re/SCORE_MODELS.md. Only cycles that started after SEEN_UNTIL count as evidence:
those did not shape the formulas. Refitting makes a new model with a new id; it never changes one here.

  python re/score_predictions.py <export.zip> [--frames FOLDER]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import os
import sys
import zipfile

SEEN_UNTIL = "2026-11-05 00:07:47"
COVERAGE_MIN = 0.8


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def sp_q(s):
    return 94.6 * (1 - max(0, 1 - s["asleep"] / s["need"] / 1.122) ** 2)


def sp_e(s):
    return max(0, 95 - 440 * math.exp(-5 * s["asleep"] / s["need"]))


ALPHA = 77 / 155
DEBT_MODELS = {
    "SD-R": lambda d, short: ALPHA * max(0, short),
    "SD-A": lambda d, short: max(0, d + ALPHA * short),
    "SD-CAP": lambda d, short: min(77, max(0, d + short)),
}
SLEEP_MODELS = {"SP-Q": sp_q, "SP-E": sp_e}
RECOVERY_MODELS = {"R-SLEEP": lambda c: 0.13 * c["asleep"] - 11.17, "R-HRV": lambda c: 119.5 - 2.25 * c["hrv"]}
STRAIN_MODELS = {
    "DS-C": lambda t, cov: 0.0122 * t / cov,
    "DS-LOG": lambda t, cov: 103.0755474924 * math.log1p(0.000125875610188 * t),
    "DS-LIN": lambda t, cov: 0.276384180791 + 0.0119451170299 * t,
    "DS-POW": lambda t, cov: 0.0158397708 * t ** 0.9624546654,
}


def read_csv(z: zipfile.ZipFile, name: str) -> list[dict]:
    path = next(n for n in z.namelist() if os.path.basename(n).lower() == name)
    return list(csv.DictReader(io.StringIO(z.read(path).decode("utf-8-sig"))))


def load(path: str) -> tuple[list[dict], list[dict]]:
    with zipfile.ZipFile(path) as z:
        sleeps = [{"onset": r["Sleep onset"], "wake": r["Wake onset"], "asleep": _num(r["Asleep duration (min)"]),
                   "need": _num(r["Sleep need (min)"]), "debt": _num(r["Sleep debt (min)"]),
                   "perf": _num(r["Sleep performance %"]), "in_bed": _num(r["In bed duration (min)"]),
                   "nap": (r.get("Nap") or "").strip().lower() == "true"} for r in read_csv(z, "sleeps.csv")]
        cycles = [{"start": r["Cycle start time"], "end": r["Cycle end time"], "recovery": _num(r["Recovery score %"]),
                   "strain": _num(r["Day Strain"]), "hrv": _num(r["Heart rate variability (ms)"]),
                   "asleep": _num(r["Asleep duration (min)"])} for r in read_csv(z, "physiological_cycles.csv")]
    return sorted(sleeps, key=lambda s: s["onset"]), sorted(cycles, key=lambda c: c["start"])


def predictions(sleeps: list[dict], cycles: list[dict], trimp: dict[str, tuple[float, float]]) -> list[dict]:
    """One row per model per observation: when, what was predicted and what WHOOP reported."""
    out = []

    def add(model, when, value, actual, resolution):
        if actual is not None:
            out.append({"model": model, "when": when, "predicted": value, "actual": actual, "resolution": resolution,
                        "new": when > SEEN_UNTIL})

    for s in sleeps:
        if s["need"] and s["asleep"] is not None:
            for name, f in SLEEP_MODELS.items():
                add(name, s["onset"], f(s), s["perf"], 1.0)
    state = {name: None for name in DEBT_MODELS}
    for s in sleeps:
        for name in DEBT_MODELS:
            if state[name] is not None:
                add(name, s["onset"], state[name], s["debt"], 1.0)
        if s["need"] is None or s["asleep"] is None or s["debt"] is None:
            continue
        for name, f in DEBT_MODELS.items():
            incoming = s["debt"]
            state[name] = incoming if s["nap"] else f(incoming, s["need"] - s["asleep"])
    for c in cycles:
        for name, f in RECOVERY_MODELS.items():
            if c["asleep"] is not None and c["hrv"] is not None:
                add(name, c["start"], f(c), c["recovery"], 1.0)
        if c["start"] in trimp:
            t, cov = trimp[c["start"]]
            for name, f in STRAIN_MODELS.items():
                add(name, c["start"], f(t, cov), c["strain"], 0.1)
    return out


def in_rounding(row: dict) -> bool:
    return abs(row["predicted"] - row["actual"]) <= row["resolution"] / 2 + 1e-9


def trimp_by_cycle(cycles: list[dict], folder: str) -> dict[str, tuple[float, float]]:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from strain_model import edwards_trimp, hr_by_second, zone_minutes
    hr = hr_by_second(folder)
    hr_max = max(hr.values())
    out = {}
    for c in cycles:
        if not c["end"]:
            continue
        a, b = (dt.datetime.fromisoformat(c[k]).timestamp() for k in ("start", "end"))
        hrs = [h for t, h in hr.items() if a <= t < b]
        if b > a and len(hrs) / (b - a) >= COVERAGE_MIN:
            out[c["start"]] = (edwards_trimp(zone_minutes(hrs, hr_max)), len(hrs) / (b - a))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("export")
    ap.add_argument("--frames")
    args = ap.parse_args()
    sleeps, cycles = load(args.export)
    rows = predictions(sleeps, cycles, trimp_by_cycle(cycles, args.frames) if args.frames else {})
    print("| model | data that shaped it | new data, in rounding | new data, mean difference |")
    print("|---|---:|---:|---:|")
    for model in sorted({r["model"] for r in rows}):
        seen = [r for r in rows if r["model"] == model and not r["new"]]
        new = [r for r in rows if r["model"] == model and r["new"]]
        hits = sum(in_rounding(r) for r in seen)
        mae = f"{sum(abs(r['predicted'] - r['actual']) for r in new) / len(new):.2f}" if new else ""
        print(f"| {model} | {hits} of {len(seen)} | {sum(in_rounding(r) for r in new)} of {len(new)} | {mae} |")
    for r in (r for r in rows if r["new"]):
        print(f"{r['when']}  {r['model']:8} predicted {r['predicted']:7.2f}  WHOOP {r['actual']:7.2f}  "
              f"{'in rounding' if in_rounding(r) else 'MISS'}")


if __name__ == "__main__":
    main()
