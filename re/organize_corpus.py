"""Arrange harvested WHOOP 5/MG data into a tidy local folder with a manifest.

Input:  the sources tree used by harvest_frames.py and its all_frames.jsonl.
Output: <dest>/frames/{all_frames.jsonl, by_type/*.jsonl}, <dest>/captures/..., <dest>/ground_truth/...,
        <dest>/MANIFEST.csv. Files are copied, never modified. The output is for local research:
        several sources carry no licence and some contain device identifiers, so do not republish it.

Usage: python re/organize_corpus.py <sources_dir> <all_frames.jsonl> <dest_dir>
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

# Hand-classified origins (repository or attachment folder prefix -> kind, note).
ORIGINS = {
    "noop1992_gists": ("real-capture", "ryanbr/noop#1992, @p3LZ3r: v20 history + 1 Hz HR/RR ground truth"),
    "noop_attachments": ("real-capture", "files attached to ryanbr/noop issues by strap owners"),
    "Asherlc_dofek": ("real-capture", "IMU activation session TSV (also vendored in Asherlc/whoop-ble-swift)"),
    "Asherlc_whoop-ble-swift": ("real-capture", "same TSV as Asherlc/dofek"),
    "tanarchytan_whoop-rs": ("real-capture", "real_frames.json: real v18/v26/events, no identifiers per its author"),
    "sennnen_maverick": ("mixed", "ECG MG 100 Hz CSV is a hardware capture; replay/records fixtures are synthetic"),
    "sennnen_maverick-connectors": ("test-vectors", "reference vectors"),
    "Sophonbot0_whoop-vault": ("real-capture", "event frames from WG50_r52 fw 50.38.1.0"),
}
COPY = [  # (source path relative to sources/, destination relative to captures/)
    ("noop1992_gists", "noop_issue_1992_v20_corpus"),
    ("noop_attachments", "noop_issue_attachments"),
    ("Asherlc_dofek/packages/mobile/modules/whoop-ble/Tests/fixtures/imu-activation-capture.tsv",
     "dofek_imu_activation_capture.tsv"),
    ("tanarchytan_whoop-rs/crates/whoop-protocol/tests/fixtures/real_frames.json", "whoop-rs_real_frames.json"),
    ("sennnen_maverick/fixtures/ecg/mg_electrode_100hz_v1.csv", "maverick_mg_ecg_100hz/mg_electrode_100hz_v1.csv"),
    ("sennnen_maverick/fixtures/ecg/mg_electrode_100hz_v1.expected.json",
     "maverick_mg_ecg_100hz/mg_electrode_100hz_v1.expected.json"),
    ("Sophonbot0_whoop-vault/ble/tests/fixtures/r52_frames.txt", "whoop-vault_wg50_r52_event_frames.txt"),
]
GROUND_TRUTH = re.compile(r"(whoop_days_shared|whoop_workouts_shared|sleep_debug|noop-raw-sensors|ground_truth|"
                          r"journal_entries|waveform\.csv)", re.I)


def ignore_git(_dir, names):
    return [n for n in names if n == ".git"]


def main(src: str, frames_path: str, dest: str) -> None:
    os.makedirs(os.path.join(dest, "frames", "by_type"), exist_ok=True)
    os.makedirs(os.path.join(dest, "captures"), exist_ok=True)
    os.makedirs(os.path.join(dest, "ground_truth"), exist_ok=True)

    recs = [json.loads(line) for line in open(frames_path)]
    shutil.copy(frames_path, os.path.join(dest, "frames", "all_frames.jsonl"))
    groups = collections.defaultdict(list)
    for r in recs:
        key = r["packet"] + (f"_L{r['layout']}" if r["packet_type"] in (43, 47) else "")
        groups[key].append(r)
    for key, rows in groups.items():
        with open(os.path.join(dest, "frames", "by_type", f"{key}.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    for rel, target in COPY:
        s, d = os.path.join(src, rel), os.path.join(dest, "captures", target)
        if not os.path.exists(s):
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True, ignore=ignore_git, symlinks=False)
        else:
            shutil.copy(s, d)

    for dirpath, dirnames, filenames in os.walk(os.path.join(dest, "captures")):
        dirnames[:] = [x for x in dirnames if x != ".git"]
        for n in filenames:
            if GROUND_TRUTH.search(n) and n.lower().endswith((".csv", ".json")):
                p = os.path.join(dirpath, n)
                label = os.path.relpath(p, os.path.join(dest, "captures")).replace(os.sep, "__")
                shutil.copy(p, os.path.join(dest, "ground_truth", label))

    per_file = collections.defaultdict(collections.Counter)
    for r in recs:
        for s in r["sources"]:
            per_file[s][r["packet"] + (f"/L{r['layout']}" if r["packet_type"] in (43, 47) else "")] += 1
    with open(os.path.join(dest, "MANIFEST.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_file", "origin", "kind", "frames", "frame_types", "has_mac", "has_serial", "note"])
        for path, counts in sorted(per_file.items(), key=lambda kv: -sum(kv[1].values())):
            origin = path.split("/")[0]
            kind, note = ORIGINS.get(origin, ("test-vectors", "frames embedded in source or tests"))
            try:
                blob = open(os.path.join(src, path), "rb").read()
            except OSError:
                blob = b""
            w.writerow([path, origin, kind, sum(counts.values()),
                        "; ".join(f"{k}={v}" for k, v in counts.most_common()),
                        bool(MAC.search(blob)), bool(SERIAL.search(blob)), note])
    print(f"{len(recs)} frames in {len(groups)} type files; manifest rows: {len(per_file)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
