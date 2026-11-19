"""Head-to-head: NOOP's own scorers and this repository's formulas against WHOOP, on the same nights, cycles and workouts.

NOOP runs through re/noop_scores, a small program that links a NOOP checkout (nothing of NOOP is copied here):
  git -C <noop clone> worktree add --detach ../noop-upstream upstream/main      # upstream ryanbr/noop, not a fork branch
  (cd re/noop_scores && NOOP_DIR=<that worktree> swift build -c release)
  python re/noop_compare.py <API snapshot folder> <own strap data folder> [--noop-dir DIR] [--hr-cache FILE] [--per-night]

Inputs: an API snapshot from re/whoop_api_fetch.py (sleeps, recoveries, cycles, workouts, body_measurement) and a folder of
the owner's strap frames (per-second R18 heart rate). Output is aggregates only; --per-night adds dated rows for local use.

Choices fixed before the first run (tier a: WHOOP's measured inputs go into both sides):
- NOOP gets what its app path uses: WHOOP's HRV, resting HR, respiration and skin temperature per night; sleep totals for its
  Rest; per-second strap HR with the night's resting HR per cycle. Charge runs twice: with NOOP's own Rest (the app path)
  and with WHOOP's sleep performance. WHOOP's consistency into Rest and WHOOP's maximum HR into the zones favour NOOP.
- Sleep need: each side its own model. Both start from zero debt, skip days without a sleep record, get the same naps and
  leave out the first WARMUP nights. Ours chains baseline + debt + recent-strain need - nap asleep from its own previous need.
- Every number of ours is out-of-sample: leave-one-out with the constants refitted per fold, or a rule frozen before the data
  (the zone rule ZR-1 before the later workouts). NOOP never saw this data either.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import statistics as st
import subprocess
import sys
from collections import defaultdict

import numpy as np
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hrr_zones import ZONE_KEYS, zone_seconds  # noqa: E402
from score_formulas import baseline_ms, debt_ms, sleep_performance, strain_need_ms  # noqa: E402

BINARY = os.path.join(HERE, "noop_scores", ".build", "release", "noop-scores")
WARMUP = 3            # nights not scored for sleep need and sleep score while both debt models start from zero
FIRST_RECOVERY = 4    # WHOOP calibrates the first recoveries; scoring starts after them
ZR1_REST = 58         # zone rule ZR-1, frozen on the workouts before ZR1_FROZEN_UTC (re/hrr_zones.py)
ZR1_FROZEN_UTC = "2026-11-05T18:00:00+00:00"
MUSCULAR = {"skiing", "weightlifting"}   # DS-E is a cardio-load formula; cycles with these sports are reported apart
HRV_PRIOR, HRV_PRIOR_WEIGHT = 103.2555, 5.0265


def parse(t: str) -> dt.datetime:
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))


def load_api(folder: str):
    def load(name):
        x = json.load(open(os.path.join(folder, f"{name}.json")))
        return x.get("records", x) if isinstance(x, dict) and "records" in x else x
    return {n: load(n) for n in ("sleeps", "recoveries", "cycles", "workouts", "body_measurement")}


def asleep(s: dict) -> int:
    t = s["score"]["stage_summary"]
    return t["total_light_sleep_time_milli"] + t["total_slow_wave_sleep_time_milli"] + t["total_rem_sleep_time_milli"]


def summary(label: str, pairs, tol: float, unit: str = "") -> dict:
    e = [abs(a - b) for a, b in pairs]
    out = {"label": label, "n": len(e), "mean": float(st.mean(e)), "max": float(max(e)), "within": int(sum(x <= tol for x in e)), "tol": tol}
    print(f"  {label:58s} n={out['n']:2d}  mean {out['mean']:6.2f}{unit}  worst {out['max']:6.2f}{unit}  within {tol:g}: {out['within']}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("api")
    ap.add_argument("strap")
    ap.add_argument("--noop-dir", default=os.environ.get("NOOP_DIR", os.path.join(HERE, "..", "..", "noop-upstream")))
    ap.add_argument("--hr-cache", help="JSON file to keep the per-second HR between runs (local, never commit)")
    ap.add_argument("--per-night", action="store_true", help="also print dated rows (local use only)")
    ap.add_argument("--json", help="write the aggregates here")
    a = ap.parse_args()

    api = load_api(a.api)
    if a.hr_cache and os.path.exists(a.hr_cache):
        hr = {int(k): v for k, v in json.load(open(a.hr_cache)).items()}
    else:
        from strain_model import hr_by_second
        hr = hr_by_second(a.strap)
        if a.hr_cache:
            json.dump(hr, open(a.hr_cache, "w"))
    secs = sorted(hr)
    by_minute = defaultdict(list)
    for t in secs:
        by_minute[t // 60].append(hr[t])
    minute_hr = {m: round(sum(v) / len(v), 2) for m, v in by_minute.items()}
    commit = subprocess.run(["git", "-C", a.noop_dir, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

    allsleeps = sorted(api["sleeps"], key=lambda s: s["start"])
    mains = [s for s in allsleeps if not s["nap"]]
    rec = {r["sleep_id"]: r["score"] for r in api["recoveries"]}
    cycles = sorted(api["cycles"], key=lambda c: c["start"])
    max_hr = api["body_measurement"]["max_heart_rate"]
    nap_after: dict = {}
    for s in allsleeps:
        if s["nap"]:
            before = [m for m in mains if m["start"] < s["start"]]
            if before:
                nap_after[before[-1]["id"]] = nap_after.get(before[-1]["id"], 0) + asleep(s)

    # ---- NOOP side
    nights = []
    for s in mains:
        sc, r, t = s["score"], rec.get(s["id"]) or {}, s["score"]["stage_summary"]
        nights.append({"hrv": r.get("hrv_rmssd_milli"), "rhr": r.get("resting_heart_rate"), "resp": sc.get("respiratory_rate"),
                       "sleepPerf": sc["sleep_performance_percentage"], "skinTemp": r.get("skin_temp_celsius"),
                       "tst": asleep(s) / 1000, "inBed": t["total_in_bed_time_milli"] / 1000,
                       "efficiency": sc["sleep_efficiency_percentage"] / 100,
                       "restorative": (t["total_slow_wave_sleep_time_milli"] + t["total_rem_sleep_time_milli"]) / 1000,
                       "deep": t["total_slow_wave_sleep_time_milli"] / 1000, "consistency": sc["sleep_consistency_percentage"] / 100,
                       "creditedSleepMin": (asleep(s) + nap_after.get(s["id"], 0)) / 60000})
    rhr_at = {s["start"][:16]: rec[s["id"]]["resting_heart_rate"] for s in mains if s["id"] in rec}
    peak = max(hr.values())
    cyc_in, cyc_rows = [], []
    for c in cycles:
        if not c.get("end"):
            continue
        b0, b1 = parse(c["start"]).timestamp(), parse(c["end"]).timestamp()
        i, j = bisect.bisect_left(secs, b0), bisect.bisect_left(secs, b1)
        if j - i < 0.8 * (b1 - b0):
            continue
        sports = {w["sport_name"] for w in api["workouts"] if c["start"] <= w["start"] < c["end"]}
        cyc_in.append({"hr": [[t, hr[t]] for t in secs[i:j]], "restingHR": rhr_at.get(c["start"][:16]), "maxHR": peak})
        cyc_rows.append({"start": c["start"], "strain": c["score"]["strain"], "muscular": bool(sports & MUSCULAR),
                         "minutes": [minute_hr[m] for m in range(int(b0) // 60, int(b1) // 60) if m in minute_hr]})
    wk_in, wk_rows = [], []
    for w in sorted(api["workouts"], key=lambda w: w["start"]):
        b0, b1 = int(parse(w["start"]).timestamp()), int(parse(w["end"]).timestamp())
        sec = [t for t in range(b0, b1) if t in hr]
        if len(sec) < 0.8 * (b1 - b0):
            continue
        wk_in.append({"hr": [[t, hr[t]] for t in sec], "maxHR": max_hr})
        wk_rows.append({"start": w["start"], "hrs": [hr[t] for t in sec], "duration": b1 - b0,
                        "whoop": [w["score"]["zone_durations"][k] / 1000 for k in ZONE_KEYS],
                        "unseen": parse(w["start"]) >= parse(ZR1_FROZEN_UTC)})
    out = json.loads(subprocess.run([BINARY], input=json.dumps({"nights": nights, "cycles": cyc_in, "workouts": wk_in}),
                                    text=True, capture_output=True, check=True).stdout)

    # ---- our side: sleep need chained from our own previous need
    need, prev = [], None
    for s in mains:
        on = parse(s["start"])
        c = [c for c in cycles if c.get("end") and abs(parse(c["end"]).timestamp() - on.timestamp()) < 120]
        sn = strain_need_ms(c[0]["score"]["strain"]) if c else s["score"]["sleep_needed"]["need_from_recent_strain_milli"]
        debt = debt_ms(prev[0], asleep(prev[1]), prev[1]["score"]["stage_summary"]["total_rem_sleep_time_milli"]) if prev else 0
        n = baseline_ms(on) + debt + sn - (nap_after.get(prev[1]["id"], 0) if prev else 0)
        need.append(n)
        prev = (n, s)

    whoop_need = [sum(s["score"]["sleep_needed"].values()) for s in mains]
    whoop_sp = [s["score"]["sleep_performance_percentage"] for s in mains]
    cons = [s["score"]["sleep_consistency_percentage"] for s in mains]
    scored = range(WARMUP, len(mains))
    res = {"noop_commit": commit, "nights": len(mains)}
    print(f"NOOP {commit}; {len(mains)} main sleeps, {len(cyc_rows)} cycles and {len(wk_rows)} workouts with strap HR\n")

    print("Sleep need (minutes):")
    res["need_noop"] = summary("NOOP: personalized need + 55 % debt ledger",
                               [(out["needMin"][i], whoop_need[i] / 60000) for i in scored if out["needMin"][i] is not None], 15, " min")
    res["need_ours"] = summary("ours: baseline + debt + recent-strain need - nap",
                               [(need[i] / 60000, whoop_need[i] / 60000) for i in scored], 15, " min")

    def sp_fit(x):
        def f(p, rows):
            return [p[0] - p[1] * x[i][0] ** -p[2] + p[3] * (x[i][1] - 80) - whoop_sp[i] for i in rows]
        return f

    def sp_loo(x):
        f = sp_fit(x)
        fit = lambda rows: least_squares(lambda p: f(p, rows), [94.8, 4.68, 2.88, 0.236]).x
        return lambda i_s: [(f(fit([j for j in range(len(x)) if j != i]), [i])[0] + whoop_sp[i], whoop_sp[i]) for i in i_s]

    own = [(asleep(s) / need[i], cons[i] or 80) for i, s in enumerate(mains)]
    whoops = [(asleep(s) / whoop_need[i], cons[i] or 80) for i, s in enumerate(mains)]
    print("Sleep score (points):")
    res["sp_noop"] = summary("NOOP Rest, its own need", [(out["rest"][i], whoop_sp[i]) for i in scored if out["rest"][i] is not None], 2)
    res["sp_ours"] = summary("ours SP-C2 on our own need, leave-one-out", sp_loo(own)(scored), 2)
    res["sp_ours_whoop_need"] = summary("ours SP-C2 on WHOOP's need, leave-one-out, every night", sp_loo(whoops)(range(len(mains))), 2)

    # recovery: REC-RHR without stress input, sleep score from our own need (frozen SP-C2)
    rows = [(s, rec[s["id"]]) for s in mains if s["id"] in rec]
    own_sp = {s["id"]: sleep_performance(asleep(s), need[i], cons[i]) for i, s in enumerate(mains)}
    y = np.array([r["recovery_score"] for _, r in rows])

    def rec_pred(p, free):
        a_, b_, d_, r0 = p[:4]
        m0, w = (abs(p[4]), abs(p[5])) if free else (HRV_PRIOR, HRV_PRIOR_WEIGHT)
        out_ = []
        for i, (s, r) in enumerate(rows):
            h = [x["hrv_rmssd_milli"] for _, x in rows[:i]]
            sps = [own_sp[x["id"]] for x, _ in rows[:i]]
            base = math.exp((w * math.log(m0) + sum(map(math.log, h))) / (w + len(h)))
            ref = sum(sps) / len(sps) if sps else own_sp[s["id"]]
            z = a_ * math.log(r["hrv_rmssd_milli"] / base) + b_ * (own_sp[s["id"]] - ref) / 10 - d_ * (r["resting_heart_rate"] - r0)
            out_.append(min(100, max(0, 100 * math.exp(min(z, 5)))))
        return np.array(out_)

    def rec_loo(free):
        x0 = [1.07, 0.08, 0.05, 59] + ([103.0, 5.0] if free else [])
        fit = lambda keep: least_squares(lambda p: (rec_pred(p, free) - y)[keep], x0, max_nfev=20000).x
        return [(rec_pred(fit([j for j in range(len(rows)) if j != i]), free)[i], y[i]) for i in range(FIRST_RECOVERY, len(rows))]

    whoop_rec = {s["id"]: r["recovery_score"] for s, r in rows}
    idx_rec = [mains.index(s) for s, _ in rows][FIRST_RECOVERY:]
    print("Recovery (points), nights after WHOOP's calibration:")
    res["rec_noop_own_rest"] = summary("NOOP Charge with its own Rest (app path)",
                                       [(out["chargeOwnRest"][i], whoop_rec[mains[i]["id"]]) for i in idx_rec if out["chargeOwnRest"][i] is not None], 3)
    res["rec_noop_whoop_sp"] = summary("NOOP Charge with WHOOP's sleep performance",
                                       [(out["charge"][i], whoop_rec[mains[i]["id"]]) for i in idx_rec if out["charge"][i] is not None], 3)
    res["rec_ours"] = summary("ours REC-RHR, leave-one-out, 4 weights refitted per fold", rec_loo(False), 3)
    res["rec_ours_strict"] = summary("ours REC-RHR, leave-one-out, all 6 constants refitted", rec_loo(True), 3)

    # day strain: DS-E nested leave-one-out (threshold chosen inside each fold)
    def ds(p, mins, t):
        return p[0] * max(sum(math.exp(p[2] * (h - 100)) for h in mins if h >= t), 1e-9) ** p[1]

    def ds_loo(sel):
        sel = list(sel)
        res_ = []
        for i in sel:
            train = [j for j in sel if j != i]
            best = None
            for t in range(88, 101):
                f = least_squares(lambda p: [ds(p, cyc_rows[j]["minutes"], t) - cyc_rows[j]["strain"] for j in train],
                                  [0.78, 0.41, 0.065], max_nfev=5000)
                if best is None or (f.fun ** 2).sum() < best[0]:
                    best = ((f.fun ** 2).sum(), f.x, t)
            res_.append((ds(best[1], cyc_rows[i]["minutes"], best[2]), cyc_rows[i]["strain"]))
        return res_

    effort = [(e * 21 / 100, c["strain"]) for c, e in zip(cyc_rows, out["effort"]) if e is not None]
    cardio = [i for i, c in enumerate(cyc_rows) if not c["muscular"]]
    print("Day strain (WHOOP 0-21; NOOP's Effort x 21/100):")
    res["strain_noop"] = summary("NOOP Effort, every cycle", effort, 0.3)
    res["strain_ours"] = summary("ours DS-E, nested leave-one-out, every cycle", ds_loo(range(len(cyc_rows))), 0.3)
    res["strain_noop_cardio"] = summary("NOOP Effort, cycles without skiing or weightlifting", [effort[i] for i in cardio], 0.3)
    res["strain_ours_cardio"] = summary("ours DS-E, nested leave-one-out, same cycles", ds_loo(cardio), 0.3)

    print(f"Workout zones (% of the workout in a different zone than WHOOP; maximum HR {max_hr} for both):")
    for tag, unseen in (("workouts after ZR-1 was frozen", True), ("workouts ZR-1 was chosen on", False)):
        sel = [(w, z) for w, z in zip(wk_rows, out["zones"]) if w["unseen"] == unseen]
        for name, get in (("NOOP %HRmax 50/60/70/80/90", lambda w, z: z), ("ours ZR-1 %HRR 40/60/70/80/90", lambda w, z: zone_seconds(w["hrs"], ZR1_REST, max_hr))):
            wrong = [sum(abs(p - q) for p, q in zip(get(w, z), w["whoop"])) / 2 / w["duration"] * 100 for w, z in sel]
            key = f"zones_{'noop' if name.startswith('NOOP') else 'ours'}_{'unseen' if unseen else 'chosen_on'}"
            res[key] = {"n": len(sel), "mean": float(st.mean(wrong)), "max": float(max(wrong))}
            print(f"  {tag:32s} {name:30s} n={len(sel)}  mean {st.mean(wrong):5.1f} %  worst {max(wrong):5.1f} %")

    if a.per_night:
        print("\nPer night (local use only): start, WHOOP need min, NOOP need, ours, WHOOP SP, NOOP Rest, SP-C2 own need")
        for i, s in enumerate(mains):
            print(f"  {s['start'][:16]}  {whoop_need[i] / 60000:6.1f} {out['needMin'][i] or float('nan'):6.1f} {need[i] / 60000:6.1f}"
                  f"  {whoop_sp[i]:5.1f} {out['rest'][i] or float('nan'):5.1f} {sleep_performance(asleep(s), need[i], cons[i]):5.1f}")
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
