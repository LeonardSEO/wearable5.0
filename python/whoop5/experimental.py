"""Experimental metrics derived from decoded WHOOP 5/MG records.

Backed by real captures (see FINDINGS) but not yet checked against a clinical or WHOOP-app reference
on more than one wearer. Twin: `Whoop5Experimental` in the Swift package.
"""
from __future__ import annotations

import math
from statistics import median


def spo2_windows(records: list[dict], max_gap: int = 2, min_valid_seconds: int = 5) -> list[dict]:
    """One SpO2 value per strap measurement window.

    `records` are decoded R18 dicts (decode_frame output). A window is a run of records whose SpO2 byte
    is non-zero, allowing gaps of at most `max_gap` seconds. Each window reports the median of its valid
    seconds (70-100 %), or None when fewer than `min_valid_seconds` seconds were valid (a lone value in a
    window of status codes is noise).
    """
    rows = sorted((r["unix_s"], r["spo2_byte_82"], r.get("spo2_percent")) for r in records
                  if r.get("layout") == 18 and r.get("spo2_byte_82") is not None)
    windows, cur = [], []
    for t, raw, pct in rows:
        if raw == 0:
            continue
        if cur and t - cur[-1][0] > max_gap:
            windows.append(cur)
            cur = []
        cur.append((t, pct))
    if cur:
        windows.append(cur)
    out = []
    for w in windows:
        valid = [p for _, p in w if p is not None]
        out.append({"start_unix": w[0][0], "end_unix": w[-1][0], "seconds": len(w), "valid_seconds": len(valid),
                    "spo2_percent": float(median(valid)) if len(valid) >= max(1, min_valid_seconds) else None})
    return out


def rmssd_ms(rr_ms: list[int], max_step_ms: int = 200) -> float | None:
    """RMSSD over consecutive R-R intervals in ms; steps above `max_step_ms` (missed beats, artefacts)
    and intervals outside 300-2000 ms are dropped. None with fewer than 10 usable differences."""
    rr = [x for x in rr_ms if 300 <= x <= 2000]
    diffs = [b - a for a, b in zip(rr, rr[1:]) if abs(b - a) < max_step_ms]
    if len(diffs) < 10:
        return None
    return math.sqrt(sum(d * d for d in diffs) / len(diffs))


def _valid_hr(hr) -> bool:
    return hr is not None and 25 <= hr <= 230


def sleep_periods(records: list[dict], smooth_s: int = 300, max_gap_s: int = 600,
                  min_duration_s: int = 1200) -> list[dict]:
    """Sleep periods from the R18 band state (**experimental**).

    `records` are decoded R18 dicts. A second counts as asleep when band_state is SLEEP (WAKE, STILL and UP
    do not); the per-second flag is smoothed by a majority vote over a centred `smooth_s` window (by time,
    so data gaps shrink the vote instead of padding it). Smoothed-asleep seconds closer than `max_gap_s`
    form one period (brief awakenings stay inside it); periods shorter than `min_duration_s` are dropped.
    Each period reports onset/offset (unix s), duration_s (offset - onset + 1), asleep_s (raw SLEEP seconds
    inside), records, and heart rate minimum and mean over all records inside with a valid HR (25-230).
    The band state is the strap's motion/rest flag, not a sleep stage or a validated sleep/wake classifier.
    """
    seen, rows = set(), []
    for r in sorted((r for r in records if r.get("layout", 18) == 18), key=lambda r: r["unix_s"]):
        if r["unix_s"] not in seen:
            seen.add(r["unix_s"])
            rows.append((r["unix_s"], r.get("band_state") == "SLEEP", r.get("heart_rate")))
    n, half = len(rows), smooth_s / 2
    prefix = [0]
    for _, s, _ in rows:
        prefix.append(prefix[-1] + s)
    smoothed, lo, hi = [], 0, 0
    for t, _, _ in rows:
        while rows[lo][0] < t - half:
            lo += 1
        while hi < n and rows[hi][0] <= t + half:
            hi += 1
        smoothed.append(2 * (prefix[hi] - prefix[lo]) > hi - lo)
    spans = []
    for i, (t, _, _) in enumerate(rows):
        if not smoothed[i]:
            continue
        if spans and t - spans[-1][1] <= max_gap_s:
            spans[-1][1] = t
        else:
            spans.append([t, t])
    out = []
    for start, end in spans:
        if end - start + 1 < min_duration_s:
            continue
        inside = [r for r in rows if start <= r[0] <= end]
        hrs = [hr for _, _, hr in inside if _valid_hr(hr)]
        out.append({"onset_unix": start, "offset_unix": end, "duration_s": end - start + 1,
                    "asleep_s": sum(1 for _, s, _ in inside if s), "records": len(inside),
                    "hr_min": min(hrs) if hrs else None, "hr_mean": sum(hrs) / len(hrs) if hrs else None})
    return out


