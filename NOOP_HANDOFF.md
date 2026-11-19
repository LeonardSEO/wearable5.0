# What NOOP can take from this repository

Checked against [ryanbr/noop](https://github.com/ryanbr/noop) `main` at `2a1de760` (2026-10-25). Each item says what to change,
the evidence, and where it goes. NOOP's rules apply to all of it: facts only, no WHOOP code, and scoring claims follow
`docs/VALIDATION_PROTOCOL.md`. Metric thresholds were fixed before the data (`CRITERIA` in `re/validate_own_strap.py`).

## Scores: closer to WHOOP on the same nights

NOOP's own scorers and this repository's formulas, run on the same nights, cycles and workouts of one WHOOP 5.0 and scored against
WHOOP's values for them. NOOP's code is called unchanged through `re/noop_scores`. Every number of ours is out-of-sample: leave-one-out
with the constants refitted per fold, or a rule frozen before the data. The exception is sleep need: its baseline and recent-strain constants were fitted on these nights, but they account for at most seconds of its error (baseline within 5 ms, strain need within 16 s); its minutes come from the debt chain.

| Score | NOOP, mean off WHOOP | This repository, mean off WHOOP | Same |
|---|---|---|---|
| Recovery | Charge: **11.9** points (3 of 12 within 3) | **4.1** (8 of 12 within 3); 5.8 with every constant refitted per fold | 12 nights |
| Sleep performance | Rest: **10.1** points (1 of 13 within 2) | **1.5** (9 of 13 within 2) | 13 nights |
| Sleep need | **17.0** min (7 of 13 within 15 min) | **6.9** min (10 of 13 within 15 min) | 13 nights |
| Day strain | Effort: **2.46** (0 of 11 within 0.3) | **0.73**; **0.13** on the 9 cycles without skiing or weightlifting (8 within 0.3) | 11 cycles |
| Workout zones | **54 %** of workout time in a different zone than WHOOP | **2.5 %** | 3 workouts |

How it was run, so it can be checked:

- `python re/noop_compare.py <API snapshot> <strap data>` reproduces the whole table. It needs `re/noop_scores` built against an
  upstream NOOP checkout (instructions in the script).
- NOOP gets what its app uses: HRV, resting HR, respiration and skin temperature per night, sleep totals for Rest, and per-second
  strap heart rate. Where it gets WHOOP's own value instead (sleep consistency, maximum HR), that favours NOOP. With WHOOP's sleep
  performance in place of Rest, Charge is 14.4 off.
- Each side uses its own sleep-need model. Both start from zero debt, skip days without a sleep record, get the same naps, and leave
  out the first 3 nights.
- Effort is on NOOP's 0–100 scale and is multiplied by 21/100 here.
- The WHOOP side comes from the owner's own data through WHOOP's official developer API, read-only. Scope: one wearer, 12 to 16
  nights, 11 cycles, 5 workouts.

## Score changes NOOP can make

Formulas and constants are in `re/score_formulas.py` and [re/SCORE_MODELS.md](re/SCORE_MODELS.md). Constants marked personal belong to
this wearer; NOOP fills those slots from its own per-user baselines. The structure and the other constants carry over.

| # | Change in NOOP | Evidence | Where in NOOP |
|---|---|---|---|
| S1 | Zones on heart-rate reserve: 40/60/70/80/90 % of (max HR − resting HR) above resting HR, with time below 40 % as zone 0 | 2.5 % of workout time misplaced against NOOP's 54 % on 3 workouts the rule had not seen; 96.2–99.3 % of seconds in WHOOP's zone per workout | `HRZones.swift` (`zoneEdges` are % of max HR from 50 %) |
| S2 | Sleep need = baseline + debt + recent-strain need − nap asleep. Debt = min(7668000 ms, f × (need − asleep)) of the last scored main sleep, f = 1/2 or 9/14; a nap or a day without a sleep record leaves it unchanged. Recent-strain need = 25995.16 s^0.72809 e^(0.16742 s) ms for day strain s. Baseline is personal | 6.9 min off WHOOP's total against 17.0. Shortfall, cap and nap credit exact on every night (`re/verify_findings.py`); which factor applies is open | `SleepDebt.swift` (fixed 8 h, 55 % carry), `Rest.personalizedNeedHours` |
| S3 | Sleep performance = 94.82 − 4.679 x^−2.884 + 0.2359 (consistency − 80), x = asleep / need | 1.5 points off against Rest's 10.1; leave-one-out on WHOOP's own need 15 of 16 nights within 2 | `AnalyticsEngine.Rest.composite` |
| S4 | Recovery = 100 (HRV / B)^1.066 × exp(0.0774 (SP − mean SP)/10 − 0.0516 (RHR − RHR ref)), B a shrunken running mean of ln HRV. The HRV prior and the RHR reference are personal | 4.1 points off against Charge's 11.9; 5.8 even with all constants refitted per fold | `RecoveryScorer.recovery` |
| S5 | Day strain = 0.781 L^0.4086, L = Σ over minutes with mean HR ≥ 94 of e^(0.065 (HR − 100)) | 0.73 off against Effort's 2.46; 0.13 against 2.30 on cardio days. Skiing and weightlifting days read 1.3–1.8 low | `StrainScorer.strain` |

## Protocol: ready now

| # | Change in NOOP | Evidence | Where in NOOP | PR |
|---|---|---|---|---|
| 1 | Pass `feedsSync: true` for 5/MG, reading the newest-page clock at body offset 57 | 589 replies from 21 sessions, FINDINGS §3 | `Strand/BLE/BLEManager.swift`, `handleDataRangeResponse` | [#2824](https://github.com/ryanbr/noop/pull/2824) |
| 2 | Stop the history auto-continue at 0 pages behind | backlog = write − trim, FINDINGS §3 | `Strand/BLE/BLEManager.swift` | [#2823](https://github.com/ryanbr/noop/pull/2823) |
| 3 | Name commands 146, 147 and 155–159; mark 10 and 11 deprecated; add events 109 and 123 | `re/compare_noop.py`, same in app 5.473.0 and 5.475.0 | `Resources/whoop_protocol.json` | 155–159 in [#2828](https://github.com/ryanbr/noop/pull/2828) |
| 4 | Add R26 heart rate from autocorrelation, with the acceptance filter | 1.48 bpm on 391 of 1145 bursts, 6.24 for a shuffled control. Asleep only. FINDINGS §16, §18 | new; NOOP has no R26 heart rate | none |

## The WHOOP app and the raw data from the same night

A strap gives each record to the first client that acknowledges it, then trims it, so a night WHOOP's app has synced is lost to every
other client. The strap keeps trimmed pages on flash until the ring overwrites them, about 3 weeks at the normal rate.

| # | Change in NOOP | Evidence | Where in NOOP |
|---|---|---|---|
| 8 | An opt-in "fetch nights the WHOOP app already took": start `SEND_HISTORICAL_DATA` (22), and after the first HISTORY_END send `HISTORICAL_DATA_RESULT` (23) with `01 + page u32 + wrap u32` of the older start page. Trim moves there and the strap serves from it. Acknowledge chunks as usual, then send 23 once more with the original trim and `ABORT_HISTORICAL_TRANSMITS` (20) | One strap, firmware 50.43.2.0: four spans of 6 to 8 hours re-read completely at about 120× realtime (a night in 3 to 4 minutes), trim restored each time, and WHOOP's app synced on normally. The firmware log confirms the page-plus-wrap format. `FORCE_TRIM` (25) is not needed. Find the start page with `SET_READ_POINTER` (33), which exposes each page's stored time ([§17](FINDINGS.md#17-re-reading-trimmed-history-an-older-acknowledgement-during-a-burst-moves-trim-back-own-strap), [guide](re/REREAD_HISTORY.md)) | the 5/MG history sync in `Strand/BLE/BLEManager.swift` |

Costs seen: pairing another device takes the strap's bond from the phone; a run that does not restore trim makes the strap re-send
those pages to WHOOP's app (WHOOP did not rescore the re-sent day). Whether WHOOP scores older pages it has never seen is untested.

## Metrics on 12 paired nights

Our values from the strap against WHOOP's on the same nights, with the thresholds fixed in advance (`re/validate_own_strap.py`,
WHOOP's side from its official API).

| Metric | Result | Verdict | Where in NOOP |
|---|---|---|---|
| HRV (RMSSD) | 1.60 ms mean off, r = 0.89 | Proven on 12 nights | `HRVAnalyzer` |
| Respiratory rate from R-R | 0.16 per min mean off, r = 0.77 | Proven on 12 nights | `SleepStager.respRateFromRR` |
| Skin temperature | 0.08 °C mean off, r = 0.93 | Proven on 11 nights | skin-temperature path in `AnalyticsEngine` |
| Sleep onset from band state | 13.9 min median off; the lag is a near-constant 14.1 min (SD 1.5), so subtracting it is the next test | Proven on 12 nights | `SleepStager` |
| Resting HR | 4.6 bpm low, r = 0.76; nearly all of it a constant offset: 1.2 bpm after the shift | Failed at the 3 bpm bar; the offset is a lead | `PrimarySessionRestingHR` |
| Wake time | 9.6 min median off, once sleep segments under 2 h apart count as one night | Proven on 12 nights | `SleepStager`, `WakeMotionRefinement` |
| SpO₂ from R18 byte 82 | Byte 82 is the strap's SpO₂ reading (measurement windows on 3 straps, FINDINGS §13). Against WHOOP: 0.53 % mean off, r = 0.80; of all R18 bytes it tracks WHOOP best (r = 0.94) | Proven on 12 nights | `Interpreter.swift`, `spo2_candidate_82`; PRs [#2825](https://github.com/ryanbr/noop/pull/2825), [#2826](https://github.com/ryanbr/noop/pull/2826) |

## Candidates, not sent to a strap yet

| # | Item | Evidence | Where in NOOP |
|---|---|---|---|
| 7 | Request bodies for alarms, haptics, wrist and optical commands | read from the app, FINDINGS §19 | `docs/PROTOCOL_ALARMS.md`, `docs/PROTOCOL_COMMANDS.md` |

## Not here

- Firmware images and the flashing commands. The update flow is documented only, in `re/RE_OPPORTUNITIES.md` §1.
- Anything already settled in NOOP, such as R-R in milliseconds and the 84, 98, 151, 121 and 128 probes.
- Stress and sleep stages: NOOP has `StressIndex` and `SleepStager`; this repository has nothing better to offer yet.
