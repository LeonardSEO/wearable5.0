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

## First test on a night the models had not seen

| Model | Prediction | WHOOP | Result |
|---|---:|---:|---|
| Sleep debt rule | 1615211 ms | 1615211 ms | **exact** |
| SP-M (with app stress) | 79.80 | 81 | miss |
| SP-E | 78.87 | 81 | miss |
| SP-Q | 78.65 | 81 | miss |
| R-SLEEP | 32.89 | 50 | miss |
| R-HRV | 32.29 | 50 | miss |

The debt rule passed its first prospective test. Every frozen sleep-performance and recovery candidate failed on the same night, so their coefficients are
rejected. The first recovery that WHOOP no longer marks as calibrating jumped well above what the calibrating ones predicted, which fits recovery changing after
calibration. Also on this night: the need baseline fell by another 284 ms (284, 285, 284 in a row), efficiency equals asleep / in bed on 3 of 5 sleeps, and the
stress hours again add up to time in bed within 1.05 minutes.

Registered next: debt 5208063 ms; baseline about 284-285 ms lower.

## Round 2, frozen 6 November (`round2` in `re/api_checks.py`)

From an outside mathematical review of the API data; only sleeps after 6 November test them.

- **Ruled out:** any sum of non-negatively weighted zone seconds, zone 0 included, followed by one rising curve for both day and workout strain. One
  workout scores above another with less weighted load than a quiet day would need. This uses reconstructed day vectors next to WHOOP's workout vectors.
- **Ruled out:** any concave function of asleep/need alone for sleep performance (three sleeps contradict it).
- Debt variants, separable now that debt was positive: replace (5208063 ms), add (6823274 ms), d + floor((N - d - m)/2) (6015668 ms).
- BL-L baseline: 27834334 - floor(284.5 k) from the second record: 27833196, 27832912, 27832627 next.
- Strain-need SN-PE: 25995.162137 s^0.728090984 e^(0.167421361 s); SN-Q: 18968.446118 s^2 - 179627.389611 s + 606847.675475. Both interpolate 3 points
  exactly, so undetermined. Pass = within 1 %.
- Sleep performance SP-M2: q = (efficiency + consistency + 100 - medium %) / 3, P = q + 0.5 + 0.375 (u - q). Control SP-L: 53.8 + 0.412 u. Both fit 3 sleeps,
  not the first two.
- Efficiency null model: asleep / in bed. It misses 2 of 5 sleeps by 0.12 and 0.40; a shorter denominator would fit them but is chosen afterwards.
- Recovery: no formula; a constant 50 is the reference only.

## Settled by the official API

`re/api_checks.py`, in milliseconds. The rules below replace the candidates they settle: SN-C holds with a nap factor of exactly 1, and
SD-CAP's 53 and every other nap factor are unlikely, though the next debt is the first test on unseen data.

