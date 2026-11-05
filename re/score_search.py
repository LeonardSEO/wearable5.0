"""Search for the formula behind WHOOP's scores, using only an owner's export and raw frames.

The export pairs each cycle's inputs with the score WHOOP gave it. This tries every transform of every input, then every
combination of them, under two links (identity and logit), and ranks them by leave-one-out error. WHOOP's servers are never
contacted.

A search over this many formulas always finds one that fits, so a fit alone proves nothing. Three checks decide:
  holdout      the formula is picked on the oldest 70 % of cycles and judged on the newest 30 %.
  shuffle      the whole search reruns on shuffled scores; the real result has to beat all those runs.
  resolution   "exact" means within one reported unit of WHOOP's value (1 for %, 0.1 for strain).

  python re/score_search.py <export.zip | physiological_cycles.csv | whoop_days_shared.csv> [--frames FOLDER]
         [--target recovery] [--max-terms 3] [--beam 200] [--shuffles 20]

Verdicts, fixed before any data was seen (VERDICT_* below):
  FORMULA   at least 90 % of holdout cycles exact, and beats every shuffled run.
  MODEL     holdout error at most half that of always guessing the mean, and beats every shuffled run.
  NONE      neither. With too few cycles the search does not run at all.
"""
from __future__ import annotations

import argparse
import csv
import io
import itertools
import math
import os
import sys
import zipfile

import numpy as np

MIN_CYCLES = 20
VERDICT_EXACT_SHARE = 0.90
VERDICT_MODEL_RATIO = 0.5
TRAIN_SHARE = 0.7
BASELINE_HALF_LIVES = (7, 14, 30)
BASELINE_MIN_PRIOR = 7

EXPORT_COLUMNS = {
    "recovery": "Recovery score %", "rhr": "Resting heart rate", "hrv": "Heart rate variability", "skin_temp": "Skin temp",
    "spo2": "Blood oxygen", "strain": "Day Strain", "energy": "Energy burned", "max_hr": "Max HR", "avg_hr": "Average HR",
    "sleep_perf": "Sleep performance", "resp": "Respiratory rate", "asleep": "Asleep duration", "in_bed": "In bed duration",
    "light": "Light sleep", "deep": "Deep (SWS)", "rem": "REM duration", "awake": "Awake duration", "need": "Sleep need",
    "debt": "Sleep debt", "efficiency": "Sleep efficiency", "consistency": "Sleep consistency",
}
SHARED_DAYS_COLUMNS = {"strain": "day_strain", "rhr": "resting_hr", "max_hr": "max_hr", "avg_hr": "avg_hr"}

SLEEP_INPUTS = ["asleep", "in_bed", "light", "deep", "rem", "awake", "need", "debt", "efficiency", "consistency"]
# Only what exists when WHOOP computes the score: recovery is set on waking, so it sees yesterday's strain, not today's.
TARGETS = {
    "recovery": {"resolution": 1.0, "bounds": (0, 100),
                 "inputs": ["hrv", "rhr", "resp", "skin_temp", "spo2", "sleep_perf", "prev_strain"] + SLEEP_INPUTS},
    "strain": {"resolution": 0.1, "bounds": (0, 21),
               "inputs": ["max_hr", "avg_hr", "rhr", "energy", "trimp", "z1", "z2", "z3", "z4", "z5"]},
    "sleep_perf": {"resolution": 1.0, "bounds": (0, 100), "inputs": ["prev_strain", "prev_debt"] + SLEEP_INPUTS},
    "need": {"resolution": 1.0, "bounds": None, "inputs": ["prev_strain", "prev_debt", "prev_asleep", "prev_need"]},
}
BASELINED = {"hrv", "rhr", "resp", "skin_temp", "spo2"}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return math.nan
    return x if math.isfinite(x) else math.nan


