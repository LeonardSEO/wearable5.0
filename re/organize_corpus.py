"""Arrange harvested WHOOP 5/MG data into a tidy local folder, keeping WHOOP 4.0 material out.

Inputs: the sources tree used by harvest_frames.py, its all_frames.jsonl, and a JSON map that assigns
each NOOP issue-attachment file a strap model ("5.0", "4.0" or "unknown") with the evidence used.
Output layout:
    frames/                       5/MG frames only (format-1 envelope, CRC-valid), all and per type
    captures/whoop5_verified/     original files whose 5.0/MG origin is established
    captures/model_unverified/    files with no reliable model signal (kept apart, not mixed in)
    ground_truth/                 reference files, prefixed with verified__ or unverified__
    MANIFEST.csv                  one row per copied file: model, evidence, frames, identifier flags
WHOOP 4.0 files are not copied; they are listed in EXCLUDED_WHOOP4.txt.

For local research only: several sources carry no licence and some contain device identifiers.

Usage: python re/organize_corpus.py <sources_dir> <all_frames.jsonl> <attachment_models.json> <dest_dir>
"""
from __future__ import annotations

import collections
import csv
import json
import os
import re
import shutil
import sys

MAC = re.compile(rb"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
SERIAL = re.compile(rb"\b(?:5AG|5AM|MGB|WG50)[0-9A-Z_]{5,}")
GROUND_TRUTH = re.compile(r"(whoop_days_shared|whoop_workouts_shared|sleep_debug|noop-raw-sensors|ground_truth|"
                          r"journal_entries|waveform\.csv)", re.I)

# (source path relative to sources/, destination under captures/whoop5_verified/, evidence)
VERIFIED = [
    ("noop1992_gists", "noop_issue_1992_v20_corpus", "R20 records, 5/MG envelope; donor states 5/MG fw 50.39.1.0"),
    ("digitalerdude_hci", "digitalerdude_ios_hci_whoop5_2026-07-10", "release titled WHOOP 5.0; 5/MG GATT and envelope"),
    ("megablocks_openwhoop/btsnoop_hci.log", "megablocks_android_btsnoop_mg/btsnoop_hci.log", "MG per publisher; 5/MG envelope"),
    ("megablocks_openwhoop/btsnoop_hci.frames.jsonl", "megablocks_android_btsnoop_mg/btsnoop_hci.frames.jsonl", "extracted"),
    ("Asherlc_dofek/packages/mobile/modules/whoop-ble/Tests/fixtures/imu-activation-capture.tsv",
     "dofek_imu_activation_capture.tsv", "every frame uses the 5/MG envelope"),
    ("tanarchytan_whoop-rs/real_frames.gen5_only.json", "whoop-rs_real_frames.gen5_only.json",
     "gen4 entries removed; gen5 entries only"),
    ("sennnen_maverick/fixtures/ecg/mg_electrode_100hz_v1.csv", "maverick_mg_ecg_100hz/mg_electrode_100hz_v1.csv",
     "hardware capture, WHOOP MG fw 50.33.2.0"),
    ("sennnen_maverick/fixtures/ecg/mg_electrode_100hz_v1.expected.json",
     "maverick_mg_ecg_100hz/mg_electrode_100hz_v1.expected.json", "metadata of the MG capture"),
    ("Sophonbot0_whoop-vault/ble/tests/fixtures/r52_frames.txt", "whoop-vault_wg50_r52_event_frames.txt",
     "WG50_r52 (WHOOP 5.0) fw 50.38.1.0"),
]


def copy(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=lambda _d, n: [x for x in n if x == ".git"])
    else:
        shutil.copy(src, dst)


def main(src: str, frames_path: str, models_path: str, dest: str) -> None:
    for sub in ("frames/by_type", "captures/whoop5_verified", "captures/model_unverified", "ground_truth"):
        os.makedirs(os.path.join(dest, sub), exist_ok=True)

    recs = [json.loads(line) for line in open(frames_path)]
    shutil.copy(frames_path, os.path.join(dest, "frames", "all_frames.jsonl"))
    groups = collections.defaultdict(list)
    for r in recs:
        groups[r["packet"] + (f"_L{r['layout']}" if r["packet_type"] in (43, 47) else "")].append(r)
    for key, rows in groups.items():
        with open(os.path.join(dest, "frames", "by_type", f"{key}.jsonl"), "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    rows = []  # (dest_rel, model, evidence, source_rel)
    for rel, target, why in VERIFIED:
        s = os.path.join(src, rel)
        if os.path.exists(s):
            copy(s, os.path.join(dest, "captures", "whoop5_verified", target))
            rows.append((f"captures/whoop5_verified/{target}", "5.0/MG", why, rel))

    models = json.load(open(models_path))
    excluded = []
    for rel, info in sorted(models.items()):
        s = os.path.join(src, "noop_attachments", rel)
        if not os.path.exists(s):
            continue
        if info["model"] == "4.0":
            excluded.append(f"noop_attachments/{rel}\t{info['why']}")
            continue
        bucket = "whoop5_verified" if info["model"] == "5.0" else "model_unverified"
        d = f"captures/{bucket}/noop_issue_attachments/{rel}"
        copy(s, os.path.join(dest, d))
        rows.append((d, "5.0/MG" if bucket == "whoop5_verified" else "unknown", info["why"] or "no model signal",
                     f"noop_attachments/{rel}"))

    with open(os.path.join(dest, "EXCLUDED_WHOOP4.txt"), "w") as f:
        f.write("# WHOOP 4.0 files found during collection and deliberately left out (source path, evidence)\n")
        f.writelines(line + "\n" for line in excluded)

    frames_per_source = collections.Counter()
    for r in recs:
        for s in r["sources"]:
            frames_per_source[s] += 1

    for d, model, _why, _s in rows:
        p = os.path.join(dest, d)
        files = [p] if os.path.isfile(p) else [os.path.join(a, n) for a, _, ns in os.walk(p) for n in ns]
        for fp in files:
            n = os.path.basename(fp)
            if GROUND_TRUTH.search(n) and n.lower().endswith((".csv", ".json")):
                tag = "verified" if model == "5.0/MG" else "unverified"
                label = os.path.relpath(fp, os.path.join(dest, "captures")).replace(os.sep, "__")
                shutil.copy(fp, os.path.join(dest, "ground_truth", f"{tag}__{label}"))

    with open(os.path.join(dest, "MANIFEST.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "model", "model_evidence", "source", "frames_5mg", "has_mac", "has_serial"])
        for d, model, why, s in rows:
            p = os.path.join(dest, d)
            files = [p] if os.path.isfile(p) else [os.path.join(a, n) for a, _, ns in os.walk(p) for n in ns]
            for fp in sorted(files):
                rel = os.path.relpath(fp, dest)
                src_rel = s if os.path.isfile(p) else os.path.join(s, os.path.relpath(fp, p))
                blob = open(fp, "rb").read()
                w.writerow([rel, model, why, src_rel, frames_per_source.get(src_rel, 0),
                            bool(MAC.search(blob)), bool(SERIAL.search(blob))])
    print(f"{len(recs)} frames; {len(rows)} copied entries; {len(excluded)} WHOOP 4.0 files excluded")


if __name__ == "__main__":
    main(*sys.argv[1:5])
