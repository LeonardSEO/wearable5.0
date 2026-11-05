# Registered score models

Candidate formulas for WHOOP's scores, frozen on 2026-11-05 from one account's first cycles. They come from an outside
mathematical analysis and were re-run here. **They are candidates, not WHOOP's formulas.** Each one fits the data that shaped it,
so that fit proves nothing. `re/score_predictions.py` tests them on later cycles only.

Rules: keep coefficients frozen, and give any refit a new id. A miss can reject the coefficients without rejecting the family.

| Target | Id | Formula (Q = rounded) | Free parameters / points | Status |
|---|---|---|---|---:|
| Sleep performance | SP-Q | x = asleep/need; 94.6(1 - max(0, 1 - x/1.122)^2) | 2 / 4 | Fits within rounding |
| | SP-E | max(0, 95 - 440 e^(-5x)) | 3 / 4 | Fits within rounding |
| Sleep debt | SD-R | (77/155) max(0, need - asleep); naps hold debt | 1 / 3 | Exact |
| | SD-A | max(0, debt + (77/155)(need - asleep)); naps hold debt | 1 / 3 | Exact |
| | SD-CAP | min(77, max(0, debt + need - asleep)); naps hold debt | 1 / 2 | Exact, weakest |
| Day strain | DS-C | 0.0122 T / coverage | 1 / 2 | Fits within rounding |
| | DS-LOG | 103.0755 ln(1 + 0.000125876 T) | 2 / 2 | Undetermined |
| | DS-LIN | 0.27638 + 0.011945 T | 2 / 2 | Undetermined |
| | DS-POW | 0.01584 T^0.96245 | 2 / 2 | Undetermined |
| Recovery | R-SLEEP | 0.13 asleep - 11.17 | 2 / 3 | Fits within rounding |
| | R-HRV | 119.5 - 2.25 HRV | 2 / 3 | Fits; the negative sign is not a causal claim |

T is Edwards TRIMP with zones on 172 bpm. Sleep need has a component model only (baseline + strain + debt - nap); it cannot predict
a new night without its components.

## Ruled out

- **Sleep performance = plain asleep/need.** It gives 69, 62, 100 and 89 where WHOOP reports 81, 75, 95 and 90.
- **Day strain proportional to uncorrected TRIMP.** The two cycles need ranges of k that do not overlap.
- **One rising function of Edwards TRIMP for day and activity strain.** The workout's TRIMP is at most 115 and it scores 7.8; a
  day with TRIMP 379 scores 4.8. WHOOP may use another load measure or more inputs.
- **Recovery as a fixed function of HRV, resting HR and sleep performance only,** rising in HRV and sleep and falling in resting
  HR. From one night to the next all three worsened and Recovery rose.

## Measured here

- **Time in bed is truncated, not rounded.** It equals whole minutes of wake - onset, rounded down, on all 4 sleeps (`417.62` gives
  417).
- **The 214 lead is rejected.** WHOOP reports a maximum HR of 187. `re/workout_zones.py` had fitted 214 with a shifted window on one
  workout. Zones at % of 187 do not fit either, so the zone definition stays open.

## Settled by the official API

`re/api_checks.py`, in milliseconds. The rules below replace the candidates they settle: SN-C holds with a nap factor of exactly 1, and
SD-CAP's 53 and every other nap factor are unlikely, though the next debt is the first test on unseen data.

| Rule | Cases |
|---|---:|
| need = baseline + debt + recent strain + nap credit | 4 of 4 |
| debt = floor(0.5 x (need - asleep)) of the last main sleep; a nap holds it | 3 of 3 |
| nap credit = -(the nap's asleep time) | 1 of 1 |
| export minutes = floor of the milliseconds | all checked |

The frozen strain models fit to 0.1 only: the API's decimals show they are not exact, for example DS-C is off by 0.02-0.03. Recovery was
in WHOOP's calibration on all cycles here. Sleep need's baseline itself is still unexplained: it dropped sharply after the first
night, then fell by about 285 ms a night.

## Next test

The first debt after the newest sleep decides: the rule above predicts 26 minutes, SD-CAP 53. After that, a night with positive debt
and a new shortfall separates replacing debt from adding to it.