def _rows_from_text(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return []
    header = list(rows[0])
    if "day_strain" in header:
        rows.sort(key=lambda r: int(r["day"]))
        return [{k: _num(r.get(c)) for k, c in SHARED_DAYS_COLUMNS.items()} for r in rows]
    cols = {k: next((h for h in header if h.strip().startswith(p)), None) for k, p in EXPORT_COLUMNS.items()}
    rows.sort(key=lambda r: r.get("Cycle start time") or "")
    return [{"start": r.get("Cycle start time"), "end": r.get("Cycle end time"),
             **{k: _num(r.get(c)) if c else math.nan for k, c in cols.items()}} for r in rows]


def load_rows(path: str) -> list[dict]:
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if os.path.basename(n).lower() == "physiological_cycles.csv")
            return _rows_from_text(z.read(name).decode("utf-8-sig"))
    return _rows_from_text(open(path, encoding="utf-8-sig").read())


def add_previous_cycle(rows: list[dict]) -> None:
    for prev, row in zip([{}] + rows, rows):
        for k in ("strain", "debt", "asleep", "need"):
            row[f"prev_{k}"] = prev.get(k, math.nan)


def add_trimp(rows: list[dict], folder: str) -> None:
    """Per-cycle TRIMP and zone minutes from raw R18 heart rate; cycles under 80 % covered stay NaN."""
    import datetime as dt
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from strain_model import edwards_trimp, hr_by_second, zone_minutes
    hr = hr_by_second(folder)
    hr_max = max(hr.values())
    for row in rows:
        try:
            start = dt.datetime.fromisoformat(row["start"]).timestamp()
            end = dt.datetime.fromisoformat(row["end"]).timestamp()
        except (TypeError, ValueError, KeyError):
            continue
        hrs = [h for t, h in hr.items() if start <= t < end]
        if end > start and len(hrs) / (end - start) >= 0.8:
            mins = zone_minutes(hrs, hr_max)
            row["trimp"] = edwards_trimp(mins)
            for i, m in enumerate(mins):
                row[f"z{i + 1}"] = m


def baseline_features(values: np.ndarray) -> dict[str, np.ndarray]:
    """Deviation from a personal baseline built from earlier cycles only, at several half-lives."""
    out = {}
    for half_life in BASELINE_HALF_LIVES:
        alpha = 1 - 0.5 ** (1 / half_life)
        mean, var, seen = math.nan, 0.0, 0
        z, diff, ratio = (np.full(len(values), math.nan) for _ in range(3))
        for i, x in enumerate(values):
            if seen >= BASELINE_MIN_PRIOR and var > 0 and math.isfinite(x):
                z[i], diff[i], ratio[i] = (x - mean) / math.sqrt(var), x - mean, x / mean if mean else math.nan
            if math.isfinite(x):
                if seen == 0:
                    mean = x
                else:
                    delta = x - mean
                    mean += alpha * delta
                    var = (1 - alpha) * (var + alpha * delta * delta)
                seen += 1
        out[f"z{half_life}"], out[f"diff{half_life}"], out[f"ratio{half_life}"] = z, diff, ratio
    return out


def build_features(rows: list[dict], inputs: list[str]) -> dict[str, np.ndarray]:
    """Every candidate term: each input, its transforms, its baseline deviations, and each ratio of two inputs."""
    base = {k: np.array([r.get(k, math.nan) for r in rows], float) for k in inputs}
    base = {k: v for k, v in base.items() if np.isfinite(v).sum() >= 2 and np.nanstd(v) > 0}
    feats = {}
    with np.errstate(all="ignore"):
        for k, v in base.items():
            feats[k] = v
            feats[f"{k}^2"] = v * v
            if np.nanmin(v) > 0:
                feats[f"ln({k})"] = np.log(v)
                feats[f"1/{k}"] = 1 / v
                feats[f"sqrt({k})"] = np.sqrt(v)
            elif np.nanmin(v) >= 0:
                feats[f"ln1p({k})"] = np.log1p(v)
            if k in BASELINED:
                feats.update({f"{name}({k})": col for name, col in baseline_features(v).items()})
                if np.nanmin(v) > 0:
                    feats.update({f"{name}(ln {k})": col for name, col in baseline_features(np.log(v)).items()
                                  if name.startswith("z")})
        for a, b in itertools.permutations(base, 2):
            if np.nanmin(base[b]) > 0:
                feats[f"{a}/{b}"] = base[a] / base[b]
    return feats


