"""Put NOOP's own Charge and Effort next to WHOOP's Recovery and Day Strain on the same cycles.

Runs NOOP's real scoring code through re/noop_scores, a small program that links a local NOOP checkout. Nothing of NOOP is
copied here. NOOP's sleep input is its own Rest score; WHOOP's Sleep performance stands in for it.

  (cd re/noop_scores && NOOP_DIR=<noop checkout> swift build -c release)
  python re/noop_compare.py <export.zip> [--frames FOLDER]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_search import add_previous_cycle, load_rows  # noqa: E402

BINARY = os.path.join(HERE, "noop_scores", ".build", "release", "noop-scores")
WHOOP_STRAIN_MAX, NOOP_EFFORT_MAX = 21.0, 100.0


def _opt(x):
    return None if x is None or math.isnan(x) else x


def build_input(rows: list[dict], hr: dict[int, int]) -> dict:
    nights = [{"hrv": _opt(r.get("hrv")), "rhr": _opt(r.get("rhr")), "resp": _opt(r.get("resp")),
               "sleepPerf": _opt(r.get("sleep_perf"))} for r in rows]
    hr_max = float(max(hr.values())) if hr else None
    cycles = []
    for r in rows:
        samples = []
        if hr and r.get("start") and r.get("end"):
            start = dt.datetime.fromisoformat(r["start"]).timestamp()
            end = dt.datetime.fromisoformat(r["end"]).timestamp()
            samples = sorted([t, b] for t, b in hr.items() if start <= t < end)
            if end <= start or len(samples) / (end - start) < 0.8:
                samples = []
        cycles.append({"hr": samples, "restingHR": _opt(r.get("rhr")), "maxHR": hr_max})
    return {"nights": nights, "cycles": cycles}


def fmt(x, digits=1):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{digits}f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source")
    ap.add_argument("--frames")
    args = ap.parse_args()
    rows = load_rows(args.source)
    add_previous_cycle(rows)
    hr = {}
    if args.frames:
        from strain_model import hr_by_second
        hr = hr_by_second(args.frames)
    out = json.loads(subprocess.run([BINARY], input=json.dumps(build_input(rows, hr)), text=True, capture_output=True,
                                    check=True).stdout)
    print("| cycle start | WHOOP Recovery | NOOP Charge | WHOOP Day Strain | NOOP Effort | Effort on the 0-21 axis |")
    print("|---|---:|---:|---:|---:|---:|")
    charge_err, strain_err = [], []
    for r, c, e in zip(rows, out["charge"], out["effort"]):
        on_axis = None if e is None else e * WHOOP_STRAIN_MAX / NOOP_EFFORT_MAX
        print(f"| {r.get('start', '')} | {fmt(r.get('recovery'), 0)} | {fmt(c)} | {fmt(r.get('strain'))} | {fmt(e)} | {fmt(on_axis)} |")
        if c is not None and not math.isnan(r.get("recovery", math.nan)):
            charge_err.append(abs(c - r["recovery"]))
        if on_axis is not None and not math.isnan(r.get("strain", math.nan)):
            strain_err.append(abs(on_axis - r["strain"]))
    for label, errs in (("Charge vs Recovery", charge_err), ("Effort vs Day Strain", strain_err)):
        print(f"\n{label}: {len(errs)} cycles" + (f", mean difference {sum(errs) / len(errs):.2f}" if errs else ", none scored"))


if __name__ == "__main__":
    main()
