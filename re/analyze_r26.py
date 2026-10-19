"""R26 compact optical window: burst structure, delta-reconstruction continuity, and does a pulse-derived
HR track the strap's own R18 heart_rate?

Input: the local 5.0/MG-only corpus (whoop5-data/, never committed). Reads
  frames/by_type/HISTORICAL_DATA_L26.jsonl   R26: u32 base at frame offset 23, 24 i16 deltas from 27,
                                              burst_counter at 21 -> 25 cumulative samples per record
  frames/by_type/HISTORICAL_DATA_L18.jsonl   R18: heart_rate, the reference (independent of this decode)
  captures/whoop5_verified/whoop-rs_real_frames.gen5_only.json   ppg_frames + ppg_hr golden (whoop-rs)
captures/model_unverified/ is not read.

Assumptions (stated, not proven here): one R26 record covers one second at 25 samples/s (base + 24 deltas);
samples are an optical intensity where a pulse is an absorption dip, so the band-passed series is inverted
before peak picking. Section 2 tests the first assumption indirectly: if a record is exactly one second with
no gap, the next record's base sits one ordinary sample step after this record's last sample.

Guard against record-boundary artifacts (as in analyze_v20_optical.py): time-domain beat detection after a
0.6-3.3 Hz band-pass, scoring by correlation against a reference that moves, and two controls:
  record shuffle - permute whole records inside each burst (keeps every record's content, destroys continuity);
  burst shuffle  - pair each burst's estimate with another burst's reference (null distribution for r).

Usage (from the workspace root): .venv/bin/python -I wearable5.0/re/analyze_r26.py [whoop5-data]
Writes wearable5.0/re/results/r26_analysis.txt and prints the same text.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402

FS = 25.0
SESSION_GAP_S = 6 * 3600  # bursts further apart than this start a new session
CLIP = {32767, -32767, -32768}
SEED = 0


def source_of(entry):
    return entry["sources"][0].split("/")[0]


def load_r26(root):
    """Unique R26 records (by record_index) with their first-listed source repo."""
    recs = {}
    for line in open(os.path.join(root, "frames", "by_type", "HISTORICAL_DATA_L26.jsonl")):
        e = json.loads(line)
        d = decode_frame(bytes.fromhex(e["hex"]))
        if d.get("layout") != 26 or d.get("record") != "compact_optical_window":
            continue
        raw = bytes.fromhex(e["hex"])
        d["deltas"] = [int.from_bytes(raw[27 + 2 * i:29 + 2 * i], "little", signed=True) for i in range(24)]
        d["source"] = source_of(e)
        recs.setdefault(d["record_index"], d)
    return sorted(recs.values(), key=lambda d: (d["unix_s"], d["record_index"]))


def load_r18_hr(root, seconds):
    """R18 heart_rate at the given seconds; seconds with conflicting copies are dropped."""
    vals = defaultdict(set)
    for line in open(os.path.join(root, "frames", "by_type", "HISTORICAL_DATA_L18.jsonl")):
        e = json.loads(line)
        if e.get("unix_s") not in seconds:
            continue
        d = decode_frame(bytes.fromhex(e["hex"]))
        hr = d.get("heart_rate")
        if d.get("layout") == 18 and hr and 25 <= hr <= 230:
            vals[d["unix_s"]].add((hr, d.get("band_state")))
    return {t: next(iter(v)) for t, v in vals.items() if len(v) == 1}


def bursts_of(records):
    """Runs of consecutive seconds with the same burst_counter (a burst may be split over source repos)."""
    out, cur = [], []
    for r in records:
        if cur and not (r["unix_s"] == cur[-1]["unix_s"] + 1 and r["burst_counter"] == cur[-1]["burst_counter"]):
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def sessions_of(bursts):
    out, cur = [], []
    for b in bursts:
        if cur and b[0]["unix_s"] - cur[-1][-1]["unix_s"] > SESSION_GAP_S:
            out.append(cur)
            cur = []
        cur.append(b)
    if cur:
        out.append(cur)
    return out


def sources(s):
    c = Counter(r["source"] for b in s for r in b)
    return "+".join(f"{k}({v})" for k, v in sorted(c.items()))


def utc(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def series(recs):
    x = np.concatenate([np.asarray(r["samples"], float) for r in recs])
    ts = np.concatenate([r["unix_s"] + np.arange(len(r["samples"])) / FS for r in recs])
    return x, ts


def bandpass(x, lo=0.6, hi=3.3):
    b, a = butter(3, [lo / (FS / 2), hi / (FS / 2)], btype="band")
    return filtfilt(b, a, x - np.median(x))


def beats(x):
    y = -bandpass(x)
    peaks, _ = find_peaks(y, distance=int(FS * 0.33), prominence=0.3 * np.std(y))
    return peaks


def windowed_hr(ts, peaks, win=10.0, step=2.0):
    pt = ts[peaks]
    out, t = [], ts[0] + win
    while t <= ts[-1] + 1e-9:
        sel = pt[(pt > t - win) & (pt <= t)]
        ibi = np.diff(sel)
        ibi = ibi[(ibi > 0.3) & (ibi < 2.0)]
        if len(ibi) >= 3:
            out.append((t, 60.0 / float(np.median(ibi))))
        t += step
    return out


def burst_hr(recs):
    """(window estimates, whole-burst median-IBI HR) for one burst."""
    x, ts = series(recs)
    if len(x) < FS * 12:
        return [], None
    pk = beats(x)
    ibi = np.diff(ts[pk])
    ibi = ibi[(ibi > 0.3) & (ibi < 2.0)]
    whole = 60.0 / float(np.median(ibi)) if len(ibi) >= 5 else None
    return windowed_hr(ts, pk), whole


def ref_mean(ref, t0, t1):
    v = [ref[s][0] for s in range(int(np.floor(t0)), int(np.floor(t1)) + 1) if s in ref]
    return float(np.mean(v)) if len(v) >= max(3, 0.6 * (t1 - t0)) else None


def stats(pairs):
    if len(pairs) < 3:
        return None
    a, b = np.asarray(pairs, float).T
    r = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else float("nan")
    return {"n": len(pairs), "r": r, "mae": float(np.mean(np.abs(a - b))), "bias": float(np.mean(a - b)),
            "ref_lo": float(b.min()), "ref_hi": float(b.max())}


def fmt(s):
    if s is None:
        return "n<3, not scored"
    return (f"n={s['n']:4d}  r={s['r']:+.2f}  MAE={s['mae']:5.1f}  bias={s['bias']:+5.1f}  "
            f"ref {s['ref_lo']:.0f}-{s['ref_hi']:.0f} bpm")


def main(root):
    out = []
    p = out.append
    rng = np.random.default_rng(SEED)
    records = load_r26(root)
    bursts = bursts_of(records)
    sess = sessions_of(bursts)

    p("R26 compact optical window analysis (analyze_r26.py)")
    p(f"corpus: {len(records)} unique R26 records (by record_index), {len(bursts)} bursts, {len(sess)} sessions")
    p("assumed: 25 samples/s, 1 record = 1 s (base + 24 deltas), pulse = absorption dip")

    # 1. sessions and bursts
    p("\n1. Sessions and bursts (burst = consecutive seconds, same burst_counter)")
    for si, s in enumerate(sess):
        lens = [len(b) for b in s]
        gaps = [b[0]["unix_s"] - a[-1]["unix_s"] for a, b in zip(s, s[1:])]
        p(f"  S{si} {sources(s)}: start {utc(s[0][0]['unix_s'])} UTC, {len(s)} bursts, {sum(lens)} records, "
          f"burst_counter {s[0][0]['burst_counter']}..{s[-1][0]['burst_counter']}")
        p(f"      burst length s: min {min(lens)} median {int(np.median(lens))} max {max(lens)}"
          + (f"; gap between bursts s: median {int(np.median(gaps))} (min {min(gaps)}, max {max(gaps)})" if gaps else ""))
        steps = Counter(b[0]["burst_counter"] - a[0]["burst_counter"] for a, b in zip(s, s[1:]))
        if steps:
            p(f"      burst_counter step between bursts: {dict(sorted(steps.items()))}")
        flags = Counter((r["on_wrist_raw"], r["acceptance_raw"], r["status"]) for b in s for r in b)
        p("      (on_wrist_raw, acceptance_raw, status) counts: "
          + ", ".join(f"{k}x{v}" for k, v in sorted(flags.items())))
    same_counter_split = sum(1 for s in sess for a, b in zip(s, s[1:]) if a[0]["burst_counter"] == b[0]["burst_counter"])
    p(f"  bursts sharing a burst_counter with the previous burst in the same session (gap inside a burst): "
      f"{same_counter_split}")

    # 2. continuity
    p("\n2. Delta-reconstruction continuity (next record's base minus this record's last reconstructed sample)")
    all_d = np.concatenate([np.asarray(r["deltas"], float) for r in records])
    clipped = Counter(int(v) for v in all_d if int(v) in CLIP)
    recs_clipped = sum(1 for r in records if any(v in CLIP for v in r["deltas"]))
    p(f"  deltas: {len(all_d)}, clipped (+32767/-32767/-32768): {sum(clipped.values())} {dict(sorted(clipped.items()))} "
      f"in {recs_clipped} records")
    p(f"  |delta| inside records: median {np.median(np.abs(all_d)):.0f}, p90 {np.percentile(np.abs(all_d), 90):.0f}, "
      f"p99 {np.percentile(np.abs(all_d), 99):.0f}")
    jumps, by_sess = [], defaultdict(list)
    for si, s in enumerate(sess):
        for b in s:
            for a, c in zip(b, b[1:]):
                j = c["base"] - a["samples"][-1]
                jumps.append(j)
                by_sess[si].append(j)
    jumps = np.asarray(jumps, float)
    if len(jumps):
        p(f"  boundary step within bursts: n={len(jumps)}, |step| median {np.median(np.abs(jumps)):.0f}, "
          f"p90 {np.percentile(np.abs(jumps), 90):.0f}, max {np.max(np.abs(jumps)):.0f}")
        # extrapolation check: does the next base continue the local slope (one extra 1/25 s step)?
        pred_err = []
        for s in sess:
            for b in s:
                for a, c in zip(b, b[1:]):
                    slope = a["samples"][-1] - a["samples"][-2]
                    pred_err.append(c["base"] - (a["samples"][-1] + slope))
        pe = np.abs(np.asarray(pred_err, float))
        p(f"  next base vs linear extrapolation of the last step: |error| median {np.median(pe):.0f}, "
          f"p90 {np.percentile(pe, 90):.0f}")
        # control: same records, boundaries between non-adjacent seconds in the same burst
        ctrl = []
        for s in sess:
            for b in s:
                if len(b) < 3:
                    continue
                for _ in range(len(b) - 1):
                    i, k = rng.choice(len(b), 2, replace=False)
                    if abs(int(i) - int(k)) > 1:
                        ctrl.append(b[k]["base"] - b[i]["samples"][-1])
        ctrl = np.abs(np.asarray(ctrl, float))
        p(f"  control (non-adjacent records in same burst): |step| median {np.median(ctrl):.0f}, "
          f"p90 {np.percentile(ctrl, 90):.0f}")
        ratio = np.median(np.abs(jumps)) / max(np.median(np.abs(all_d)), 1)
        p(f"  verdict: adjacent boundary step is {ratio:.1f}x the median in-record step and "
          f"{np.median(ctrl) / max(np.median(np.abs(jumps)), 1):.0f}x smaller than the control -> "
          + ("records are contiguous at 25 samples/s (no dropped sample at the boundary)"
             if ratio < 2.5 and np.median(ctrl) > 3 * np.median(np.abs(jumps)) else "continuity NOT established"))
    big = [(si, int(j)) for si, js in by_sess.items() for j in js if abs(j) > 32767]
    p(f"  boundary steps beyond i16 range (would need >1 clipped delta): {len(big)}")

    # 3. HR vs R18
    p("\n3. HR from R26 vs R18 heart_rate at the same seconds")
    p("   method: per burst, 0.6-3.3 Hz Butterworth(3) filtfilt, invert, find_peaks(distance 0.33 s, prominence 0.3 sd);")
    p("   window HR = 60/median IBI over 10 s windows every 2 s (IBI 0.3-2.0 s, >=3 IBIs); burst HR = median IBI of")
    p("   the whole burst; reference = mean R18 heart_rate over the same seconds (>=60% coverage).")
    ref = load_r18_hr(root, {r["unix_s"] for r in records})
    p(f"   R18 seconds overlapping R26: {len(ref)} of {len(records)} "
      f"(band_state: {dict(sorted(Counter(v[1] for v in ref.values()).items()))})")
    pooled_w, pooled_b, pooled_rs, burst_rows = [], [], [], []
    for si, s in enumerate(sess):
        win_pairs, b_pairs, rs_pairs = [], [], []
        for b in s:
            est, whole = burst_hr(b)
            t0, t1 = b[0]["unix_s"], b[-1]["unix_s"] + 1
            for t, h in est:
                m = ref_mean(ref, t - 10, t - 1e-6)
                if m is not None:
                    win_pairs.append((h, m))
            m = ref_mean(ref, t0, t1 - 1e-6)
            if whole is not None and m is not None:
                b_pairs.append((whole, m))
                burst_rows.append((si, len(b), whole, m))
                # record-shuffle control on the same burst
                order = rng.permutation(len(b))
                _, wc = burst_hr([b[i] for i in order])
                if wc is not None:
                    rs_pairs.append((wc, m))
        n_ref = sum(1 for b in s for r in b if r["unix_s"] in ref)
        p(f"  S{si} {sources(s)}: {n_ref} R26 seconds with R18 HR")
        if n_ref == 0:
            p("      no R18 reference in this session -> not scored")
            continue
        p(f"      windows          {fmt(stats(win_pairs))}")
        p(f"      bursts           {fmt(stats(b_pairs))}")
        p(f"      record-shuffled  {fmt(stats(rs_pairs))}")
        pooled_w += win_pairs
        pooled_b += b_pairs
        pooled_rs += rs_pairs
    sb = stats(pooled_b)
    p("  pooled:")
    p(f"      windows          {fmt(stats(pooled_w))}  (windows overlap; not independent)")
    p(f"      bursts           {fmt(sb)}")
    p(f"      record-shuffled  {fmt(stats(pooled_rs))}")
    p("      (record shuffle keeps ~1 s of pulse per record, so some rank order can survive; the HR level does not.")
    p("       A boundary artifact would pin HR near 60 bpm regardless of the reference.)")
    if sb is not None and sb["n"] >= 3:
        a, bref = np.asarray(pooled_b, float).T
        null = []
        for _ in range(2000):
            perm = rng.permutation(len(bref))
            if np.std(a) > 0:
                null.append(np.corrcoef(a, bref[perm])[0, 1])
        null = np.asarray(null)
        pval = float(np.mean(null >= sb["r"]))
        null_mae = float(np.mean([np.mean(np.abs(a - bref[rng.permutation(len(bref))])) for _ in range(2000)]))
        p(f"      burst-shuffled   r null 95th pct {np.percentile(null, 95):+.2f}, one-sided p(r_null >= r) = {pval:.3f}, "
          f"mean MAE {null_mae:.1f}")
    p("  per burst (session, seconds, R26 burst HR, R18 mean HR):")
    for si, n, h, m in burst_rows:
        p(f"      S{si} {n:3d}s  {h:6.1f}  {m:6.1f}  diff {h - m:+5.1f}")
    fair = sb is not None and sb["n"] >= 10 and (sb["ref_hi"] - sb["ref_lo"]) >= 10
    p("  fairness: " + (f"{sb['n']} bursts spanning {sb['ref_hi'] - sb['ref_lo']:.0f} bpm of reference -> scoreable"
                        if fair else "too few bursts or too little reference variation for a fair correlation score;"
                        " read MAE only, r is not evidence"))

    # 4. whoop-rs golden
    p("\n4. whoop-rs ppg_hr golden (whoop-rs_real_frames.gen5_only.json)")
    g = json.load(open(os.path.join(root, "captures", "whoop5_verified", "whoop-rs_real_frames.gen5_only.json")))
    gold = g["ppg_hr"]
    gf = [decode_frame(bytes.fromhex(f["hex"])) for f in g["ppg_frames"]]
    gf.sort(key=lambda d: d["unix_s"])
    consec = all(b["unix_s"] == a["unix_s"] + 1 for a, b in zip(gf, gf[1:]))
    p(f"  ppg_frames: {len(gf)}, consecutive seconds: {consec}, burst_counter {sorted({d['burst_counter'] for d in gf})}")
    match = mism = 0
    for f in g["ppg_frames"]:
        if "samples" in f:
            raw = bytes.fromhex(f["hex"])
            ours = [int.from_bytes(raw[27 + 2 * i:29 + 2 * i], "little", signed=True) for i in range(24)]
            match, mism = (match + 1, mism) if ours == f["samples"] else (match, mism + 1)
    p(f"  frames with pinned 'samples': {match + mism}; equal to our 24 raw deltas: {match} (whoop-rs pins the deltas,"
      " not the cumulative samples)")
    in_corpus = sum(1 for d in gf if any(r["record_index"] == d["record_index"] and r["unix_s"] == d["unix_s"]
                                         for r in records))
    p(f"  golden frames also in the L26 corpus: {in_corpus}; R18 reference at those seconds: "
      f"{sum(1 for d in gf if d['unix_s'] in ref)}")
    est, whole = burst_hr(gf)
    first = gold["first"]
    first_ours = next((h for t, h in est), None)
    p(f"  golden: {gold['estimate_count']} estimates, first ts {first['ts']} bpm {first['bpm']} conf {first['conf']}, "
      f"confident range {gold['confident_bpm_range']}")
    p(f"  ours:   {len(est)} window estimates, first (window ending {est[0][0] - gf[0]['unix_s']:.0f} s in) "
      f"{first_ours:.1f} bpm; burst HR {whole:.1f} bpm; window range {min(h for _, h in est):.1f}-"
      f"{max(h for _, h in est):.1f}" if est else "  ours:   no estimate")
    if est:
        lo, hi = gold["confident_bpm_range"]
        inside = sum(1 for _, h in est if lo <= h <= hi)
        p(f"  ours inside golden confident range: {inside}/{len(est)}; |first ours - golden first| "
          f"{abs(first_ours - first['bpm']):.1f} bpm")
    p("  note: whoop-rs uses a different estimator (autocorrelation lag, parabolic refinement) and its golden is a")
    p("  regression anchor, not a reference measurement; agreement is consistency, not validation.")

    text = "\n".join(out) + "\n"
    dst = os.path.join(HERE, "results", "r26_analysis.txt")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w") as fh:
        fh.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "whoop5-data"))
