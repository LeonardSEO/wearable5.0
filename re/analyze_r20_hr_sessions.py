"""R20 optical heart rate across independent sessions, each with its own reference.

Session A: ryanbr/noop#1992 corpus, reference = the strap's banked 1 Hz HR (ground_truth_window.csv).
Session B: ryanbr/noop#26 attachment, reference = the strap's live HR notifications in the NOOP strap log
           ("[hh:mm:ss] HR notify: N bpm"), converted to UTC with the time zone the log itself states.
Method and shuffled-record control are those of analyze_v20_optical.py (time-domain beats, 10 s windows).

Usage: python re/analyze_r20_hr_sessions.py <whoop5-data dir>
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from analyze_v20_optical import beats, channel_series, load_reference, score, segments, windowed_hr  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402

CHANNELS = [(0, "A"), (0, "B"), (4, "A"), (4, "B")]


def r20_from_corpus(root: str, source_prefix: str):
    by_index = {}
    for line in open(os.path.join(root, "frames", "by_type", "HISTORICAL_DATA_L20.jsonl")):
        r = json.loads(line)
        if any(s.startswith(source_prefix) for s in r["sources"]):
            d = decode_frame(bytes.fromhex(r["hex"]))
            if d.get("record") == "optical_blocks":
                by_index.setdefault(d["record_index"], d)
    return [by_index[k] for k in sorted(by_index)]


def notify_reference(log_paths):
    ref = {}
    for p in log_paths:
        text = open(p, errors="replace").read()
        tz = re.search(r"Timezone:\s+\S+ \(UTC([+-]\d+):(\d+)\)", text)
        date = re.search(r"strap-log-(\d{2})(\d{2})(\d{2})-", os.path.basename(p)) or \
            re.search(r"-(\d{2})(\d{2})(\d{2})-\d{4}", p)
        if not tz or not date:
            continue
        offset = dt.timedelta(hours=int(tz.group(1)), minutes=int(tz.group(2)) * (1 if tz.group(1)[0] != "-" else -1))
        day = dt.date(2000 + int(date.group(1)), int(date.group(2)), int(date.group(3)))
        for m in re.finditer(r"^\[(\d\d):(\d\d):(\d\d)\] HR notify: (\d+) bpm", text, re.M):
            local = dt.datetime.combine(day, dt.time(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            ref[int((local - offset).replace(tzinfo=dt.timezone.utc).timestamp())] = int(m.group(4))
    return ref


def nearest(ref, tolerance=15):
    keys = np.array(sorted(ref))

    def get(t):
        i = np.searchsorted(keys, t)
        best = [k for k in keys[max(0, i - 1):i + 1] if abs(k - t) <= tolerance]
        return ref[min(best, key=lambda k: abs(k - t))] if best else None
    return get


def run(name, records, ref, ref_lookup=None):
    rng = np.random.default_rng(0)
    print(f"== {name}: {len(records)} R20 records, {len(ref)} reference samples")
    for bi, slot in CHANNELS:
        ests, ctrls = [], []
        for seg in segments(records):
            if len(seg) < 60:
                continue
            x, ts = channel_series(seg, bi, slot)
            ests += windowed_hr(ts, beats(x), ts[0], ts[-1])
            order = rng.permutation(len(seg))
            xc, _ = channel_series([seg[i] for i in order], bi, slot)
            ctrls += windowed_hr(ts, beats(xc), ts[0], ts[-1])
        if ref_lookup:
            lookup = {t: ref_lookup(t) for t, _ in ests + ctrls}
            ref_used = {t: v for t, v in lookup.items() if v is not None}
        else:
            ref_used = ref
        s, c = score(ests, ref_used), score(ctrls, ref_used)
        if s:
            print(f"   {bi}{slot}: n={s['n']:4d} r={s['pearson_r']:+.2f} MAE={s['mae_bpm']:4.1f} ref {s['ref_range']}"
                  f" | control r={c['pearson_r'] if c else float('nan'):+.2f} MAE={c['mae_bpm'] if c else float('nan'):4.1f}")
        else:
            print(f"   {bi}{slot}: too little overlap with the reference to score")


def main(root):
    a = r20_from_corpus(root, "noop1992_gists")
    gt = glob.glob(os.path.join(root, "captures", "whoop5_verified", "noop_issue_1992_v20_corpus", "*", "ground_truth_window.csv"))
    run("session A (noop#1992, banked 1 Hz HR)", a, load_reference(gt[0]))
    b = r20_from_corpus(root, "noop_attachments/issue_26")
    logs = glob.glob(os.path.join(root, "captures", "whoop5_verified", "noop_issue_attachments", "issue_26", "**", "*.txt"),
                     recursive=True)
    ref_b = notify_reference(logs)
    run("session B (noop#26, live HR notifications, 30 s cadence)", b, ref_b, nearest(ref_b))


if __name__ == "__main__":
    main(sys.argv[1])