def _clean_rr(rr_ms: list[int], max_step_ms: int = 200) -> list[int]:
    out, prev = [], None
    for x in rr_ms:
        if not 300 <= x <= 2000:
            continue
        if prev is None or abs(x - prev) < max_step_ms:
            out.append(x)
        prev = x
    return out


def respiratory_rate(rr_ms: list[int], window_s: float = 60, fs: float = 4.0, lo_hz: float = 0.1,
                     hi_hz: float = 0.5, step_hz: float = 0.005) -> list[dict]:
    """Breaths per minute from respiratory sinus arrhythmia in an R-R series (**experimental**).

    `rr_ms` is a contiguous R-R series in ms (e.g. every R18 record's rr_ms, in order). Intervals outside
    300-2000 ms and steps of 200 ms or more are dropped; beat times are the cumulative sum of the kept
    intervals. The tachogram is cut into consecutive `window_s` windows of beat time, linearly resampled at
    `fs`, mean- and linear-detrended and Hann-windowed; its power is evaluated by a direct DFT every `step_hz`
    from `lo_hz` to min(`hi_hz`, half the window's mean beat rate). Power is weighted by f^2 (the spectrum of
    the R-R derivative) so the 1/f low-frequency background does not pin the peak at `lo_hz`. Each window
    reports start_s/end_s (beat time from the series start), beats, breaths_per_min (peak f * 60, None with
    fewer than window_s/3 beats) and peak_fraction (peak power / total in band; low values = no clear rhythm).
    Missing beats shorten beat time a little, which biases the rate slightly upwards.
    """
    rr = _clean_rr(rr_ms)
    times, acc = [], 0.0
    for x in rr:
        acc += x / 1000.0
        times.append(acc)
    out, start, i = [], 0.0, 0
    while times and start + window_s <= times[-1]:
        end = start + window_s
        while i < len(times) and times[i] < start:
            i += 1
        j = i
        while j < len(times) and times[j] < end:
            j += 1
        sel_t, sel_v = times[i:j], rr[i:j]
        row = {"start_s": start, "end_s": end, "beats": len(sel_t), "breaths_per_min": None, "peak_fraction": None}
        if len(sel_t) >= max(4, window_s / 3):
            n = int(window_s * fs)
            ys, k = [], 0
            for m in range(n):
                q = start + m / fs
                while k < len(sel_t) - 2 and sel_t[k + 1] < q:
                    k += 1
                t0, t1, v0, v1 = sel_t[k], sel_t[k + 1], sel_v[k], sel_v[k + 1]
                q = min(max(q, t0), t1)
                ys.append(v0 + (v1 - v0) * (q - t0) / (t1 - t0) if t1 > t0 else float(v0))
            mean, xm = sum(ys) / n, (n - 1) / 2
            slope = sum((m - xm) * (y - mean) for m, y in enumerate(ys)) / sum((m - xm) ** 2 for m in range(n))
            ys = [(y - mean - slope * (m - xm)) * (0.5 - 0.5 * math.cos(2 * math.pi * m / (n - 1)))
                  for m, y in enumerate(ys)]
            top = min(hi_hz, 0.5 * len(sel_t) / window_s)
            best_f, best_p, total, s = None, -1.0, 0.0, 0
            while lo_hz + s * step_hz <= top + 1e-9:
                f = lo_hz + s * step_hz
                w = 2 * math.pi * f / fs
                re = sum(y * math.cos(w * m) for m, y in enumerate(ys))
                im = sum(y * math.sin(w * m) for m, y in enumerate(ys))
                p = (re * re + im * im) * f * f
                total += p
                if p > best_p:
                    best_f, best_p = f, p
                s += 1
            if best_f is not None and total > 0:
                row["breaths_per_min"] = best_f * 60
                row["peak_fraction"] = best_p / total
        out.append(row)
        start = end
    return out


