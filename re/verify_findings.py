"""Recompute every claim taken from the WHOOP export and official API, and fail loudly if one no longer holds.

  python re/verify_findings.py <export zip or folder> <API snapshot folder> [frames folder]

Prints counts only, so the output is safe to share. Exit code 1 means a claim failed. Run it on every new snapshot: a rule that
held on the data that suggested it has to keep holding on later data.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_checks import MS_PER_MIN, asleep_ms, debt_after, need_ms  # noqa: E402

KJ_PER_KCAL = 4.184
RESEND_START_UTC = "2026-11-05T13:48:04+00:00"  # first captured re-send of already scored pages, FINDINGS §17
Z5_EDGE = 0.9
REJECTED_MAX_HR = 214
ZONE_REST_HR = 58  # the resting HR that fits best, re/hrr_zones.py
ZONE_MIN_SHARE = 0.99
ZONE_RULE_FROZEN_UTC = "2026-11-05T18:00:00+00:00"  # workouts from here on did not shape the rule


def read_export(path: str, name: str) -> list[dict]:
    if os.path.isdir(path):
        text = open(os.path.join(path, name), encoding="utf-8-sig").read()
    else:
        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if os.path.basename(n).lower() == name)
            text = z.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def local_time(utc: str, offset: str) -> str:
    moment = dt.datetime.fromisoformat(utc.replace("Z", "+00:00"))
    sign = -1 if offset.startswith("-") else 1
    hours, minutes = offset.lstrip("+-").split(":")
    return (moment + sign * dt.timedelta(hours=int(hours), minutes=int(minutes))).strftime("%Y-%m-%d %H:%M:%S")


def utc(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def claim(results: list, name: str, hits: int, total: int, need_all: bool = True) -> None:
    results.append({"claim": name, "hits": hits, "total": total, "ok": total > 0 and (hits == total or not need_all)})


def verify(export_sleeps: list[dict], export_cycles: list[dict], sleeps: list[dict], cycles: list[dict], recoveries: list[dict],
           workouts: list[dict], resend_start: str = RESEND_START_UTC) -> list[dict]:
    results: list[dict] = []
    by_onset = {r["Sleep onset"]: r for r in export_sleeps}
    pairs = [(s, by_onset[local_time(s["start"], s["timezone_offset"])]) for s in sleeps
             if local_time(s["start"], s["timezone_offset"]) in by_onset]
    claim(results, "every API sleep matches an export sleep by onset", len(pairs), len(sleeps))
    floor_min = lambda ms: ms // MS_PER_MIN
    claim(results, "export need = floor(sum of the four API components)",
          sum(float(r["Sleep need (min)"]) == floor_min(need_ms(s["score"]["sleep_needed"])) for s, r in pairs), len(pairs))
    claim(results, "export asleep = floor(light + deep + REM)",
          sum(float(r["Asleep duration (min)"]) == floor_min(asleep_ms(s["score"]["stage_summary"])) for s, r in pairs), len(pairs))
    claim(results, "export in bed = floor(API in bed)",
          sum(float(r["In bed duration (min)"]) == floor_min(s["score"]["stage_summary"]["total_in_bed_time_milli"]) for s, r in pairs), len(pairs))
    claim(results, "API in bed = asleep + awake",
          sum(asleep_ms(s["score"]["stage_summary"]) + s["score"]["stage_summary"]["total_awake_time_milli"]
              == s["score"]["stage_summary"]["total_in_bed_time_milli"] for s in sleeps), len(sleeps))

    ordered = sorted(sleeps, key=lambda s: s["start"])
    main, nap, debt_hits, debt_total, nap_hits, nap_total = None, None, 0, 0, 0, 0
    for s in ordered:
        needed = s["score"]["sleep_needed"]
        if main is not None:
            debt_total += 1
            debt_hits += needed["need_from_sleep_debt_milli"] == debt_after(need_ms(main["score"]["sleep_needed"]), asleep_ms(main["score"]["stage_summary"]))
        if nap is not None:
            nap_total += 1
            nap_hits += -needed["need_from_recent_nap_milli"] == asleep_ms(nap["score"]["stage_summary"])
        if s["nap"]:
            nap = s
        else:
            main, nap = s, None
    claim(results, "debt = half the last main sleep's shortfall; naps hold it", debt_hits, debt_total)
    claim(results, "nap credit = the nap's asleep time", nap_hits, nap_total)

    claim(results, "recovery and sleep performance are whole numbers in the API",
          sum(float(r["score"]["recovery_score"]).is_integer() for r in recoveries)
          + sum(float(s["score"]["sleep_performance_percentage"]).is_integer() for s in sleeps), len(recoveries) + len(sleeps))
    claim(results, "strain has decimals in the API",
          sum(not float(c["score"]["strain"]).is_integer() for c in cycles if c.get("score")), sum(1 for c in cycles if c.get("score")))
    finished = [c for c in cycles if c.get("end") and c.get("score")]
    by_start = {r["Cycle start time"]: r for r in export_cycles}
    matched = [(c, by_start[local_time(c["start"], c["timezone_offset"])]) for c in finished
               if local_time(c["start"], c["timezone_offset"]) in by_start]
    claim(results, "export strain = API strain rounded to 0.1",
          sum(math.isclose(round(c["score"]["strain"], 1), float(r["Day Strain"])) for c, r in matched), len(matched))
    claim(results, "export calories = API kilojoules / 4.184, rounded",
          sum(round(c["score"]["kilojoule"] / KJ_PER_KCAL) == round(float(r["Energy burned (cal)"])) for c, r in matched), len(matched))
    resend = utc(resend_start)
    earlier = [c for c in finished if utc(c["start"]) < resend]
    claim(results, "cycles from before the re-send were not updated after it",
          sum(utc(c["updated_at"]) < resend for c in earlier), len(earlier))
    claim(results, "at least one cycle was first scored days after it began",
          sum((utc(c["created_at"]) - utc(c["start"])).total_seconds() > 3 * 86400 for c in cycles), len(cycles), need_all=False)
    in_z5 = [w for w in workouts if w.get("score") and w["score"]["zone_durations"]["zone_five_milli"] > 0]
    claim(results, f"zone 5 was reached below {Z5_EDGE:.0%} of the rejected maximum HR {REJECTED_MAX_HR}",
          sum(w["score"]["max_heart_rate"] < Z5_EDGE * REJECTED_MAX_HR for w in in_z5), len(in_z5))
    return results


def zone_claims(results: list, workouts: list[dict], hr: dict[int, int], max_hr: int) -> None:
    """The frozen zone rule ZR-1 on raw strap heart rate. Later workouts count as tests; rest and edges are not chosen again."""
    from hrr_zones import ZONE_KEYS, unix, zone_error
    shaped_total, shaped_right, new_ok, new_total = 0, 0, 0, 0
    for w in workouts:
        hrs = [hr[t] for t in range(unix(w["start"]), unix(w["end"])) if t in hr]
        if not hrs:
            continue
        wrong = zone_error(hrs, [w["score"]["zone_durations"][k] / 1000 for k in ZONE_KEYS], ZONE_REST_HR, max_hr) / 2
        share = 1 - wrong / len(hrs)
        is_new = utc(w["start"]) >= utc(ZONE_RULE_FROZEN_UTC)
        print(f"zones {w['sport_name']}: {share:.2%} of {len(hrs)} s in WHOOP's zone{' (new workout)' if is_new else ''}")
        if is_new:
            new_total += 1
            new_ok += share >= ZONE_MIN_SHARE
        else:
            shaped_total += len(hrs)
            shaped_right += int(len(hrs) - wrong)
    claim(results, "the workouts that chose the zone rule land in WHOOP's zones (at least 99 % together)", shaped_right, shaped_total, need_all=False)
    results[-1]["ok"] = shaped_total > 0 and shaped_right / shaped_total >= ZONE_MIN_SHARE
    if new_total:
        claim(results, "each new workout lands at least 99 % in WHOOP's zones under the frozen rule", new_ok, new_total)


def main() -> int:
    export, snapshot = sys.argv[1], sys.argv[2]
    load = lambda n: json.load(open(os.path.join(snapshot, f"{n}.json")))
    results = verify(read_export(export, "sleeps.csv"), read_export(export, "physiological_cycles.csv"), load("sleeps"), load("cycles"),
                     load("recoveries"), load("workouts"))
    if len(sys.argv) > 3:
        from strain_model import hr_by_second
        zone_claims(results, load("workouts"), hr_by_second(sys.argv[3]), load("body_measurement")["max_heart_rate"])
    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['hits']} of {r['total']}  {r['claim']}")
    failed = sum(not r["ok"] for r in results)
    print(f"\n{len(results) - failed} of {len(results)} claims hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