def design(rows: list[dict], target: str):
    """Rows with a score, and the matrix of terms complete on nearly all of them."""
    spec = TARGETS[target]
    y = np.array([r.get(target, math.nan) for r in rows], float)
    have = np.isfinite(y)
    feats = {k: v[have] for k, v in build_features(rows, spec["inputs"]).items()}
    y = y[have]
    if len(y) == 0:
        return y, [], np.empty((0, 0))
    # Baseline terms are NaN during their warm-up; drop those rows rather than the terms, then require completeness.
    keep = {k: v for k, v in feats.items() if np.isfinite(v).mean() >= 0.7}
    rows_ok = np.all([np.isfinite(v) for v in keep.values()], axis=0) if keep else np.zeros(len(y), bool)
    seen, names, cols = set(), [], []
    for k, v in keep.items():
        col = v[rows_ok]
        key = np.round(col, 9).tobytes()
        if col.size and np.std(col) > 1e-12 and key not in seen:
            seen.add(key)
            names.append(k)
            cols.append(col)
    return y[rows_ok], names, np.array(cols).T if cols else np.empty((rows_ok.sum(), 0))


def link_y(y: np.ndarray, link: str, bounds) -> np.ndarray:
    if link == "identity":
        return y
    lo, hi = bounds
    p = np.clip((y - lo) / (hi - lo), 0.005, 0.995)
    return np.log(p / (1 - p))


def unlink(pred: np.ndarray, link: str, bounds) -> np.ndarray:
    if link == "identity":
        return pred
    lo, hi = bounds
    return lo + (hi - lo) / (1 + np.exp(-np.clip(pred, -30, 30)))


def loo_errors(X: np.ndarray, y: np.ndarray, subsets: np.ndarray, link: str, bounds, y_raw: np.ndarray) -> np.ndarray:
    """Leave-one-out MAE on the score's own scale, per subset, in batch via the hat-matrix shortcut."""
    n, k = X.shape[0], subsets.shape[1]
    A = np.empty((len(subsets), n, k + 1))
    A[:, :, 0] = 1.0
    A[:, :, 1:] = np.transpose(X[:, subsets], (1, 0, 2))
    AtA = np.einsum("mni,mnj->mij", A, A) + 1e-9 * np.eye(k + 1)
    inv = np.linalg.inv(AtA)
    beta = np.einsum("mij,mnj,n->mi", inv, A, y)
    fit = np.einsum("mni,mi->mn", A, beta)
    hat = np.clip(np.einsum("mni,mij,mnj->mn", A, inv, A), 0, 0.999)
    loo = y - (y - fit) / (1 - hat)
    return np.abs(unlink(loo, link, bounds) - y_raw).mean(axis=1)


