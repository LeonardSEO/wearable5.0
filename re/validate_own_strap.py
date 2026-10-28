"""Validate wearable5.0's open claims on one owner's WHOOP 5.0 / MG data, with criteria fixed in advance.

Drop everything in one folder, as often as you like; the script reads all of it, de-duplicates frames and
re-runs every check over the whole collection:
  - NOOP snapshots made by re/export_noop_db.py (`frames.jsonl`)
  - HCI captures of the official app syncing: iOS PacketLogger `.pklg`, Android `btsnoop_hci.log`
  - the WHOOP data export (`physiological_cycles.csv`, or the .zip from app.whoop.com)

Each check prints PASS / FAIL / WAITING (not enough data yet) against the thresholds in CRITERIA, which are
fixed here before the data arrives so a result cannot be tuned after the fact. The bar is one device and at
least MIN_NIGHTS paired nights: the evidence of this owner's strap, nothing else.

Checks:
  decoder          every frame decodes; no unknown layouts or lengths (all frames)
  rr_unit          R18 R-R is milliseconds: median HR x mean(R-R) / 60000 is ~1 (asleep records)
  r26_hr           heart rate from the R26 25 Hz waveform tracks R18 heart rate; a time-shuffle control fails
  r21_scale        R21 accel is 4096 LSB/g: at rest |a| / 4096 is ~1 g (README H5)
  sleep_onset/wake sleep period from the R18 band state vs WHOOP's sleep onset / wake onset (D3)
  spo2             nightly mean of the R18 byte-82 window medians vs WHOOP blood oxygen (D2)
  spo2_byte_82     no other R18 byte tracks WHOOP blood oxygen better (needs frames from sleep; D8)
  resp_rate        respiratory rate from R-R sinus arrhythmia vs WHOOP respiratory rate (D6)
  resting_hr       lowest 5-minute mean HR in the sleep period vs WHOOP resting heart rate
  hrv              median 5-minute RMSSD in the sleep period vs WHOOP HRV (trend; D5)
  skin_temp        nightly mean R18 skin temperature vs WHOOP skin temperature (trend; D7)
  inventory        layouts, R22 presence, event numbers seen (D9, D10; informational)

Usage (workspace root):
  .venv/bin/python -I wearable5.0/re/validate_own_strap.py whoop5-data/own_strap
Writes <folder>/REPORT.md and <folder>/report.json (personal values: they stay in the data folder).
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import hashlib
import io
import json
import math
import os
import random
import sys
import zipfile
from collections import Counter, defaultdict
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
sys.path.insert(0, HERE)
from whoop5.decode import decode_frame  # noqa: E402
from whoop5.experimental import (hr_from_r26, respiratory_rate, rmssd_ms, sleep_periods,  # noqa: E402
                                 spo2_windows)

MIN_NIGHTS = 5
# Fixed before the data: (metric, comparison, threshold). r = Pearson over paired nights, mae = mean |ours - WHOOP|.
CRITERIA = {
    "rr_unit": ("median_ratio", "within", (0.98, 1.02)),
    "r26_hr": ("mae_bpm", "<=", 3.0),
    "r21_scale": ("median_g", "within", (0.95, 1.05)),
    "sleep_onset": ("median_abs_min", "<=", 15.0),
    "sleep_wake": ("median_abs_min", "<=", 15.0),
    "spo2": ("mae_pct", "<=", 1.0),
    "resp_rate": ("mae_rpm", "<=", 1.0),
    "resting_hr": ("mae_bpm", "<=", 3.0),
    "hrv": ("r", ">=", 0.7),
    "skin_temp": ("r", ">=", 0.7),
}
# Where WHOOP's own nightly values vary enough, the trend must also follow: r >= 0.7 (as NOOP's #103 gate).
TREND_R, TREND_MIN_SPREAD = 0.7, {"spo2": 1.0, "resp_rate": 1.0, "resting_hr": 3.0}
R18_LEN = 124


# ---------------------------------------------------------------- loading

def frames_in(folder: str):
    """Yield raw frames from every supported file below `folder`."""
    for path in sorted(glob.glob(os.path.join(folder, "**", "*"), recursive=True)):
        name = os.path.basename(path).lower()
        if name.endswith(".jsonl"):
            for line in open(path):
                if '"hex"' in line or '"frameHex"' in line:
                    obj = json.loads(line)
                    yield bytes.fromhex(obj.get("hex") or obj["frameHex"])
        elif name.endswith(".pklg") or name.startswith("btsnoop"):
            from pklg_extract import whoop_frames
            for _ts, _direction, _handle, f in whoop_frames(open(path, "rb").read()):
                yield f


def load(folder: str) -> dict:
    seen, d = set(), {"r18": {}, "r18_raw": {}, "r26": {}, "r21_g": [], "kinds": Counter(), "events": Counter(),
                      "undecodable": 0, "odd_length": Counter()}
    for f in frames_in(folder):
        h = hashlib.sha1(f).digest()
        if h in seen:
            continue
        seen.add(h)
        try:
            r = decode_frame(f)
        except Exception:
            d["undecodable"] += 1
            continue
        lay = r.get("layout")
        d["kinds"][f"R{lay}" if lay is not None else r.get("packet", "?")] += 1
        if r.get("error"):
            d["odd_length"][f"R{lay}"] += 1
        if r.get("packet") == "EVENT":
            d["events"][r.get("event_name", r.get("event"))] += 1
        if lay == 18 and r.get("record") == "biometric_summary":
            d["r18"].setdefault(r["unix_s"], r)
            d["r18_raw"].setdefault(r["unix_s"], f)
            if len(f) != R18_LEN:
                d["odd_length"]["R18"] += 1
        elif lay == 26 and r.get("record") == "compact_optical_window":
            d["r26"].setdefault(r["record_index"], r)
        elif lay == 21 and r.get("accel_count"):
            ax, ay, az = (sum(r[f"accel_{k}"]) / r["accel_count"] for k in "xyz")
            d["r21_g"].append((r["unix_s"], math.sqrt(ax * ax + ay * ay + az * az) / 4096))
    d["frames"] = len(seen)
    return d


def _parse_time(text: str, tz: str | None) -> int | None:
    if not text:
        return None
    t = dt.datetime.fromisoformat(text.strip().replace("T", " ")[:19])
    if t.tzinfo is None:
        off = dt.timedelta(0)
        if tz and tz.upper().startswith("UTC") and len(tz) > 3:
            sign = -1 if tz[3] == "-" else 1
            hh, _, mm = tz[4:].partition(":")
            off = sign * dt.timedelta(hours=int(hh), minutes=int(mm or 0))
        else:  # no zone column: assume this machine's zone, which is where the export was made
            return int(t.timestamp())
        t = t.replace(tzinfo=dt.timezone(off))
    return int(t.timestamp())


def _col(row: dict, *prefixes: str):
    for k, v in row.items():
        if k and any(k.strip().lower().startswith(p) for p in prefixes):
            return v
    return None


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def load_export(folder: str) -> list[dict]:
    """WHOOP nights from physiological_cycles.csv (loose files or inside an export .zip)."""
    texts = []
    for path in glob.glob(os.path.join(folder, "**", "*"), recursive=True):
        name = os.path.basename(path).lower()
        if name == "physiological_cycles.csv":
            texts.append(open(path, encoding="utf-8-sig").read())
        elif name.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                texts += [z.read(n).decode("utf-8-sig") for n in z.namelist()
                          if os.path.basename(n).lower() == "physiological_cycles.csv"]
    nights = {}
    for text in texts:
        for row in csv.DictReader(io.StringIO(text)):
            tz = _col(row, "cycle timezone")
            onset = _parse_time(_col(row, "sleep onset") or "", tz)
            if onset is None:
                continue
            nights[onset] = {
                "onset": onset, "wake": _parse_time(_col(row, "wake onset") or "", tz),
                "spo2": _num(_col(row, "blood oxygen")), "resp_rate": _num(_col(row, "respiratory rate")),
                "resting_hr": _num(_col(row, "resting heart rate")),
                "hrv": _num(_col(row, "heart rate variability")), "skin_temp": _num(_col(row, "skin temp"))}
    return sorted(nights.values(), key=lambda n: n["onset"])


# ---------------------------------------------------------------- per-night metrics

def night_metrics(r18: list[dict]) -> list[dict]:
    out = []
    for p in sleep_periods(r18):
        inside = [r for r in r18 if p["onset_unix"] <= r["unix_s"] <= p["offset_unix"]]
        win = [w["spo2_percent"] for w in spo2_windows(inside) if w["spo2_percent"] is not None]
        rr = [x for r in inside for x in (r.get("rr_ms") or [])]
        rates = [w["breaths_per_min"] for w in respiratory_rate(rr) if w["breaths_per_min"] is not None]
        by5 = defaultdict(list)
        for r in inside:
            by5[(r["unix_s"] - p["onset_unix"]) // 300].append(r)
        hr5 = [sum(h) / len(h) for b in by5.values()
               if len(h := [r["heart_rate"] for r in b if 25 <= (r.get("heart_rate") or 0) <= 230]) >= 150]
        rm5 = [v for b in by5.values() if (v := rmssd_ms([x for r in b for x in (r.get("rr_ms") or [])])) is not None]
        temps = [r["skin_temp_c"] for r in inside if r.get("skin_temp_c")]
        out.append({"onset": p["onset_unix"], "wake": p["offset_unix"], "hours": round(p["duration_s"] / 3600, 2),
                    "spo2": sum(win) / len(win) if win else None, "spo2_windows": len(win),
                    "resp_rate": median(rates) if rates else None, "resting_hr": min(hr5) if hr5 else None,
                    "hrv": median(rm5) if rm5 else None, "skin_temp": sum(temps) / len(temps) if temps else None})
    return out


def pair(ours: list[dict], whoop: list[dict], max_gap_s: int = 3 * 3600) -> list[tuple[dict, dict]]:
    """Each WHOOP night matched to our sleep period with the nearest onset, within `max_gap_s`."""
    pairs = []
    for w in whoop:
        best = min(ours, key=lambda o: abs(o["onset"] - w["onset"]), default=None)
        if best and abs(best["onset"] - w["onset"]) <= max_gap_s:
            pairs.append((best, w))
    return pairs


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return None if sx == 0 or sy == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


# ---------------------------------------------------------------- checks

def verdict(name: str, value, enough: bool = True) -> str:
    if not enough or value is None:
        return "WAITING"
    _metric, op, thr = CRITERIA[name]
    ok = thr[0] <= value <= thr[1] if op == "within" else value <= thr if op == "<=" else value >= thr
    return "PASS" if ok else "FAIL"


def run(folder: str) -> dict:
    d = load(folder)
    r18 = [d["r18"][t] for t in sorted(d["r18"])]
    res = {"frames": d["frames"], "kinds": dict(d["kinds"]), "checks": {}}
    c = res["checks"]

    bad = d["undecodable"] + sum(d["odd_length"].values())
    c["decoder"] = {"undecodable": d["undecodable"], "odd_length": dict(d["odd_length"]),
                    "verdict": ("PASS" if bad == 0 else "FAIL") if d["frames"] else "WAITING"}

    # Asleep only: awake and moving, the strap misses beats (one R-R spanning two), which inflates the ratio.
    ratios = [r["heart_rate"] * (sum(r["rr_ms"]) / len(r["rr_ms"])) / 60000 for r in r18
              if r.get("rr_ms") and r.get("band_state") == "SLEEP" and 30 <= (r.get("heart_rate") or 0) <= 200]
    v = median(ratios) if ratios else None
    c["rr_unit"] = {"records": len(ratios), "median_ratio": v, "verdict": verdict("rr_unit", v, len(ratios) >= 1000)}

    hr_at = {t: r["heart_rate"] for t, r in d["r18"].items() if 25 <= (r.get("heart_rate") or 0) <= 230}
    pairs26 = []
    for b in hr_from_r26(list(d["r26"].values())):
        ref = [hr_at[t] for t in range(b["start_unix"], b["end_unix"] + 1) if t in hr_at]
        if b["heart_rate_bpm"] and ref:
            pairs26.append((b["heart_rate_bpm"], sum(ref) / len(ref)))
    mae = sum(abs(a - b) for a, b in pairs26) / len(pairs26) if pairs26 else None
    shuffled = [p[1] for p in pairs26]
    random.Random(0).shuffle(shuffled)
    mae_ctl = sum(abs(a - b) for (a, _), b in zip(pairs26, shuffled)) / len(pairs26) if pairs26 else None
    ok26 = verdict("r26_hr", mae, len(pairs26) >= 20)
    if ok26 == "PASS" and mae_ctl is not None and mae_ctl < 2 * mae:
        ok26 = "FAIL"  # no better than chance pairing: the agreement says nothing
    c["r26_hr"] = {"bursts": len(pairs26), "mae_bpm": mae, "shuffled_mae_bpm": mae_ctl, "verdict": ok26}

    still = {t for t, r in d["r18"].items() if (r.get("dynamic_accel_g") or 1) < 0.02}
    g = [m for t, m in d["r21_g"] if t in still]
    v = median(g) if g else None
    c["r21_scale"] = {"still_seconds": len(g), "median_g": v, "verdict": verdict("r21_scale", v, len(g) >= 600)}

    ours, whoop = night_metrics(r18), load_export(folder)
    pairs = pair(ours, whoop)
    res["nights"] = {"ours": len(ours), "whoop": len(whoop), "paired": len(pairs)}
    for key, which in (("sleep_onset", "onset"), ("sleep_wake", "wake")):
        diffs = [abs(o[which] - w[which]) / 60 for o, w in pairs if w[which]]
        v = median(diffs) if diffs else None
        c[key] = {"nights": len(diffs), "median_abs_min": v, "verdict": verdict(key, v, len(diffs) >= MIN_NIGHTS)}
    for key in ("spo2", "resp_rate", "resting_hr", "hrv", "skin_temp"):
        xy = [(o[key], w[key]) for o, w in pairs if o[key] is not None and w[key] is not None]
        xs, ys = [a for a, _ in xy], [b for _, b in xy]
        r = pearson(xs, ys)
        mae = sum(abs(a - b) for a, b in xy) / len(xy) if xy else None
        metric = CRITERIA[key][0]
        val = r if metric == "r" else mae
        out = {"nights": len(xy), "r": r, "mae": mae, "bias": (sum(xs) - sum(ys)) / len(xy) if xy else None,
               "whoop_spread": (max(ys) - min(ys)) if ys else None,
               "verdict": verdict(key, val, len(xy) >= MIN_NIGHTS)}
        if key in TREND_MIN_SPREAD and out["verdict"] == "PASS" and out["whoop_spread"] >= TREND_MIN_SPREAD[key] \
                and (r is None or r < TREND_R):
            out["verdict"] = "FAIL"  # close on average but does not follow WHOOP's night-to-night changes
        c[key] = out

    c["spo2_byte_82"] = byte_scan(d["r18_raw"], d["r18"], pairs)
    res["inventory"] = {"events": {str(k): n for k, n in d["events"].most_common()},
                        "r22_records": d["kinds"].get("R22", 0)}
    res["per_night"] = [{"ours": o, "whoop": w} for o, w in pairs]
    return res


def byte_scan(raw: dict, r18: dict, pairs) -> dict:
    """Rank every R18 byte by how well its nightly in-band (70-100) mean while asleep tracks WHOOP SpO2."""
    ys = [w["spo2"] for _o, w in pairs if w["spo2"] is not None]
    if len(ys) < MIN_NIGHTS:
        return {"verdict": "WAITING", "nights": len(ys)}
    scores = []
    for off in range(20, R18_LEN - 4):
        xs, yy = [], []
        for o, w in pairs:
            if w["spo2"] is None:
                continue
            v = [raw[t][off] for t in range(o["onset"], o["wake"] + 1)
                 if t in raw and r18[t].get("band_state") == "SLEEP" and 70 <= raw[t][off] <= 100]
            if len(v) >= 5:
                xs.append(sum(v) / len(v))
                yy.append(w["spo2"])
        if len(xs) >= MIN_NIGHTS and len(set(xs)) > 1:
            r = pearson(xs, yy)
            if r is not None:
                scores.append((r, off))
    scores.sort(reverse=True)
    best = scores[0][1] if scores else None
    return {"nights": len(ys), "top": [{"offset": o, "r": r} for r, o in scores[:5]],
            "verdict": "WAITING" if best is None else ("PASS" if best == 82 else "FAIL")}


# ---------------------------------------------------------------- report

def fmt(v):
    return "–" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)


def report(res: dict) -> str:
    lines = ["# Own-strap validation", "",
             f"{res['frames']} unique frames; nights: {res['nights']['ours']} ours, {res['nights']['whoop']} WHOOP, "
             f"{res['nights']['paired']} paired (bar: {MIN_NIGHTS}).", "",
             "| check | verdict | values | criterion |", "|---|---|---|---|"]
    for name, c in res["checks"].items():
        vals = ", ".join(f"{k}={fmt(v)}" for k, v in c.items() if k not in ("verdict", "top"))
        if "top" in c:
            vals += ", best=" + ", ".join(f"@{t['offset']} r={t['r']:.2f}" for t in c["top"][:3])
        crit = CRITERIA.get(name)
        crit_s = f"{crit[0]} {crit[1]} {crit[2]}" if crit else {"decoder": "0 undecodable, 0 odd lengths",
                                                                "spo2_byte_82": "byte 82 ranks first"}[name]
        lines.append(f"| {name} | **{c['verdict']}** | {vals} | {crit_s} |")
    lines += ["", "## Frame kinds", "", ", ".join(f"{k}: {n}" for k, n in sorted(res["kinds"].items())),
              "", "## Events", "", ", ".join(f"{k}: {n}" for k, n in res["inventory"]["events"].items()) or "–",
              "", "## Paired nights", "", "| onset | hours | SpO₂ ours/WHOOP | resp | RHR | HRV | skin |",
              "|---|---|---|---|---|---|---|"]
    for p in res["per_night"]:
        o, w = p["ours"], p["whoop"]
        lines.append(f"| {dt.datetime.fromtimestamp(o['onset']):%Y-%m-%d %H:%M} | {o['hours']} | "
                     + " | ".join(f"{fmt(o[k])} / {fmt(w[k])}" for k in ("spo2", "resp_rate", "resting_hr",
                                                                          "hrv", "skin_temp")) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "whoop5-data", "own_strap")
    res = run(folder)
    text = report(res)
    open(os.path.join(folder, "REPORT.md"), "w").write(text)
    with open(os.path.join(folder, "report.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    print(text)


if __name__ == "__main__":
    main()
