# Reverse-engineering analyses

Scripts here run on **real** 5/MG data published by strap owners. Raw corpora are downloaded on
demand into `re/corpus/` (gitignored); only scripts and results are committed.

| Script | Question | Result |
|---|---|---|
| `harvest_frames.py` | Extract every CRC-valid 5/MG frame from a tree of checked-out repos and downloads | de-duplicated JSONL with sources |
| `organize_corpus.py` | Arrange harvested frames and original files into a local corpus with a manifest | `frames/`, `captures/`, `ground_truth/`, `MANIFEST.csv` |
| `prepare_donation.py` | Turn your own archive, logs, HCI capture and WHOOP export into a privacy-safe donation zip | `frames.jsonl`, `whoop_export/`, `MANIFEST.json` |
| `export_noop_db.py` | Export the raw frames NOOP keeps with `enableRawCapture` on (read-only snapshot of its database) | `frames.jsonl`, `whoop.sqlite` |
| `strain_model.py` | Build WHOOP day strain from per-second HR (zones -> TRIMP -> log fit); needs each strain cycle's whole span re-read | fit stats on stdout |
| `compare_noop.py` | Which commands, events and packet types differ between this schema and NOOP's | difference list on stdout |
| `score_search.py` | Search all transforms and combinations of the export's inputs for WHOOP's scores, judged on a holdout and against shuffled scores | verdict per score, `results/score_search_strain_public.txt` |
| `noop_compare.py` | NOOP's real Charge and Effort next to WHOOP's Recovery and Day Strain (builds on `noop_scores/`, which links a NOOP checkout) | table on stdout |
| `pipeline.sh` | One command: validate + score + strain over your data folder and WHOOP export (SpO2 standing on top) | combined report |
| `score_model.py` | Reverse-engineer WHOOP's recovery/strain/sleep scores empirically from your own export (input/output pairs) | fit stats on stdout |
| `validate_own_strap.py` | Every open claim checked on one owner's strap and WHOOP export, with thresholds fixed in advance | `REPORT.md`, `report.json` in the data folder |
| `pklg_extract.py` | Extract 5/MG frames from an iOS PacketLogger (.pklg) or Android btsnoop capture | frames JSONL with direction and ATT handle |
| `analyze_rr_unit.py` | Is R-R in ms or 1/1024 s? (0x2A37 vs R18, phone clock) | `results/rr_unit.txt` — milliseconds |
| `analyze_official_sync.py` | What the official app sends, feature-flag values | `results/official_sync_ios.txt` |
| `analyze_console.py` | Firmware console log reconstruction and inventory | `results/console_inventory.txt` |
| `analyze_overnight_r18.py` | One night of R18 described | `results/overnight_r18.txt` |
| `analyze_r18_b82_windows.py` | Byte-82 SpO₂ measurement windows | `results/r18_b82_windows.txt`, `results/spo2_windows_ios_night.txt` |
| `analyze_r26.py` | R26 contiguity and heart rate vs R18 | `results/r26_analysis.txt` |
| `probe_read_pointer.py` | Re-read trimmed history from your own strap (`fetch`); moves trim, see [REREAD_HISTORY.md](REREAD_HISTORY.md) | `frames.jsonl`, summarised in FINDINGS §17 |
| `analyze_r26_failure.py` | Why R26 heart rate fails awake, and what `hr_from_r26` accepts now | `results/r26_failure.txt`, summarised in FINDINGS §16 |
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

## What else to reverse-engineer

[RE_OPPORTUNITIES.md](RE_OPPORTUNITIES.md) ranks what is left: the firmware-update protocol (app side mapped, strap side not automated), unexercised commands, the app and API, and the current gaps.

## Validating on your own strap

Put NOOP snapshots (`export_noop_db.py`), re-read frames ([REREAD_HISTORY.md](REREAD_HISTORY.md)), HCI captures of the
official app (`.pklg`, `btsnoop_hci.log`) and the WHOOP export (`physiological_cycles.csv` or the export .zip) in one folder, then:

```bash
.venv/bin/python -I re/validate_own_strap.py <folder>
```

Each check reports PASS, FAIL or WAITING against the `CRITERIA` at the top of the script. Night checks
need at least 5 nights that appear in both the frames and the export. A night synced by NOOP never reaches
WHOOP's servers, so let the official app sync first and re-read the night afterwards.

## Weekly loop to prove SpO2 (and feed the score models)

SpO2 is the flagship claim and needs 5 paired nights (ours + WHOOP's own). Each round:

1. Wear the strap overnight; let the official WHOOP app sync, and export your data from the app.
2. Re-read the same night(s) raw from the strap: `re/refetch.sh <WhoopProbe.app> <venv-site-packages> <out> "<start>" "<stop>" 2654:7` (see REREAD_HISTORY.md). The strap keeps ~3 weeks, so a batch of nights re-reads in one pass.
3. Drop the export .zip in the data folder and run `re/pipeline.sh <data-folder> <export.zip>`.

`validate_own_strap.py` flips SpO2 from WAITING to PASS/FAIL once 5 nights are paired; the same nights also accrue toward the ~20-cycle score fits.

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
