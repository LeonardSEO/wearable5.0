# Reverse-engineering analyses

Scripts here run on **real** 5/MG data published by strap owners. Raw corpora are downloaded on
demand into `re/corpus/` (gitignored); only scripts and results are committed.

| Script | Question | Result |
|---|---|---|
| `harvest_frames.py` | Extract every CRC-valid 5/MG frame from a tree of checked-out repos and downloads | de-duplicated JSONL with sources |
| `organize_corpus.py` | Arrange harvested frames and original files into a local corpus with a manifest | `frames/`, `captures/`, `ground_truth/`, `MANIFEST.csv` |
| `prepare_donation.py` | Turn your own archive, logs, HCI capture and WHOOP export into a privacy-safe donation zip | `frames.jsonl`, `whoop_export/`, `MANIFEST.json` |
| `pklg_extract.py` | Extract 5/MG frames from an iOS PacketLogger (.pklg) or Android btsnoop capture | frames JSONL with direction and ATT handle |
| `analyze_rr_unit.py` | Is R-R in ms or 1/1024 s? (0x2A37 vs R18, phone clock) | `results/rr_unit.txt` — milliseconds |
| `analyze_official_sync.py` | What the official app sends, feature-flag values | `results/official_sync_ios.txt` |
| `analyze_console.py` | Firmware console log reconstruction and inventory | `results/console_inventory.txt` |
| `analyze_overnight_r18.py` | One night of R18 described | `results/overnight_r18.txt` |
| `analyze_r18_b82_windows.py` | Byte-82 SpO₂ measurement windows | `results/r18_b82_windows.txt`, `results/spo2_windows_ios_night.txt` |
| `analyze_r26.py` | R26 contiguity and heart rate vs R18 | `results/r26_analysis.txt` |
| `analyze_experimental_metrics.py` | Sleep periods, respiratory rate, skin temperature and R26 HR (library helpers) on a night, vs numpy/scipy | `results/experimental_metrics.txt` |
| `analyze_r20_config.py` | R20 block configuration and two-channel bursts per session | `results/r20_config_bursts.txt` |
| `analyze_r20_hr_sessions.py` | R20 heart rate on every session with a reference | `results/r20_hr_sessions.txt` |
| `analyze_v20_optical.py` | Which R20 channels carry the pulse, and does derived HR track a varying reference? | `results/v20_optical_noop1992.txt`, summarised in FINDINGS §4 |

```bash
re/fetch_corpus.sh                       # needs the GitHub CLI
python3 -m venv .venv && .venv/bin/pip install numpy scipy
.venv/bin/python re/analyze_v20_optical.py re/corpus/v20_frames/rejected_history.jsonl \
    re/corpus/v20_ground_truth/ground_truth_window.csv
```

## Corpus regression

`WHOOP5_CORPUS=<folder built by organize_corpus.py> python3 -m unittest tests.test_corpus` (from
`python/`) decodes every frame of the local corpus. It is skipped when the variable is unset, so CI
never needs the data.

## Donating data

```bash
python3 re/prepare_donation.py <archive / logs / capture / WHOOP export ...> --out my-donation
```

Most useful, in order:
1. One or more **overnight** history offloads (NOOP's `rejected_history.jsonl`, strap logs, or an HCI
   capture of the official app) together with the WHOOP data export for the same nights.
2. Sessions with R21 IMU or R22 records (none are public yet).
3. Firmware versions other than 50.37–50.42.

The tool keeps only CRC-valid 5/MG frames and strips identifiers (see its docstring for the exact
rules). Dates stay in, because they are what lines frames up with the export. Read `MANIFEST.json`
before you share the zip.
