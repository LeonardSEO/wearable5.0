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
- **Workout zones (`re/workout_zones.py`).** One workout: zone shares match within 1.6 points in total at a maximum HR of 214 with
  the window 660-690 s later than exported. The unfitted mean (118.5 against 119) and maximum (157 against 157) agree too. Without the
  shift the error is at least 11 points at any maximum. This search covered 241 shifts and 71 maximums on one workout, so it is a
  lead. Test: a second workout should give the same maximum. The cause of the shift is unknown; no strap clock correction of that
  size shows on that day.

## Next test

The first debt after the 5 November sleep decides the debt family: SD-R, SD-A and SD-G predict 26 minutes, SD-CAP 53.
