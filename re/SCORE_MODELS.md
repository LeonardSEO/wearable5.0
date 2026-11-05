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

## Fit on the export against fit on the API's exact inputs

These are the same nights, so neither column is a test on new data. A miss rejects the frozen coefficients, not the family.

| Id | On export values | On API inputs |
|---|---:|---:|
| SP-Q | 4 of 4 | **3 of 4**: 75.52 rounds to 76, WHOOP reports 75 |
| SP-E | 4 of 4 | 4 of 4 |
| R-SLEEP | 3 of 3 | 3 of 3, one very close to the rounding edge |
| R-HRV | 3 of 3 | **2 of 3**: 41.61 rounds to 42, WHOOP reports 43 |
| DS-C, DS-LOG, DS-LIN, DS-POW | fit to 0.1 | fit to 0.1, not the API's decimals |

## SP-M, a composite with stress from the app, frozen

P = (0.4 sufficiency + 0.2 efficiency + 0.2 consistency + 0.2 (100 - stress share)) / (0.8 + 0.2 if consistency exists), with sufficiency =
min(100, 100 asleep/need) and stress share = (medium + high) / (low + medium + high) from the WHOOP app, which the API does not give.

**Scope:** one separate main sleep with consistency and its own stress reading. Both such sleeps so far fit within rounding (94.56 and 89.78 against 95 and 90).
The weights come from the earlier illustration, and medium stress was chosen as the input after seeing the numbers. **Two points, so a lead.** New mornings test it
unchanged. Limiting the scope to these sleeps is itself a choice made after seeing a nap cycle not fit. Nap cycles stay recorded, because they show how WHOOP
combines sleeps.

High stress is 0 on every night, so its weight cannot be determined. Dossier SP-C used stress = high sleep stress and needed 7-18 %. With the app's 0 % those
specific weights fail: 83.6, 79.7, 96.4 and 92.3 against 81, 75, 95 and 90. That does not rule out every formula with high stress. No choice of non-negative weights on
sufficiency, efficiency, consistency and a fixed calm term fits all 4 sleeps either: the best is 0.53 off, just past the rounding limit of 0.5. That margin is thin,
so it points to a missing input without settling the form.

Stress hours add up to time in bed within 1.32 minutes, with the main sleep and nap together on the cycle that has a nap. So the window is about time in bed. Rounding,
missing stress samples and the exact link are unchecked, so identical periods are not established.

**Lead ST-1, frozen:** split each cycle's sleeps into 300 s windows from each sleep's start; take the mean HR per window with at least half its samples; medium stress is the
windows at or above 1.07 x the median of those means over the whole cycle. It gives 75, 35 and 55 minutes against 74, 39 and 54. It was picked from a search over thresholds and
window lengths, so it is not an established source.

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
- **The 214 lead and its 11-minute shift were wrong.** They came from assuming zones start at 50 % of maximum HR. The zones below need
  no shift.

## Zone rule ZR-1, frozen (`re/hrr_zones.py`)

Zones are percentages of heart rate reserve, (HR - rest) / (max - rest), with edges at **40, 60, 70, 80 and 90 %**, WHOOP's maximum HR from the
API and a resting HR of 58. These values are now frozen. New workouts test the rule without choosing rest or edges again.

From raw strap heart rate at the exported times, with no time shift: one workout is reproduced in all 6 zones to the second, 1379 of 1379 s. A
second workout is nearly reproduced: 98.69 %, with 26 of 1978 s one zone off, all at the 60 % edge. Together that is 99.23 %. Resting HR (of 16
values) and the edge set (of 4) were chosen on these same two workouts, so independent confirmation is still to come. A first edge at 50 % is
off by 2170 s on the same data. The match also shows R18 heart rate and its clock line up with what WHOOP scored.

Open: why the 60 % edge misses by 26 s on the second workout, whether the resting HR is fixed or changes, and why WHOOP's mean HR reads
about 4 bpm lower than the raw mean on both workouts.

**Strain.** With these zones one curve a ln(1 + b load) across 2 workouts and 3 cycles misses by 0.48 on average at best, so load is
still not identified.

## Settled by the official API

`re/api_checks.py`, in milliseconds. The rules below replace the candidates they settle: SN-C holds with a nap factor of exactly 1, and
SD-CAP's 53 and every other nap factor are unlikely, though the next debt is the first test on unseen data.

| Rule | Cases |
|---|---:|
| need = baseline + debt + recent strain + nap credit | 4 of 4 |
| debt = floor(0.5 x (need - asleep)) of the last main sleep; a nap holds it. This reproduces the transitions so far; how existing debt carries over is open | 3 of 3 |
| nap credit = -(the nap's asleep time) | 1 of 1 |
| export minutes = floor of the milliseconds | all checked |

The frozen strain models fit to 0.1 only: the API's decimals show they are not exact, for example DS-C is off by 0.02-0.03. Recovery was
in WHOOP's calibration on all cycles here. Sleep need's baseline itself is still unexplained: it dropped sharply after the first
night, then fell by about 285 ms a night.

## Next test

The first debt after the newest sleep decides: the rule above predicts 26 minutes, SD-CAP 53. After that, a night with positive debt
and a new shortfall separates replacing debt from adding to it.
