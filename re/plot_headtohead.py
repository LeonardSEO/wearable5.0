"""Draw the head-to-head chart for the README from re/noop_compare.py's aggregates (no per-night data).

  python re/plot_headtohead.py <noop_compare --json output> docs/headtohead.svg

Plain SVG with its own background, so it reads the same in GitHub's light and dark themes. Each row is scaled to NOOP's error
(NOOP = full bar) because the units differ per score; the labels carry the absolute values.
"""
import json
import sys

ROWS = (  # label, NOOP key, our key, unit, digits
    ("Recovery", "rec_noop_own_rest", "rec_ours", " pts", 1),
    ("Sleep performance", "sp_noop", "sp_ours", " pts", 1),
    ("Sleep need", "need_noop", "need_ours", " min", 1),
    ("Day strain", "strain_noop", "strain_ours", "", 2),
    ("Workout zones", "zones_noop_unseen", "zones_ours_unseen", " %", 1),
)
W, LEFT, BAR_W, ROW_H, TOP = 760, 170, 470, 64, 78
INK, MUTED, NOOP_C, OURS_C, BG = "#1f2328", "#59636e", "#c4c9d0", "#1a7f37", "#ffffff"


def main() -> None:
    d = json.load(open(sys.argv[1]))
    h = TOP + ROW_H * len(ROWS) + 46
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" '
           f'aria-label="Mean distance from WHOOP\'s own scores, NOOP against this repository">',
           f'<rect width="{W}" height="{h}" rx="10" fill="{BG}"/>',
           '<style>text{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif}</style>',
           f'<text x="24" y="34" font-size="19" font-weight="600" fill="{INK}">Mean distance from WHOOP\'s own scores — shorter is better</text>',
           f'<text x="24" y="56" font-size="13" fill="{MUTED}">Same nights, cycles and workouts. NOOP main {d["noop_commit"]}; ours out-of-sample. '
           f'Each row scaled to NOOP\'s error.</text>']
    for i, (label, nk, ok, unit, dig) in enumerate(ROWS):
        y = TOP + i * ROW_H
        nv, ov = d[nk]["mean"], d[ok]["mean"]
        ow = max(2, BAR_W * ov / nv)
        out += [f'<text x="24" y="{y + 25}" font-size="14" font-weight="600" fill="{INK}">{label}</text>',
                f'<rect x="{LEFT}" y="{y + 4}" width="{BAR_W}" height="20" rx="4" fill="{NOOP_C}"/>',
                f'<text x="{LEFT + BAR_W + 10}" y="{y + 19}" font-size="13" fill="{MUTED}">NOOP {nv:.{dig}f}{unit}</text>',
                f'<rect x="{LEFT}" y="{y + 28}" width="{ow:.1f}" height="20" rx="4" fill="{OURS_C}"/>',
                f'<text x="{LEFT + ow + 10:.1f}" y="{y + 43}" font-size="13" font-weight="600" fill="{OURS_C}">this repo {ov:.{dig}f}{unit} '
                f'({100 * ov / nv:.0f} % of NOOP\'s)</text>']
    y = TOP + ROW_H * len(ROWS) + 22
    out += [f'<rect x="24" y="{y - 11}" width="14" height="12" rx="2" fill="{NOOP_C}"/>',
            f'<text x="44" y="{y}" font-size="12" fill="{MUTED}">NOOP\'s own scorers</text>',
            f'<rect x="190" y="{y - 11}" width="14" height="12" rx="2" fill="{OURS_C}"/>',
            f'<text x="210" y="{y}" font-size="12" fill="{MUTED}">this repository (re/score_formulas.py), reproduced by re/noop_compare.py</text>',
            "</svg>"]
    open(sys.argv[2], "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