def search(X: np.ndarray, y_raw: np.ndarray, bounds, max_terms: int, beam: int) -> dict:
    """All single terms, all pairs, then the best `beam` subsets extended term by term, under each link."""
    best = {"mae": math.inf, "terms": (), "link": "identity"}
    tried = 0
    links = ["identity", "logit"] if bounds else ["identity"]
    max_terms = min(max_terms, max(1, (len(y_raw) - 2) // 5))
    for link in links:
        y = link_y(y_raw, link, bounds)
        frontier = [()]
        for size in range(1, max_terms + 1):
            if size <= 2:
                subsets = list(itertools.combinations(range(X.shape[1]), size))
            else:
                subsets = sorted({tuple(sorted(s + (j,))) for s in frontier for j in range(X.shape[1]) if j not in s})
            if not subsets:
                break
            arr = np.array(subsets)
            maes = np.concatenate([loo_errors(X, y, arr[i:i + 2000], link, bounds, y_raw)
                                   for i in range(0, len(arr), 2000)])
            tried += len(arr)
            order = np.argsort(maes)[:beam]
            frontier = [subsets[i] for i in order]
            if maes[order[0]] < best["mae"]:
                best = {"mae": float(maes[order[0]]), "terms": subsets[order[0]], "link": link}
    best["tried"] = tried
    return best


def fit_predict(X_tr, y_tr, X_te, terms, link, bounds):
    A = np.column_stack([np.ones(len(X_tr)), X_tr[:, list(terms)]])
    beta, *_ = np.linalg.lstsq(A, link_y(y_tr, link, bounds), rcond=None)
    pred = np.column_stack([np.ones(len(X_te)), X_te[:, list(terms)]]) @ beta
    return beta, unlink(pred, link, bounds)


def run_target(rows: list[dict], target: str, max_terms: int, beam: int, shuffles: int, seed: int = 0) -> dict:
    spec = TARGETS[target]
    y, names, X = design(rows, target)
    res = {"target": target, "cycles": len(y), "terms_available": len(names)}
    if len(y) < MIN_CYCLES or not names:
        return {**res, "verdict": "TOO_FEW", "need": MIN_CYCLES}
    bounds = spec["bounds"]
    cut = int(len(y) * TRAIN_SHARE)
    picked = search(X[:cut], y[:cut], bounds, max_terms, beam)
    _, pred = fit_predict(X[:cut], y[:cut], X[cut:], picked["terms"], picked["link"], bounds)
    err = np.abs(pred - y[cut:])
    mean_err = float(np.abs(y[:cut].mean() - y[cut:]).mean())
    holdout_mae = float(err.mean())
    exact = float((err <= spec["resolution"] + 1e-9).mean())

    rng = np.random.default_rng(seed)
    null = []
    for _ in range(shuffles):
        y_s = rng.permutation(y[:cut])
        y_rest = rng.permutation(y[cut:])
        pick = search(X[:cut], y_s, bounds, max_terms, beam)
        _, p = fit_predict(X[:cut], y_s, X[cut:], pick["terms"], pick["link"], bounds)
        null.append(float(np.abs(p - y_rest).mean()))
    beats_shuffle = bool(null) and holdout_mae < min(null)

    if exact >= VERDICT_EXACT_SHARE and beats_shuffle:
        verdict = "FORMULA"
    elif holdout_mae <= VERDICT_MODEL_RATIO * mean_err and beats_shuffle:
        verdict = "MODEL"
    else:
        verdict = "NONE"
    final = search(X, y, bounds, max_terms, beam)
    beta, _ = fit_predict(X, y, X[:1], final["terms"], final["link"], bounds)
    return {**res, "verdict": verdict, "tried": picked["tried"], "train": cut, "test": len(y) - cut,
            "holdout_mae": holdout_mae, "guess_mean_mae": mean_err, "holdout_exact": exact,
            "shuffled_best_mae": min(null) if null else None, "picked": [names[i] for i in picked["terms"]],
            "picked_link": picked["link"], "final": [names[i] for i in final["terms"]], "final_link": final["link"],
            "final_coef": [round(float(b), 4) for b in beta], "final_loo_mae": final["mae"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source")
    ap.add_argument("--frames", help="folder with raw frames; adds per-cycle TRIMP and zone minutes")
    ap.add_argument("--target", choices=sorted(TARGETS), action="append")
    ap.add_argument("--max-terms", type=int, default=3)
    ap.add_argument("--beam", type=int, default=200)
    ap.add_argument("--shuffles", type=int, default=20)
    args = ap.parse_args()
    rows = load_rows(args.source)
    add_previous_cycle(rows)
    if args.frames:
        add_trimp(rows, args.frames)
    print(f"{len(rows)} cycles from {os.path.basename(args.source)}\n")
    for target in args.target or list(TARGETS):
        r = run_target(rows, target, args.max_terms, args.beam, args.shuffles)
        print(f"## {target}: {r['verdict']}")
        if r["verdict"] == "TOO_FEW":
            print(f"   {r['cycles']} usable cycles, need {r['need']}; {r['terms_available']} candidate terms ready.\n")
            continue
        print(f"   {r['tried']} formulas on {r['train']} cycles, judged on the newest {r['test']}")
        print(f"   holdout error {r['holdout_mae']:.2f}; guessing the mean {r['guess_mean_mae']:.2f}; "
              f"best shuffled run {r['shuffled_best_mae']:.2f}; exact {r['holdout_exact']:.0%}")
        print(f"   picked ({r['picked_link']}): {' + '.join(r['picked'])}")
        print(f"   on all cycles ({r['final_link']}): {' + '.join(r['final'])}  coef {r['final_coef']}  "
              f"leave-one-out error {r['final_loo_mae']:.2f}\n")


if __name__ == "__main__":
    main()
