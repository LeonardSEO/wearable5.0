"""Approximate WHOOP score formulas that meet the practical tolerances out-of-sample (SCORE_MODELS.md, round 6).

Sleep performance within 2 points, day strain within 0.3 on cardio-only days, sleep-need parts within 60 s. Recovery is a
lead only. Self-test: python3 re/score_formulas.py <math_round6 folder> (local data, never in git).
"""
import csv
import datetime as dt
import math
import sys

DEBT_CAP_MS = 7668000
REM_SWITCH_MS = 6_800_000  # frozen choice between 1/2 and 9/14; falsified on low-REM nights that took 9/14, driver open


def baseline_ms(sleep_start_utc: dt.datetime) -> float:
    """Within about 1 ms: falls 284.3 ms per UTC calendar day of the sleep start."""
    return 27834333.7 - 284.3152 * (sleep_start_utc.date() - dt.date(2026, 11, 2)).days


def debt_ms(need: int, asleep: int, rem: int) -> int:
    """Debt charged to the next sleep from the last scored main sleep: 1/2 or 9/14 of its shortfall, capped. The shortfall and
    cap are exact; which factor applies is open, and REM_SWITCH_MS is the frozen guess. A nap or a day without a sleep record
    leaves the debt unchanged."""
    f = 9 / 14 if rem > REM_SWITCH_MS else 1 / 2
    return max(0, min(DEBT_CAP_MS, math.floor(f * (need - asleep))))


def strain_need_ms(day_strain: float) -> float:
    return 25995.162137 * day_strain ** 0.728090984 * math.exp(0.167421361 * day_strain)


def sleep_performance(asleep: int, need: int, consistency: float, high_stress_min: float = 0) -> float:
    """consistency 0 (WHOOP's value before it has history) counts as 80. The stress term rests on one night."""
    c = consistency or 80
    return 94.81929 - 4.67893 * (asleep / need) ** -2.88390 + 0.23588 * (c - 80) - 0.0862 * high_stress_min


def day_strain(minute_hr: list[float]) -> float:
    """Per-minute mean HR on the strap's own scale (about WHOOP + 3 bpm). Cardio load only: days with muscular workouts read low."""
    load = sum(math.exp(0.065 * (h - 100)) for h in minute_hr if h >= 94)
    return 0.78115 * load ** 0.40855


def zone_seconds(second_hr: list[int], rest: int = 57, hr_max: int = 189) -> list[int]:
    """Seconds in WHOOP zones 0-5 by heart-rate reserve, edges 40/60/70/80/90 %."""
    z = [0] * 6
    for h in second_hr:
        z[sum((h - rest) / (hr_max - rest) * 100 >= e for e in (40, 60, 70, 80, 90))] += 1
    return z


def recovery_lead(history: list[tuple[float, float]], hrv: float, sleep_perf: float, rhr: float,
                  high_stress_min: float = 0) -> float:
    """Lead only (REC-RHR, refit 17 Nov): HRV against a baseline that starts near a population value and shrinks to the
    own mean, times sleep, stress and resting-HR terms. history = (hrv, sleep_performance) of every earlier night,
    calibrating nights included. rhr is on WHOOP's scale: the strap's resting HR reads about 4.6 bpm lower, so add 4.6.
    The RHR weight was learned from the four high-RHR nights only."""
    n = len(history)
    base = math.exp((5.0265 * math.log(103.2555) + sum(math.log(h) for h, _ in history)) / (5.0265 + n))
    s_ref = sum(s for _, s in history) / n if n else sleep_perf
    z = (1.066 * math.log(hrv / base) + 0.07735 * (sleep_perf - s_ref) / 10 - 0.08547 * high_stress_min / 60
         - 0.05156 * (rhr - 59.08321))
    return min(100.0, max(0.0, 100 * math.exp(z)))


def _self_test(folder: str) -> None:
    sleeps = list(csv.DictReader(open(f"{folder}/sleeps.csv")))
    for r in sleeps[1:-1]:  # skip the profile-change row and the one high-stress night
        v = {k: float(r[k]) for k in ("baseline", "debt", "strain_need", "nap_need", "light", "deep", "rem", "consistency", "performance")}
        need = v["baseline"] + v["debt"] + v["strain_need"] + v["nap_need"]
        asleep = v["light"] + v["deep"] + v["rem"]
        assert abs(sleep_performance(asleep, need, v["consistency"]) - v["performance"]) <= 2, r["start_utc"]
        assert abs(baseline_ms(dt.datetime.fromisoformat(r["start_utc"])) - v["baseline"]) <= 1.5, r["start_utc"]
    hr = {r["minute_utc"]: float(r["mean_hr"]) for r in csv.DictReader(open(f"{folder}/hr_per_minute_utc.csv"))}
    for c in csv.DictReader(open(f"{folder}/cycles.csv")):
        if c["open"] == "1" or c["start_utc"][:10] in ("2026-11-01", "2026-11-05"):  # open cycle; the two cycles with muscular workouts
            continue
        t, end, mins = dt.datetime.fromisoformat(c["start_utc"]).replace(second=0), dt.datetime.fromisoformat(c["end_utc"]), []
        while t < end:
            if (h := hr.get(t.strftime("%Y-%m-%dT%H:%M"))) is not None:
                mins.append(h)
            t += dt.timedelta(minutes=1)
        assert abs(day_strain(mins) - float(c["strain"])) <= 0.3, c["start_utc"]
    assert debt_ms(30_000_000, 20_000_000, 5_000_000) == 5_000_000 and debt_ms(30_000_000, 20_000_000, 7_000_000) == 6_428_571
    assert debt_ms(40_000_000, 20_000_000, 0) == DEBT_CAP_MS and debt_ms(20_000_000, 25_000_000, 0) == 0
    assert recovery_lead([], 103.2555, 80, 59.08321) == 100.0
    print("all formulas within tolerance")


if __name__ == "__main__":
    _self_test(sys.argv[1])
