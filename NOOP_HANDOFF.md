# What NOOP can take from this repository

Checked against [ryanbr/noop](https://github.com/ryanbr/noop) `main` at `2a1de760` (2026-10-26). Each item says what to change,
the evidence, and where it goes. NOOP's rules apply to all of it: facts only, no WHOOP code, and scoring claims follow
`docs/VALIDATION_PROTOCOL.md`. Thresholds here were fixed before the data (`CRITERIA` in `re/validate_own_strap.py`).

## Ready now

| # | Change in NOOP | Evidence | Where in NOOP | PR |
|---|---|---|---|---|
| 1 | Pass `feedsSync: true` for 5/MG, reading the newest-page clock at body offset 57 | 589 replies from 21 sessions, FINDINGS §3 | `Strand/BLE/BLEManager.swift`, `handleDataRangeResponse` | [#2824](https://github.com/ryanbr/noop/pull/2824) |
| 2 | Stop the history auto-continue at 0 pages behind | backlog = write − trim, FINDINGS §3 | `Strand/BLE/BLEManager.swift` | [#2823](https://github.com/ryanbr/noop/pull/2823) |
| 3 | Name commands 146, 147 and 155–159; mark 10 and 11 deprecated; add events 109 and 123 | `re/compare_noop.py`, same in app 5.473.0 and 5.475.0 | `Resources/whoop_protocol.json` | 155–159 in [#2828](https://github.com/ryanbr/noop/pull/2828) |
| 4 | Add R26 heart rate from autocorrelation, with the acceptance filter | 1.46 bpm on 184 of 528 bursts, 5.78 for a shuffled control, 0.92 on 82 bursts the filter had not seen. Asleep only. FINDINGS §16, §18 | new; NOOP's packages and docs have no R26 heart rate | none |

## Ready at 5 paired nights

| # | Change in NOOP | Evidence so far | Where in NOOP | PR |
|---|---|---|---|---|
| 5 | Show byte 82 as SpO₂, one value per window | Windows on 3 straps. 0.34 % from WHOOP on 3 nights, FINDINGS §13, §18. NOOP's two contrary #103 nights are unexplained | `Interpreter.swift`, `spo2_candidate_82` | [#2825](https://github.com/ryanbr/noop/pull/2825), [#2826](https://github.com/ryanbr/noop/pull/2826) |
| 6 | Compare respiratory rate, HRV and skin temperature with these results | 0.13 per min, 1.48 ms, 0.12 °C on 3 nights, FINDINGS §18 | `StrandAnalytics` | none |

## Candidates, not sent to a strap yet

| # | Item | Evidence | Where in NOOP |
|---|---|---|---|
| 7 | Request bodies for alarms, haptics, wrist and optical commands | read from the app, FINDINGS §19 | `docs/PROTOCOL_ALARMS.md`, `docs/PROTOCOL_COMMANDS.md` |

## Coming: WHOOP's score mapping

The WHOOP export pairs raw inputs with Recovery, Day Strain and Sleep performance for each cycle. With enough cycles this
gives a measured reference for `RecoveryScorer` and `StrainScorer` in `StrandAnalytics`. State: 3 of 20 cycles for
recovery and sleep, 2 of 5 for strain. NOOP's offline rule is unaffected: the fit uses one owner's own export.

## Not here

- Firmware images and the flashing commands. The update flow is documented only, in `re/RE_OPPORTUNITIES.md` §1.
- Anything already settled in NOOP, such as R-R in milliseconds and the 84, 98, 151, 121 and 128 probes.
