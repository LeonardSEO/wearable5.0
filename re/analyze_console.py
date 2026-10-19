"""Reconstruct WHOOP 5/MG firmware console logs and inventory what the strap reports about itself.

Input: one or more frames.jsonl files from re/pklg_extract.py (frames in received order).
Console fragments (packet type 50) are joined in order into log lines; the line prefix
("<n>, <tick>: ") is stripped and messages are grouped into templates (numbers replaced by #).
Messages that echo device identifiers are not printed.

Usage: python re/analyze_console.py <frames.jsonl> [...]
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import console_text  # noqa: E402

KEYWORDS = ["spo2", "sleep", "temp", "hrv", "resp", "wear", "wrist", "battery", "optical", "imu", "ecg", "r22",
            "r20", "r21", "r26", "sigproc", "sync", "history", "trim", "page", "flash", "alarm", "haptic", "config"]
IDENTIFIER = re.compile(r"\b(?:5A[GM]|MGB|WG50)[0-9A-Z]{4,}|(?:[0-9A-F]{2}:){5}[0-9A-F]{2}|serial", re.I)


def lines(path):
    frames = [bytes.fromhex(json.loads(line)["hex"]) for line in open(path)]
    text = console_text([f for f in frames if f[8] == 50])
    for raw in text.split("\n"):
        msg = re.sub(r"^\s*\d+,\s*\d+:\s*", "", raw).strip()
        if msg:
            yield msg


def main(paths):
    templates = collections.Counter()
    total = 0
    for p in paths:
        for msg in lines(p):
            total += 1
            templates[re.sub(r"-?\d+(?:\.\d+)?", "#", msg)] += 1
    print(f"{total} console lines, {len(templates)} distinct templates\n")
    for kw in KEYWORDS:
        hits = [(t, n) for t, n in templates.items() if kw in t.lower() and not IDENTIFIER.search(t)]
        if not hits:
            continue
        print(f"== '{kw}': {sum(n for _, n in hits)} lines, {len(hits)} templates")
        for t, n in sorted(hits, key=lambda x: -x[1])[:8]:
            print(f"   {n:5d}  {t[:150]}")
    print("\n== most frequent templates")
    for t, n in templates.most_common(25):
        if not IDENTIFIER.search(t):
            print(f"   {n:5d}  {t[:150]}")


if __name__ == "__main__":
    main(sys.argv[1:])