| Rule | Cases |
|---|---:|
| need = baseline + debt + recent strain + nap credit | 5 of 5 |
| debt = min(7668000, f x (need - asleep)) of the last scored main sleep, f = 1/2 or 9/14; a nap or a day without a sleep record holds it. Which f applies is open (below) | 16 of 16 (`re/verify_findings.py`) |
| nap credit = -(the nap's asleep time) | 1 of 1 |
| export minutes = floor of the milliseconds | all checked |

The frozen strain models fit to 0.1 only: the API's decimals show they are not exact, for example DS-C is off by 0.02-0.03. Recovery was
in WHOOP's calibration on all cycles here. Sleep need's baseline itself is still unexplained: it dropped sharply after the first
night, then fell by about 285 ms a night.

## Formulas in use

Code: `re/score_formulas.py`. Verdicts follow FINDINGS: these are **Measured** on one wearer, 12 to 16 nights, short of the 27-night
bar for a score model. Every count below is out-of-sample (leave-one-out with the constants refitted per fold, a rule frozen before
the data, or a prediction registered before the night and scored after it), except the baseline and recent-strain rows, whose
constants were fitted on these nights; their errors are milliseconds and seconds, and the need's minutes come from the debt chain. Personal constants belong to this wearer; a client
fills those slots from its own baselines. The structure and the other constants carry over.

| Score | Formula | Out-of-sample result |
|---|---|---|
| Sleep need | baseline + debt + recent-strain need − nap asleep | 6.9 min mean against WHOOP's total, chained from its own previous need (13 nights) |
| — baseline | 27834333.7 − 284.3152 k ms, k = UTC days of the onset (personal) | within 4.7 ms on 15 nights, mean 0.9 ms |
| — debt | min(7668000, f (need − asleep)) of the last scored main sleep, f = 1/2 or 9/14 | shortfall and cap exact on 16 of 16; which f applies is open |
| — recent-strain need (SN-PE) | 25995.162137 s^0.728090984 e^(0.167421361 s), s = day strain of the cycle ending at onset | within 16.2 s on 15 nights; 5 of 5 registered nights within 60 s |
| — nap credit | − the nap's asleep time | exact |
| Sleep performance (SP-C2) | 94.81929 − 4.67893 x^−2.88390 + 0.23588 (consistency − 80), x = asleep / need, consistency 0 counts as 80 | leave-one-out 15 of 16 within 2 points, mean 1.25; the miss is the one night with long high stress. 4 of 4 registered nights within 2 |
| Recovery (REC-RHR) | 100 (HRV/B)^1.066 exp(0.07735 (SP − S̄)/10 − 0.08547 high-stress min/60 − 0.05156 (RHR − 59.08)), B = exp((5.0265 ln 103.2555 + Σ ln HRV) / (5.0265 + n)) over earlier nights, S̄ their mean SP; the HRV prior and the RHR reference are personal | without stress input, leave-one-out 8 of 12 within 3 points, mean 4.1; refitting all six constants per fold 5 of 12, mean 5.8. 1 of 1 registered night within 3 |
| Day strain (DS-E) | 0.78115 L^0.40855, L = Σ over minutes with mean HR ≥ 94 of e^(0.065 (HR − 100)), strap HR | nested leave-one-out 8 of 9 cycles without skiing or weightlifting within 0.3, mean 0.13; all 11 cycles mean 0.73. Muscular days read 1.3 to 1.8 low |
| Workout zones (ZR-1) | 40/60/70/80/90 % of heart-rate reserve, resting HR 58 (personal), WHOOP's maximum HR | 99.2 % of seconds in WHOOP's zone on the 2 workouts it was chosen on; 96.2 to 99.3 % on the 3 later ones. The frozen bar of 99 % per new workout holds on 1 of 3 |

Leads, not yet confirmed on new nights: the strap's resting HR reads 4.6 bpm below WHOOP's (SD 1.5, 12 nights; 1.2 bpm error after
the offset); the band-state sleep onset lags WHOOP's by 14.1 min (SD 1.5).

## Registered before the night, scored after

| Model | Nights within tolerance |
|---|---|
| Debt shortfall | exact on every registered night; the 1/2 factor was wrong on the nights that took 9/14 |
| Baseline | within 5 ms on every registered night |
| SN-PE | 5 of 5 within 60 s |
| SP-C2 | 4 of 4 within 2 points |
| REC-PS (no RHR term) | 0 of 4 within 3; replaced by REC-RHR |
| REC-RHR | 1 of 1 within 3 |

## Ruled out since round 3

- A REM threshold as the switch between 1/2 and 9/14: two nights with little REM took 9/14. REM share, deep share, strain need,
  asleep/need and the source night's own debt do not separate the two groups either.
- Recovery as a z-score or deviation against the own baseline with 50 at the baseline: at best 3 of 9 within 3.
- Recovery from HRV and sleep alone (REC-PS): four registered nights in a row came out 16 to 21 too high when resting HR rose.
- Standalone asleep time better than in-bed time × 0.95 from band state, HR or R-R: band state marks the whole window asleep, and
  trimming edges by HR makes it worse. Awake time before rising cannot be seen without accelerometer data.

## Standalone chain

Every input from the strap and this repository's decoders; WHOOP's values only score the result (12 nights; a local script over the owner's data). HRV 11 of 12 within
3 ms. Day strain 9 of 11 within 0.3. Asleep time 16 min mean off. Sleep performance 4.6 points mean off, recovery 5.0 (worst 11.2).
Asleep time and the missing stress input carry most of that error.

## Head-to-head with NOOP

`re/noop_compare.py` runs NOOP's own scorers through `re/noop_scores` (built against upstream `ryanbr/noop` `main` at `2a1de760`)
and this repository's formulas on the same nights, cycles and workouts. NOOP gets what its app path uses; where it gets WHOOP's own
values (sleep consistency, maximum HR, and in one row WHOOP's sleep performance) that favours NOOP. Each side uses its own sleep-need
model; both start from zero debt and leave out the first 3 nights. NOOP's Effort is on a 0–100 scale and is multiplied by 21/100.

| Score | NOOP, mean off WHOOP | This repository, mean off WHOOP | Same |
|---|---|---|---|
| Recovery | Charge with its own Rest: 11.9 (3 within 3). With WHOOP's sleep performance: 14.4 (0 within 3) | REC-RHR: 4.1 (8 within 3). All constants refitted per fold: 5.8 | 12 nights |
| Sleep performance | Rest: 10.1 (1 within 2) | SP-C2 on its own need: 1.5 (9 within 2) | 13 nights |
| Sleep need | 17.0 min (7 within 15 min) | 6.9 min (10 within 15 min) | 13 nights |
| Day strain | Effort: 2.46 (0 within 0.3) | DS-E: 0.73 | 11 cycles |
| Day strain without skiing or weightlifting | Effort: 2.30 (0 within 0.3) | DS-E: 0.13 (8 within 0.3) | 9 cycles |
| Workout zones, time in a different zone than WHOOP | %HRmax 50/60/70/80/90: 54 % | ZR-1: 2.5 % | 3 workouts after ZR-1 was frozen |
