"""Check WHOOP's sleep-need rules and the formulas in use against an API snapshot from re/whoop_api_fetch.py.

  python re/api_checks.py <snapshot folder>

Times in the API are in milliseconds, so a rule that fits here has little room to be chance. The formulas come from
re/score_formulas.py; re/SCORE_MODELS.md records how they were found and what was ruled out.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

MS_PER_MIN = 60000
DEBT_CAP_MS = 7668000  # constant: hit on two different baselines
DEBT_FACTORS = (1 / 2, 9 / 14)  # which one applies is open (re/SCORE_MODELS.md)


def asleep_ms(stage: dict) -> int:
    return stage["total_light_sleep_time_milli"] + stage["total_slow_wave_sleep_time_milli"] + stage["total_rem_sleep_time_milli"]


def need_ms(needed: dict) -> int:
    return (needed["baseline_milli"] + needed["need_from_sleep_debt_milli"] + needed["need_from_recent_strain_milli"]
            + needed["need_from_recent_nap_milli"])


def debt_after(need: int, asleep: int, factor: float = 1 / 2) -> int:
    """A share of the last scored main sleep's shortfall, in whole milliseconds, up to the cap; it replaces earlier debt."""
    return min(DEBT_CAP_MS, int(factor * max(0, need - asleep)))


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
        needed = s["score"]["sleep_needed"]
        if prev_main is not None:
            options = [debt_after(need_ms(prev_main["score"]["sleep_needed"]), asleep_ms(prev_main["score"]["stage_summary"]), f)
                       for f in DEBT_FACTORS]
            got = needed["need_from_sleep_debt_milli"]
            debt_cases += 1
            if any(abs(got - o) <= 1 for o in options):  # halves round either way
                debt_hits += 1
            else:
                misses.append(f"debt expected {' or '.join(map(str, options))} got {got}")
        if prev_nap is not None:
            nap_cases += 1
            nap_hits += -needed["need_from_recent_nap_milli"] == asleep_ms(prev_nap["score"]["stage_summary"])
        if s["nap"]:
            prev_nap = s
        else:
            prev_main, prev_nap = s, None
    lines.append(f"debt = 1/2 or 9/14 of the last scored main sleep's shortfall, capped: {debt_hits} of {debt_cases} within 1 ms")
    lines.append(f"nap credit = the nap's asleep time: {nap_hits} of {nap_cases} exact")
    lines.extend(misses)
    return lines


def check_formulas(sleeps: list[dict], cycles: list[dict]) -> list[str]:
    """The formulas in use (re/score_formulas.py) on every scored main sleep, against their practical tolerances."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from score_formulas import baseline_ms, sleep_performance, strain_need_ms
    when = lambda t: dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    base, strain, perf = [], [], []
    mains = [s for s in sleeps if not s["nap"] and s.get("score")]
    for i, s in enumerate(mains):
        sc, needed = s["score"], s["score"]["sleep_needed"]
        if i:  # the first night precedes the line: WHOOP's baseline settled after it
            base.append(abs(baseline_ms(when(s["start"])) - needed["baseline_milli"]))
        before = [c for c in cycles if c.get("end") and c.get("score")
                  and abs((when(c["end"]) - when(s["start"])).total_seconds()) < 120]
        if before and needed["need_from_recent_strain_milli"] > 0:
            strain.append(abs(strain_need_ms(before[0]["score"]["strain"]) - needed["need_from_recent_strain_milli"]))
        perf.append(abs(sleep_performance(asleep_ms(sc["stage_summary"]), need_ms(needed), sc["sleep_consistency_percentage"])
                        - sc["sleep_performance_percentage"]))

    def row(name, errs, tol, unit):
        return f"{name}: {sum(e <= tol for e in errs)} of {len(errs)} within {tol:g}{unit}, largest {max(errs, default=0):.1f}{unit}"
    return [row("baseline line", base, 5, " ms"), row("recent-strain need (SN-PE)", [e / 1000 for e in strain], 60, " s"),
            row("sleep performance (SP-C2)", perf, 2, " points")]


def main() -> None:
    folder = sys.argv[1]
    load = lambda n: json.load(open(os.path.join(folder, f"{n}.json")))
    sleeps = sorted(load("sleeps"), key=lambda r: r["start"])
    for line in check_sleep_chain(sleeps):
        print(line)
    print("\nformulas in use, on every scored night (the fit includes these nights; see re/noop_compare.py for out-of-sample):")
    for line in check_formulas(sleeps, load("cycles")):
        print(f"  {line}")
    last = [s for s in sleeps if not s["nap"] and s.get("score")][-1]["score"]
    need, asleep = need_ms(last["sleep_needed"]), asleep_ms(last["stage_summary"])
    print("\nnext night's debt: " + " or ".join(f"{debt_after(need, asleep, f)} ms" for f in DEBT_FACTORS))


if __name__ == "__main__":
    main()
