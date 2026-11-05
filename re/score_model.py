"""Reverse-engineer WHOOP's recovery, strain and sleep scores from your own account, empirically.

WHOOP computes the scores server-side (FINDINGS 19 / the RE ledger), so there is no formula to read out of the app.
But your WHOOP data export pairs each cycle's inputs (HRV, resting HR, respiratory rate, sleep) with the score WHOOP
assigned, and those input/output pairs are yours. This fits a model per score on that history and reports how well it
reproduces WHOOP, so a client can show the same numbers from the inputs this library already decodes.

What it is and is not: recovery and strain are personalized and baseline-relative (WHOOP normalizes against your own
~30-day baseline), so a fit on one account reproduces *that account's* mapping, not a universal constant. It needs
enough cycles: with fewer than `MIN_CYCLES` it reports the data as insufficient rather than a flattering fit on noise.

Input: your full WHOOP export (the .zip from app.whoop.com, or its `physiological_cycles.csv`). Export your whole
history, not one week.

  python re/score_model.py <export.zip | physiological_cycles.csv | folder>

Targets:
  sleep_performance  asleep / sleep-need, the simplest; expected near-exact.
  recovery           linear fit of recovery % on HRV, resting HR, respiratory rate and sleep performance (standardized).
  strain             documented only here: a 0-21 logarithmic cardiovascular load that needs intraday HR time-in-zone,
                     not just the per-cycle export columns. Settled once per-second day HR (re-read frames) is joined.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import zipfile

import numpy as np

MIN_CYCLES = 20
FEATURES = ["hrv", "rhr", "resp", "sleep_perf"]  # recovery inputs WHOOP documents publicly


def _num(v):
    try:
        return float(v) if v not in (None, "", "NaN") else None
    except ValueError:
        return None


def _col(row: dict, *prefixes: str):
    for k, v in row.items():
        if k and any(k.strip().lower().startswith(p) for p in prefixes):
            return v
    return None


def load_cycles(path: str) -> list[dict]:
    """Every cycle from the export, as {recovery, strain, hrv, rhr, resp, skin_temp, asleep_min, need_min, sleep_perf}."""
    texts = []
    if os.path.isdir(path):
        for root, _d, files in os.walk(path):
            for n in files:
                if n.lower() == "physiological_cycles.csv":
                    texts.append(open(os.path.join(root, n), encoding="utf-8-sig").read())
    elif path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            texts = [z.read(n).decode("utf-8-sig") for n in z.namelist()
                     if os.path.basename(n).lower() == "physiological_cycles.csv"]
    else:
        texts = [open(path, encoding="utf-8-sig").read()]
    out = []
    for text in texts:
        for row in csv.DictReader(io.StringIO(text)):
            asleep, need = _num(_col(row, "asleep duration")), _num(_col(row, "sleep need"))
            out.append({
                "recovery": _num(_col(row, "recovery score")), "strain": _num(_col(row, "day strain")),
                "hrv": _num(_col(row, "heart rate variability")), "rhr": _num(_col(row, "resting heart rate")),
                "resp": _num(_col(row, "respiratory rate")), "skin_temp": _num(_col(row, "skin temp")),
                "asleep_min": asleep, "need_min": need,
                "sleep_perf": _num(_col(row, "sleep performance"))})
    return out


def fit_linear(rows: list[dict], target: str, features: list[str]) -> dict:
    """Least-squares fit of `target` on standardized `features`; leave-one-out MAE so a small n is not flattered."""
    full = [r for r in rows if r[target] is not None and all(r[f] is not None for f in features)]
    n = len(full)
    if n < MIN_CYCLES:
        return {"target": target, "cycles": n, "enough": False}
    X = np.array([[r[f] for f in features] for r in full], float)
    y = np.array([r[target] for r in full], float)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Xs = np.column_stack([(X - mu) / sd, np.ones(n)])
    beta, *_ = np.linalg.lstsq(Xs, y, rcond=None)
    pred = Xs @ beta
    ss_res, ss_tot = float(((y - pred) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    # Leave-one-out: refit without each row, predict it.
    loo = []
    for i in range(n):
        m = np.ones(n, bool); m[i] = False
        b, *_ = np.linalg.lstsq(Xs[m], y[m], rcond=None)
        loo.append(abs(y[i] - Xs[i] @ b))
    return {"target": target, "cycles": n, "enough": True,
            "r2": 1 - ss_res / ss_tot if ss_tot else None,
            "mae_in_sample": float(np.abs(y - pred).mean()), "mae_loo": float(np.mean(loo)),
            "coef": {f: round(float(c), 3) for f, c in zip(features, beta[:-1])}, "intercept": round(float(beta[-1]), 2)}


def sleep_performance(rows: list[dict]) -> dict:
    pairs = [(100 * r["asleep_min"] / r["need_min"], r["sleep_perf"]) for r in rows
             if r["asleep_min"] and r["need_min"] and r["sleep_perf"] is not None]
    if not pairs:
        return {"target": "sleep_performance", "cycles": 0, "enough": False}
    err = [abs(a - b) for a, b in pairs]
    return {"target": "sleep_performance", "cycles": len(pairs), "enough": len(pairs) >= 3,
            "ratio_mae_pct": round(float(np.mean(err)), 2),
            "note": "WHOOP sleep performance % vs 100*asleep/need; close means it is that ratio"}


def report(path: str) -> None:
    rows = load_cycles(path)
    print(f"{len(rows)} cycles from {path}\n")
    print("sleep_performance:", sleep_performance(rows))
    rec = fit_linear(rows, "recovery", FEATURES)
    print("recovery:", rec)
    if not rec["enough"]:
        print(f"  need >= {MIN_CYCLES} cycles with all of {FEATURES}; export your full WHOOP history.")
    print("strain: documented only — 0-21 log cardiovascular load; needs intraday HR time-in-zone,")
    print("        join per-second day HR from re-read frames (re/REREAD_HISTORY.md), not in these columns.")


def _self_test() -> None:
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(60):
        hrv, rhr = rng.normal(60, 12), rng.normal(55, 5)
        rec = 0.9 * hrv - 1.2 * rhr + 100 + rng.normal(0, 2)
        rows.append({"recovery": rec, "strain": None, "hrv": hrv, "rhr": rhr, "resp": 15.0,
                     "skin_temp": 34.0, "asleep_min": 420, "need_min": 480, "sleep_perf": 87.5})
    f = fit_linear(rows, "recovery", FEATURES)
    assert f["enough"] and f["r2"] > 0.95, f
    assert abs(sleep_performance(rows)["ratio_mae_pct"] - 0.0) < 0.01
    assert fit_linear(rows[:5], "recovery", FEATURES) == {"target": "recovery", "cycles": 5, "enough": False}


if __name__ == "__main__":
    _self_test()
    if len(sys.argv) == 2:
        report(sys.argv[1])
    else:
        print(__doc__.strip().splitlines()[-1])
