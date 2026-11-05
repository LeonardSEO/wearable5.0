"""Check the rules behind WHOOP's sleep need, sleep debt and exports against an API snapshot from re/whoop_api_fetch.py.

  python re/api_checks.py <snapshot folder> [app stress csv]

Times in the API are in milliseconds, so a rule that fits here has little room to be chance.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys

MS_PER_MIN = 60000
KJ_PER_KCAL = 4.184


def asleep_ms(stage: dict) -> int:
    return stage["total_light_sleep_time_milli"] + stage["total_slow_wave_sleep_time_milli"] + stage["total_rem_sleep_time_milli"]


def need_ms(needed: dict) -> int:
    return (needed["baseline_milli"] + needed["need_from_sleep_debt_milli"] + needed["need_from_recent_strain_milli"]
            + needed["need_from_recent_nap_milli"])


def debt_after(need: int, asleep: int) -> int:
    """Half the shortfall of a main sleep, in whole milliseconds. Carried debt is only tested once it stays above zero."""
    return max(0, need - asleep) // 2


def check_sleep_chain(sleeps: list[dict]) -> list[str]:
    """Each rule, with the number of cases that held. `sleeps` is in time order and must be scored."""
    lines = []
    scored = [s for s in sleeps if s.get("score")]
    stage_ok = sum(asleep_ms(s["score"]["stage_summary"]) + s["score"]["stage_summary"]["total_awake_time_milli"]
                   == s["score"]["stage_summary"]["total_in_bed_time_milli"] for s in scored)
    lines.append(f"in bed = asleep + awake: {stage_ok} of {len(scored)} exact")
    prev_main, prev_nap, debt_hits, debt_cases, nap_hits, nap_cases = None, None, 0, 0, 0, 0
    misses = []
    for s in scored:
        sc = s["score"]
        needed = sc["sleep_needed"]
        if prev_main is not None:
            expect = debt_after(need_ms(prev_main["score"]["sleep_needed"]), asleep_ms(prev_main["score"]["stage_summary"]))
            debt_cases += 1
            debt_hits += needed["need_from_sleep_debt_milli"] == expect
            if needed["need_from_sleep_debt_milli"] != expect:
                misses.append(f"debt expected {expect} got {needed['need_from_sleep_debt_milli']}")
        if prev_nap is not None:
            nap_cases += 1
            nap_hits += -needed["need_from_recent_nap_milli"] == asleep_ms(prev_nap["score"]["stage_summary"])
        if s["nap"]:
            prev_nap = s
        else:
            prev_main, prev_nap = s, None
    lines.append(f"debt = half the shortfall of the last main sleep: {debt_hits} of {debt_cases} exact")
    lines.append(f"nap credit = the nap's asleep time: {nap_hits} of {nap_cases} exact")
    lines.extend(misses)
    return lines


def sp_m(sufficiency: float, efficiency: float, consistency: float | None, stress_share: float) -> float:
    """Frozen candidate SP-M: sufficiency, efficiency, consistency and calm sleep, with consistency dropped when missing."""
    has_consistency = bool(consistency)
    total = 0.4 * sufficiency + 0.2 * efficiency + 0.2 * (100 - stress_share) + (0.2 * consistency if has_consistency else 0)
    return total / (0.8 + (0.2 if has_consistency else 0))


def stress_rows(sleeps: list[dict], stress_csv: str) -> list[dict]:
    """SP-M on separate main sleeps with their own stress reading. Nap cycles have one combined reading, so they are out of scope here."""
    rows = []
    by_cycle = {}
    for s in sleeps:
        by_cycle.setdefault(s["cycle_id"], []).append(s)
    with open(stress_csv, encoding="utf-8") as f:
        readings = {r["sleep_cycle_start"]: r for r in csv.DictReader(f)}
    for group in by_cycle.values():
        if len(group) != 1 or group[0]["nap"]:
            continue
        s = group[0]
        reading = readings.get(local_start(s))
        if not reading:
            continue
        low, medium, high = (float(reading[k]) for k in ("low_min", "medium_min", "high_min"))
        share = 100 * (medium + high) / (low + medium + high)
        score = s["score"]
        predicted = sp_m(100 * min(1, asleep_ms(score["stage_summary"]) / need_ms(score["sleep_needed"])), score["sleep_efficiency_percentage"],
                         score["sleep_consistency_percentage"], share)
        rows.append({"start": local_start(s), "predicted": predicted, "actual": score["sleep_performance_percentage"]})
    return rows


def local_start(s: dict) -> str:
    moment = dt.datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
    sign = -1 if s["timezone_offset"].startswith("-") else 1
    hours, minutes = s["timezone_offset"].lstrip("+-").split(":")
    return (moment + sign * dt.timedelta(hours=int(hours), minutes=int(minutes))).strftime("%Y-%m-%d %H:%M:%S")


def frozen_on_api(sleeps: list[dict], recoveries: list[dict]) -> list[dict]:
    """Recheck the frozen candidates on the API's exact inputs. These are the same nights, so this is not a test on new data."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from score_predictions import RECOVERY_MODELS, SLEEP_MODELS
    rows = []
    by_id = {s["id"]: s for s in sleeps}
    for s in sleeps:
        inputs = {"asleep": asleep_ms(s["score"]["stage_summary"]) / MS_PER_MIN, "need": need_ms(s["score"]["sleep_needed"]) / MS_PER_MIN}
        for name, f in SLEEP_MODELS.items():
            rows.append({"model": name, "predicted": f(inputs), "actual": s["score"]["sleep_performance_percentage"]})
    for r in recoveries:
        inputs = {"asleep": asleep_ms(by_id[r["sleep_id"]]["score"]["stage_summary"]) / MS_PER_MIN, "hrv": r["score"]["hrv_rmssd_milli"]}
        for name, f in RECOVERY_MODELS.items():
            rows.append({"model": name, "predicted": f(inputs), "actual": r["score"]["recovery_score"]})
    return rows


