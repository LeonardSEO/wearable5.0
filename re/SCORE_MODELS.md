# Score models

The formulas this repository uses for WHOOP's scores, how they do on data they did not see, and what was tried and ruled out on the
way. Code: `re/score_formulas.py`. Head-to-head with NOOP: `re/noop_compare.py`. Rules against an API snapshot: `re/api_checks.py`.

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

## Standalone chain

Every input from the strap and this repository's decoders; WHOOP's values only score the result (12 nights; a local script over the owner's data). HRV 11 of 12 within
3 ms. Day strain 9 of 11 within 0.3. Asleep time 16 min mean off. Sleep performance 4.6 points mean off, recovery 5.0 (worst 11.2).
Asleep time and the missing stress input carry most of that error.

## Rules settled by the official API

In milliseconds, against every night of an API snapshot (`re/api_checks.py`, `re/verify_findings.py`).

| Rule | Cases |
|---|---:|
| need = baseline + debt + recent-strain need + nap credit | every night: the API reports these four parts |
| debt = min(7668000, f × (need − asleep)) of the last scored main sleep, f = 1/2 or 9/14; a nap or a day without a sleep record holds it | 16 of 16 within 1 ms; which f applies is open |
| nap credit = −(the nap's asleep time) | 1 of 1 |
| export minutes = the API's milliseconds rounded down | every value checked |

## Zone rule ZR-1, frozen (`re/hrr_zones.py`)

Zones are percentages of heart-rate reserve, (HR − rest) / (max − rest), with edges at **40, 60, 70, 80 and 90 %**, WHOOP's maximum HR from the
API and a resting HR of 58 (personal). Rest and edges were chosen on two workouts: one reproduced in all 6 zones to the second (1379 of 1379 s),
the other at 98.69 %. Frozen there, the rule put 96.2 to 99.3 % of seconds in WHOOP's zone on the 3 later workouts, so the stricter bar of
99 % per new workout holds on 1 of 3. NOOP's zones, starting at 50 % of maximum HR, misplace 54 % of the same time. The match also shows that
R18 heart rate and its clock line up with what WHOOP scored.

## Ruled out

- **The first candidates** (frozen 5 to 7 November from the first cycles: SP-Q, SP-E, SP-M, SP-M2, SP-L, SP-U, SD-R, SD-A, SD-CAP, DS-C,
  DS-LOG, DS-LIN, DS-POW, R-SLEEP, R-HRV, SN-Q, BL-L, BL-UTC). Each fitted the nights that shaped it and missed the first nights it had
  not seen; the formulas above replaced them.
- **Sleep performance as plain asleep/need,** or as any concave function of asleep/need alone.
- **Day strain proportional to Edwards TRIMP,** or one rising function of it for day and workout strain alike; also any sum of
  non-negatively weighted zone seconds followed by one rising curve.
- **Recovery as a fixed function of HRV, resting HR and sleep performance** without a personal baseline: from one night to the next all
  three worsened and recovery rose.
- A REM threshold as the switch between 1/2 and 9/14: two nights with little REM took 9/14. REM share, deep share, strain need,
  asleep/need and the source night's own debt do not separate the two groups either.
- Recovery as a z-score or deviation against the own baseline with 50 at the baseline: at best 3 of 9 within 3.
- Recovery from HRV and sleep alone (REC-PS): four registered nights in a row came out 16 to 21 too high when resting HR rose.
- Standalone asleep time better than in-bed time × 0.95 from band state, HR or R-R: band state marks the whole window asleep, and
  trimming edges by HR makes it worse. Awake time before rising cannot be seen without accelerometer data.

## Measured along the way

- Time in bed in the export is the API's value rounded down to whole minutes.
- Efficiency equals asleep / in bed on most sleeps and is slightly higher on some; the difference is unexplained.
- The app's sleep-stress hours add up to time in bed. Sleep stress is not in the API, so no formula here uses it.
- An early zone fit with a maximum HR of 214 and an 11-minute time shift was wrong: it came from assuming zones start at 50 % of maximum HR.
