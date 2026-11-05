# AGENTS.md: working on wearable5.0

## Mission

Everything here exists to make [NOOP](https://github.com/ryanbr/noop) better on the WHOOP 5.0 / MG. The end product is a clear
list: what is proven, what is new, and what NOOP should change. Steer each task by one question: **what does this let NOOP
ship or stop guessing?** Work with no answer waits.

Three streams feed that list:

1. **Protocol.** Decode what the strap sends and accepts.
2. **Metrics.** Prove our values against WHOOP's own on the same nights.
3. **Scores.** Work out recovery, strain and sleep from raw data plus WHOOP's scores. WHOOP computes them on its servers, so
   there is no formula to read. Input and output pairs replace it.

Also compare each new WHOOP app version with NOOP, so new commands and behaviour show up (`re/compare_noop.py`).

## How to write results

- **Say what is proven, plainly.** Use the verdicts from FINDINGS: Proven, Measured, Failed, Open. No "might", "seems" or
  "experimental" on a settled result. Put the scope and the numbers in the sentence instead.
- **Never raise a verdict past the evidence.** Thresholds in `CRITERIA` (`re/validate_own_strap.py`) are fixed. Do not lower them
  or the 5-night bar to reach a pass. NOOP's `docs/VALIDATION_PROTOCOL.md` requires this too.
- **Keep the proof.** Each number names the script that reproduces it.

## Where things live

| File | Holds |
|---|---|
| [NOOP_HANDOFF.md](NOOP_HANDOFF.md) | What NOOP can take now. Update it with every result |
| [FINDINGS.md](FINDINGS.md) | The proof. The status table on top is the state of the project |
| [re/RE_OPPORTUNITIES.md](re/RE_OPPORTUNITIES.md) | What is left to reverse-engineer, ranked |
| [re/README.md](re/README.md) | Every analysis script |
| `protocol/whoop5_protocol.json` | The schema. Edit only this, then run `scripts/sync-schema.sh` |
| `../whoop5-data/own_strap/` | The owner's raw data and `REPORT.md`. Never commit it |

## State on 2026-11-05

**Done.** Framing, history sync, record structure, command and event tables, R-R unit, byte 82 as SpO₂, re-reading history,
and proof that the scores are server-side.

**Waiting on nights.** SpO₂, respiration, HRV, skin temperature and sleep onset meet the bar on 3 of 5 nights.

**Failing.** Wake time (33.6 min, bar 15) and resting heart rate (3.75 bpm, bar 3).

**Not done.** Score formulas (3 of 20 cycles, strain 2 of 5), sleep stages, gyro scale.

## The data routine

The owner has the WHOOP app free for one month. Target 20 nights, minimum 5.

1. Wear the strap. Let the WHOOP app sync.
2. Before the month ends, and within 3 weeks of the oldest unread night, make a WHOOP export. It holds every score per cycle, so
   nobody notes them by hand.
3. Pair the Mac and re-read those nights (`re/REREAD_HISTORY.md`). The ring holds about 22 days (131,072 pages at 245 per hour).
   Always pass `--restore`.
4. Run `re/pipeline.sh <data folder> <export.zip>`, then update FINDINGS and NOOP_HANDOFF.

Split nights by firmware when a check fails. Nights after 5 November 11:03 are on 50.43.2.0.

## Hard lines

- Never redistribute WHOOP code, firmware or assets. Never write firmware to a strap. Commands marked `destructive` in the schema
  are documentation only.
- Keep the re-read method out of anything sent to NOOP, including NOOP_HANDOFF.md. The owner decided this.
- Raw captures and personal data stay out of git.
- Commit or post to NOOP only when the owner asks.

## Checks

```bash
cd python && python3 -m unittest discover -s tests
cd Packages/Whoop5Protocol && swift test
cd kotlin && ./gradlew test
```
