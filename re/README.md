# Reverse-engineering analyses

Scripts here run on **real** 5/MG data published by strap owners. Raw corpora are downloaded on
demand into `re/corpus/` (gitignored); only scripts and results are committed.

| Script | Question | Result |
|---|---|---|
| `analyze_v20_optical.py` | Which R20 channels carry the pulse, and does derived HR track a varying reference? | `results/v20_optical_noop1992.txt`, summarised in FINDINGS §4 |

```bash
re/fetch_corpus.sh                       # needs the GitHub CLI
python3 -m venv .venv && .venv/bin/pip install numpy scipy
.venv/bin/python re/analyze_v20_optical.py re/corpus/v20_frames/rejected_history.jsonl \
    re/corpus/v20_ground_truth/ground_truth_window.csv
```

## Donating data

Most useful, in order:
1. One or more **overnight** history offloads (R18 + R21 + R20) with a sleep reference (a watch's
   sleep stages, or the WHOOP data export for the same night).
2. The same night's exported **SpO₂ / respiratory rate / skin temperature** from the WHOOP app.
3. Frames from firmware versions other than 50.39–50.42.

Share frames only (hex of CRC-valid frames, as NOOP's RawHistoryArchive writes them). Do not share
HCI logs that contain your MAC address, serial number or identity blocks.