def main() -> None:
    folder = sys.argv[1]
    load = lambda n: json.load(open(os.path.join(folder, f"{n}.json")))
    sleeps = sorted(load("sleeps"), key=lambda r: r["start"])
    for line in check_sleep_chain(sleeps):
        print(line)
    rows = frozen_on_api(sleeps, load("recoveries"))
    print("\nfrozen candidates on the API's exact inputs (same nights, not a new test):")
    for model in sorted({r["model"] for r in rows}):
        mine = [r for r in rows if r["model"] == model]
        hits = sum(abs(r["predicted"] - r["actual"]) < 0.5 for r in mine)
        print(f"  {model:8} {hits} of {len(mine)} within rounding; {[round(r['predicted'], 2) for r in mine]}")
    if len(sys.argv) > 2:
        print("\nSP-M with app stress hours:")
        for r in stress_rows(sleeps, sys.argv[2]):
            print(f"  predicted {r['predicted']:.2f}  WHOOP {r['actual']:.0f}  {'in rounding' if abs(r['predicted'] - r['actual']) < 0.5 else 'MISS'}")
    print("\nnext-debt prediction after the newest main sleep:")
    last = [s for s in sleeps if not s["nap"] and s.get("score")][-1]["score"]
    expect = debt_after(need_ms(last["sleep_needed"]), asleep_ms(last["stage_summary"]))
    print(f"  {expect} ms = {expect / MS_PER_MIN:.2f} min")
    print("\nefficiency against asleep / in bed:")
    for s in sleeps:
        stage = s["score"]["stage_summary"]
        ratio = 100 * asleep_ms(stage) / stage["total_in_bed_time_milli"]
        print(f"  reported {s['score']['sleep_efficiency_percentage']:.4f}  ratio {ratio:.4f}  difference {s['score']['sleep_efficiency_percentage'] - ratio:+.4f}")


if __name__ == "__main__":
    main()