def skin_temp_baseline(records: list[dict], periods: list[dict] | None = None,
                       baseline_c: float | None = None) -> list[dict]:
    """Nightly skin temperature (**experimental**): mean/min/max/sd of R18 skin_temp_c over each sleep period.

    `periods` default to `sleep_periods(records)`. deviation_c is the night mean minus `baseline_c` when given,
    else minus the mean of the previous nights' means (None for the first night). The sensor is uncalibrated
    against a clinical thermometer and settles over the first hour on the wrist (it rose ~3 C in the overnight
    capture), so compare nights with each other, not with core temperature.
    """
    if periods is None:
        periods = sleep_periods(records)
    temps = sorted((r["unix_s"], r["skin_temp_c"]) for r in records
                   if r.get("layout", 18) == 18 and r.get("skin_temp_c") is not None)
    out, means = [], []
    for p in periods:
        v = [c for t, c in temps if p["onset_unix"] <= t <= p["offset_unix"]]
        row = {"onset_unix": p["onset_unix"], "offset_unix": p["offset_unix"], "samples": len(v),
               "mean_c": None, "min_c": None, "max_c": None, "sd_c": None, "baseline_c": None, "deviation_c": None}
        if v:
            mean = sum(v) / len(v)
            base = baseline_c if baseline_c is not None else (sum(means) / len(means) if means else None)
            row.update(mean_c=mean, min_c=min(v), max_c=max(v),
                       sd_c=math.sqrt(sum((c - mean) ** 2 for c in v) / len(v)), baseline_c=base,
                       deviation_c=mean - base if base is not None else None)
            means.append(mean)
        out.append(row)
    return out


def _biquad(x: list[float], b: tuple[float, float, float], a: tuple[float, float]) -> list[float]:
    """Direct-form-II-transposed biquad, zero initial state; a = (a1, a2) with a0 normalised to 1."""
    z1 = z2 = 0.0
    out = []
    for v in x:
        y = b[0] * v + z1
        z1 = b[1] * v - a[0] * y + z2
        z2 = b[2] * v - a[1] * y
        out.append(y)
    return out


def _butter2(fc: float, fs: float, high: bool) -> tuple[tuple[float, float, float], tuple[float, float]]:
    """Second-order Butterworth low/high-pass (bilinear transform, RBJ cookbook, Q = 1/sqrt(2))."""
    w0 = 2 * math.pi * fc / fs
    c, alpha = math.cos(w0), math.sin(w0) / math.sqrt(2)
    a0 = 1 + alpha
    if high:
        b = ((1 + c) / 2, -(1 + c), (1 + c) / 2)
    else:
        b = ((1 - c) / 2, 1 - c, (1 - c) / 2)
    return (b[0] / a0, b[1] / a0, b[2] / a0), (-2 * c / a0, (1 - alpha) / a0)


def bandpass(x: list[float], fs: float, lo_hz: float, hi_hz: float) -> list[float]:
    """Zero-phase band-pass: 2nd-order Butterworth high-pass at `lo_hz` and low-pass at `hi_hz`, run forward
    and backward (4th-order magnitude each side), on an odd-reflected padding of up to 2 s per end."""
    n = len(x)
    pad = min(n - 1, int(2 * fs))
    if pad < 1:
        return [0.0] * n
    ext = [2 * x[0] - x[k] for k in range(pad, 0, -1)] + list(x) + [2 * x[-1] - x[n - 2 - k] for k in range(pad)]
    hp, lp = _butter2(lo_hz, fs, True), _butter2(hi_hz, fs, False)
    y = [v - ext[0] for v in ext]
    for _ in range(2):
        y = _biquad(_biquad(y, *hp), *lp)[::-1]
    return y[pad:pad + n]


