"""R20 block configuration per session, and the bursts in which blocks 1 and 2 carry samples.

analyze_v20_optical.py found that blocks 0 and 4 carry the pulse, block 3 is dark, and blocks 1/2
(the highest LED drives) were populated in only one 21-second stretch of one recording. This script
checks that pattern across every 5/MG R20 session in the local corpus. It describes what is observed:
configuration, burst timing and per-channel perfusion. It does not estimate SpO2 and does not assign
wavelengths to sources.

Input: whoop5-data/frames/by_type/HISTORICAL_DATA_L20.jsonl (see whoop5-data/README.md). A frame is
kept only when at least one of its sources is listed in whoop5-data/MANIFEST.csv under
captures/whoop5_verified/ with model 5.0/MG; frames seen only in model_unverified captures or in
repository test fixtures are dropped and counted.

Usage (from the workspace root):
  .venv/bin/python -I wearable5.0/re/analyze_r20_config.py [corpus_dir] [output_txt]
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from scipy.signal import butter, filtfilt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402

FS = 25.0
SESSION_GAP_S = 60
BURST_BLOCKS = (1, 2)
CFG_KEYS = ("source", "drive", "detector", "range", "offset")


def verified_sources(corpus):
    ok = set()
    for row in csv.DictReader(open(os.path.join(corpus, "MANIFEST.csv"))):
        if row["path"].startswith("captures/whoop5_verified/") and row["model"] == "5.0/MG":
            ok.add(row["source"])
    return ok


def load_records(corpus):
    ok = verified_sources(corpus)
    lines = [json.loads(l) for l in open(os.path.join(corpus, "frames", "by_type", "HISTORICAL_DATA_L20.jsonl"))]
    kept, dropped = [], Counter()
    for f in lines:
        if not any(s in ok for s in f["sources"]):
            dropped[f["sources"][0].split("/")[0]] += 1
            continue
        d = decode_frame(bytes.fromhex(f["hex"]))
        if d.get("layout") != 20:
            dropped["not_layout_20"] += 1
            continue
        d["_sha1"] = f["sha1"]
        d["_origin"] = sorted({s.rsplit("/", 1)[0] for s in f["sources"] if s in ok})
        kept.append(d)
    kept.sort(key=lambda d: (d["unix_s"], d["record_index"], d["_sha1"]))
    return kept, len(lines), dropped


def sessions(records):
    """Split on gaps > SESSION_GAP_S, then keep the first copy of each record_index within a session."""
    out, cur = [], []
    for r in records:
        if cur and r["unix_s"] - cur[-1]["unix_s"] > SESSION_GAP_S:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    deduped = []
    for s in out:
        seen, uniq = set(), []
        for r in s:
            if r["record_index"] not in seen:
                seen.add(r["record_index"])
                uniq.append(r)
        deduped.append((uniq, len(s) - len(uniq)))
    return deduped


def utc(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def block_cfg(b, slot):
    return tuple(b[f"{k}_{slot}"] for k in CFG_KEYS)


def fmt_cfg(c):
    return " ".join(f"{k[:3]}={v}" for k, v in zip(CFG_KEYS, c))


def bursts(sess, bi):
    """Runs of records, consecutive in unix_s, in which block `bi` has count > 0."""
    out, cur = [], []
    for r in sess:
        if r["blocks"][bi]["count"] > 0 and (not cur or r["unix_s"] == cur[-1]["unix_s"] + 1):
            cur.append(r)
        elif r["blocks"][bi]["count"] > 0:
            out.append(cur)
            cur = [r]
        else:
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def bandpass(x, lo=0.6, hi=3.3):
    b, a = butter(3, [lo / (FS / 2), hi / (FS / 2)], btype="band")
    return filtfilt(b, a, x - np.median(x))


def perfusion(run, bi, slot):
    x = np.asarray([v for r in run for v in r["blocks"][bi]["slot_a" if slot == "A" else "slot_b"]], float)
    if len(x) < 4 * FS or np.ptp(x) == 0:
        return None
    dc = float(np.median(x))
    if dc == 0:
        return None
    return len(x), dc, float(np.std(bandpass(x))) / abs(dc)


def report(corpus):
    records, n_lines, dropped = load_records(corpus)
    sess = sessions(records)
    L = []
    p = L.append
    p("R20 block configuration and block 1/2 bursts per session")
    p("=" * 60)
    p(f"input frames: {n_lines}; kept (5/MG verified captures): {len(records)}; "
      f"dropped: {dict(sorted(dropped.items())) or 'none'}")
    p(f"sessions (split on gaps > {SESSION_GAP_S} s, record_index de-duplicated within a session): {len(sess)}")
    p("Times are UTC from the record header; the wearer's local time zone is not known.")
    p("Observations only: no SpO2 value and no wavelength identity is inferred from source numbers or drives.")

    all_cfgs = {}
    summary = []
    for si, (s, ndup) in enumerate(sess, 1):
        t0, t1 = s[0]["unix_s"], s[-1]["unix_s"]
        gaps = sum(1 for a, b in zip(s, s[1:]) if b["unix_s"] - a["unix_s"] > 1)
        origins = sorted({o for r in s for o in r["_origin"]})
        p("")
        p(f"Session {si}: {utc(t0)} .. {utc(t1)} UTC  span {t1 - t0 + 1} s  records {len(s)} "
          f"(coverage {100 * len(s) / (t1 - t0 + 1):.0f}%, duplicates dropped {ndup}, internal gaps >1 s: {gaps})")
        for o in origins:
            p(f"  source: {o}")

        p("  Block configuration (slot A | slot B), records with samples (count>0) / without:")
        sess_cfg = {}
        for bi in range(5):
            cfg = Counter()
            for r in s:
                b = r["blocks"][bi]
                cfg[(block_cfg(b, "a"), block_cfg(b, "b"), b["count"] > 0)] += 1
            keys = sorted({(a, b_) for a, b_, _ in cfg})
            sess_cfg[bi] = tuple(keys)
            for a, b_ in keys:
                on, off = cfg[(a, b_, True)], cfg[(a, b_, False)]
                p(f"    block {bi}: A({fmt_cfg(a)}) | B({fmt_cfg(b_)})  with samples {on} / without {off}")
            counts = Counter(r["blocks"][bi]["count"] for r in s)
            p(f"             count values: {dict(sorted(counts.items()))}")
        all_cfgs[si] = sess_cfg

        sess_bursts = {}
        for bi in BURST_BLOCKS:
            bl = bursts(s, bi)
            sess_bursts[bi] = bl
            p(f"  Block {bi} bursts: {len(bl)}")
            prev = None
            for k, run in enumerate(bl, 1):
                st, en = run[0]["unix_s"], run[-1]["unix_s"]
                n = sum(r["blocks"][bi]["count"] for r in run)
                iv = f"{st - prev:6d} s" if prev is not None else "     -  "
                pos = s.index(run[0])
                edge = []
                if pos == 0 or st - s[pos - 1]["unix_s"] > 1:
                    edge.append("start at session start/gap")
                end = pos + len(run)
                if end == len(s) or s[end]["unix_s"] - en > 1:
                    edge.append("end at session end/gap")
                p(f"    #{k:<3d} start {utc(st)}  duration {en - st + 1:4d} s  interval since prev start {iv}  "
                  f"samples/slot {n}" + (f"  [possibly truncated: {', '.join(edge)}]" if edge else ""))
                prev = st
        same = [(a[0]["unix_s"], a[-1]["unix_s"]) for a in sess_bursts[1]] == \
               [(a[0]["unix_s"], a[-1]["unix_s"]) for a in sess_bursts[2]]
        p(f"  Blocks 1 and 2 bursts coincide exactly: {'yes' if same else 'no'}")

        runs = sess_bursts[1] if sess_bursts[1] else sess_bursts[2]
        if runs:
            p("  Perfusion during bursts (AC = std after 0.6-3.3 Hz band-pass, DC = median), "
              "sample-weighted over bursts:")
            p("    chan   samples   DC            AC/DC")
            for bi in range(5):
                for slot in "AB":
                    rows = [x for x in (perfusion(run, bi, slot) for run in runs) if x]
                    if not rows:
                        p(f"    {bi}{slot}     {'-':>7}   (flat, zero DC or < 4 s of samples)")
                        continue
                    w = np.array([r[0] for r in rows], float)
                    dc = float(np.average([r[1] for r in rows], weights=w))
                    pi = float(np.average([r[2] for r in rows], weights=w))
                    p(f"    {bi}{slot}    {int(w.sum()):7d}   {dc:12.0f}  {pi:9.5f}")

        durs = [r[-1]["unix_s"] - r[0]["unix_s"] + 1 for r in sess_bursts[1]]
        starts = [r[0]["unix_s"] for r in sess_bursts[1]]
        summary.append((si, t1 - t0 + 1, len(s), len(sess_bursts[1]), len(sess_bursts[2]), durs,
                        list(np.diff(starts)) if len(starts) > 1 else [],
                        [datetime.fromtimestamp(t, timezone.utc).hour for t in starts]))

    p("")
    p("Summary")
    p("-" * 60)
    p("  sess  span_s  records  b1_bursts  b2_bursts  b1 durations (s)  b1 start-to-start intervals (s)  b1 UTC hours")
    for si, span, n, nb1, nb2, durs, ivs, hrs in summary:
        p(f"  {si:4d}  {span:6d}  {n:7d}  {nb1:9d}  {nb2:9d}  {durs}  {[int(v) for v in ivs]}  {hrs}")
    all_d = [d for row in summary for d in row[5]]
    all_i = [int(v) for row in summary for v in row[6]]
    if all_d:
        p(f"  all block-1 bursts: n={len(all_d)} duration median {np.median(all_d):.0f} s "
          f"(min {min(all_d)}, max {max(all_d)})")
    if all_i:
        p(f"  start-to-start interval median {np.median(all_i):.0f} s (min {min(all_i)}, max {max(all_i)}), "
          f"within-session only")
    distinct = Counter(tuple(sorted(c.items())) for c in all_cfgs.values())
    p(f"  distinct per-session block configurations (source/drive/detector/range/offset, both slots, "
      f"all 5 blocks): {len(distinct)}")
    if len(distinct) > 1:
        base = all_cfgs[1]
        for si, c in all_cfgs.items():
            diff = [bi for bi in range(5) if c[bi] != base[bi]]
            p(f"    session {si}: blocks differing from session 1: {diff or 'none'}")
    return "\n".join(L) + "\n"


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    corpus = argv[0] if argv else os.path.join(here, "..", "..", "whoop5-data")
    out = argv[1] if len(argv) > 1 else os.path.join(here, "results", "r20_config_bursts.txt")
    text = report(corpus)
    with open(out, "w") as fh:
        fh.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main(sys.argv[1:])