def find_peaks(y: list[float], distance: int = 1, prominence: float = 0.0) -> list[int]:
    """Local maxima of `y` (scipy.signal.find_peaks semantics for `distance` and `prominence`): peaks closer
    than `distance` samples to a higher kept peak are dropped (on equal height the later one is kept), then peaks below `prominence` are dropped."""
    cand = [i for i in range(1, len(y) - 1) if y[i - 1] < y[i] >= y[i + 1]]
    keep = set(cand)
    if distance > 1:
        keep = set()
        for i in sorted(cand, key=lambda i: (-y[i], -i)):  # ties: later index first, as scipy
            if all(abs(i - j) >= distance for j in keep):
                keep.add(i)
    out = []
    for p in sorted(keep):
        left_min = y[p]
        k = p - 1
        while k >= 0 and y[k] <= y[p]:
            left_min = min(left_min, y[k])
            k -= 1
        right_min = y[p]
        k = p + 1
        while k < len(y) and y[k] <= y[p]:
            right_min = min(right_min, y[k])
            k += 1
        if y[p] - max(left_min, right_min) >= prominence:
            out.append(p)
    return out


def hr_from_r26(records: list[dict], fs: float = 25.0, min_seconds: int = 12) -> list[dict]:
    """Heart rate per R26 burst from the 25 Hz compact optical waveform (**experimental**).

    `records` are decoded R26 dicts (`samples`: 25 cumulative samples per record, one record per second).
    A burst is a run of consecutive seconds with the same burst_counter (duplicates by record_index dropped).
    Per burst of at least `min_seconds` s: subtract the median, band-pass 0.6-3.3 Hz (`bandpass`), invert
    (a pulse is an absorption dip), pick peaks at least 0.33 s apart with prominence >= 0.3 sd, and report
    60 / median inter-beat interval (IBIs 0.3-2.0 s, at least 5) as heart_rate_bpm, else None.
    Same method as re/analyze_r26.py (scipy), which tracked R18 heart_rate at r = 0.95, MAE 1.4 bpm over
    17 overnight bursts (46-66 bpm); not checked during exercise or on other wearers.
    """
    seen, rows = set(), []
    for r in sorted((r for r in records if r.get("layout") == 26 and r.get("samples")),
                    key=lambda r: (r["unix_s"], r.get("record_index", 0))):
        key = r.get("record_index", (r["unix_s"], r["burst_counter"]))
        if key not in seen:
            seen.add(key)
            rows.append(r)
    bursts = []
    for r in rows:
        if bursts and r["unix_s"] == bursts[-1][-1]["unix_s"] + 1 and r["burst_counter"] == bursts[-1][-1]["burst_counter"]:
            bursts[-1].append(r)
        else:
            bursts.append([r])
    out = []
    for b in bursts:
        x = [float(v) for r in b for v in r["samples"]]
        row = {"start_unix": b[0]["unix_s"], "end_unix": b[-1]["unix_s"], "seconds": len(b),
               "burst_counter": b[0]["burst_counter"], "beats": 0, "heart_rate_bpm": None}
        if len(x) >= fs * min_seconds:
            med = median(x)
            y = [-v for v in bandpass([v - med for v in x], fs, 0.6, 3.3)]
            mean = sum(y) / len(y)
            sd = math.sqrt(sum((v - mean) ** 2 for v in y) / len(y))
            peaks = find_peaks(y, distance=int(fs * 0.33), prominence=0.3 * sd)
            ibi = [(q - p) / fs for p, q in zip(peaks, peaks[1:])]
            ibi = [v for v in ibi if 0.3 < v < 2.0]
            row["beats"] = len(peaks)
            if len(ibi) >= 5:
                row["heart_rate_bpm"] = 60.0 / median(ibi)
        out.append(row)
    return out
