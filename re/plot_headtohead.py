"""Draw the README chart from re/noop_compare.py's aggregates (no per-night data).

  python re/plot_headtohead.py <noop_compare --json output> docs/headtohead.svg [--ours-label TEXT]

WHOOP is the zero line. Each score's mean distance from WHOOP is drawn as a percentage of that score's own scale, chosen before
drawing: recovery and sleep performance 0-100, day strain 0-21, sleep need WHOOP's mean need, zones the share of workout time.
Plain SVG with its own background, so it reads the same in GitHub's light and dark themes.
"""
import argparse
import json

AXIS_MAX = 15.0  # % ; a value beyond it is drawn at the edge with its number
W, LEFT, RIGHT, TOP, ROW_H = 820, 230, 760, 112, 58
INK, MUTED, GRID, WHOOP_C, OURS_C, NOOP_C, BG = "#1f2328", "#59636e", "#e6e8eb", "#1f2328", "#1a7f37", "#cf222e", "#ffffff"


def x_of(pct: float) -> float:
    return LEFT + (RIGHT - LEFT) * min(pct, AXIS_MAX) / AXIS_MAX


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--ours-label", default="this repository")
    a = ap.parse_args()
    d = json.load(open(a.data))
    need = d["need_whoop_mean_min"]
    rows = (  # label, scale note, NOOP %, ours %, NOOP raw, ours raw
        ("Recovery", "points of 100", d["rec_noop_own_rest"]["mean"], d["rec_ours"]["mean"], None, 1),
        ("Sleep performance", "points of 100", d["sp_noop"]["mean"], d["sp_ours"]["mean"], None, 1),
        ("Day strain", "of the 0–21 scale", d["strain_noop"]["mean"] / 21 * 100, d["strain_ours"]["mean"] / 21 * 100,
         "{:.2f}", 21 / 100),
        ("Sleep need", f"of WHOOP's mean need ({need / 60:.1f} h)", d["need_noop"]["mean"] / need * 100,
         d["need_ours"]["mean"] / need * 100, "{:.1f} min", need / 100),
        ("Workout zones", "of workout time in another zone", d["zones_noop_unseen"]["mean"], d["zones_ours_unseen"]["mean"],
         None, 1),
    )
    h = TOP + ROW_H * len(rows) + 70
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" role="img" '
           f'aria-label="Distance from WHOOP, which is the zero line, as a percentage of each score\'s scale. '
           + "; ".join(f"{r[0]}: {a.ours_label} {r[3]:.1f} %, NOOP {r[2]:.1f} %" for r in rows) + '">',
           f'<rect width="{W}" height="{h}" rx="10" fill="{BG}"/>',
           '<style>text{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif}</style>',
           f'<text x="24" y="36" font-size="20" font-weight="600" fill="{INK}">How far each score lands from WHOOP</text>',
           f'<text x="24" y="59" font-size="13" fill="{MUTED}">WHOOP is the zero line. Mean distance on the same nights, as % of each '
           f'score\'s scale. NOOP main {d["noop_commit"]}; ours out-of-sample.</text>']
    axis_top, axis_bot = TOP - 22, TOP + ROW_H * len(rows) - 14
    for t in range(0, int(AXIS_MAX) + 1, 5):
        x = x_of(t)
        out += [f'<line x1="{x:.1f}" y1="{axis_top}" x2="{x:.1f}" y2="{axis_bot}" stroke="{GRID}" stroke-width="1"/>',
                f'<text x="{x:.1f}" y="{axis_bot + 18}" font-size="12" fill="{MUTED}" text-anchor="middle">{t} %</text>']
    x0 = x_of(0)
    out += [f'<line x1="{x0:.1f}" y1="{axis_top - 6}" x2="{x0:.1f}" y2="{axis_bot}" stroke="{WHOOP_C}" stroke-width="3"/>',
            f'<text x="{x0:.1f}" y="{axis_top - 12}" font-size="12" font-weight="600" fill="{WHOOP_C}" text-anchor="middle">WHOOP</text>']
    for i, (label, scale, noop, ours, fmt, unit) in enumerate(rows):
        y = TOP + i * ROW_H + 10
        xo, xn = x_of(ours), x_of(noop)
        out += [f'<text x="24" y="{y - 2}" font-size="14" font-weight="600" fill="{INK}">{label}</text>',
                f'<text x="24" y="{y + 15}" font-size="11.5" fill="{MUTED}">{scale}</text>',
                f'<line x1="{x0:.1f}" y1="{y}" x2="{xn:.1f}" y2="{y}" stroke="{NOOP_C}" stroke-width="2" stroke-opacity="0.35"/>',
                f'<circle cx="{xn:.1f}" cy="{y}" r="7" fill="{NOOP_C}"/>',
                f'<circle cx="{xo:.1f}" cy="{y}" r="7" fill="{OURS_C}"/>']
        n_txt = f"NOOP {noop:.1f} %" + (f" ({fmt.format(noop * unit)})" if fmt else "")
        o_txt = f"{ours:.1f} %" + (f" ({fmt.format(ours * unit)})" if fmt else "")
        if noop > AXIS_MAX:  # off the axis: an arrow at the edge carries the real value
            out += [f'<path d="M{xn + 9:.1f},{y - 6} l9,6 l-9,6 z" fill="{NOOP_C}"/>',
                    f'<text x="{xn - 10:.1f}" y="{y - 12}" font-size="12.5" font-weight="600" fill="{NOOP_C}" text-anchor="end">{n_txt}</text>']
        else:
            out.append(f'<text x="{xn:.1f}" y="{y - 12}" font-size="12.5" font-weight="600" fill="{NOOP_C}" text-anchor="middle">{n_txt}</text>')
        half = 3.6 * len(o_txt)  # about half the label's width at 12.5 px
        ox, anchor = (xo, "middle") if xo - half > x0 + 6 else (x0 + 6, "start")  # never across the WHOOP line
        out.append(f'<text x="{ox:.1f}" y="{y + 24}" font-size="12.5" font-weight="600" fill="{OURS_C}" text-anchor="{anchor}">{o_txt}</text>')
    y = h - 20
    out += [f'<circle cx="31" cy="{y - 4}" r="6" fill="{OURS_C}"/>',
            f'<text x="44" y="{y}" font-size="12.5" fill="{INK}">{a.ours_label} (score_formulas.py)</text>',
            f'<circle cx="331" cy="{y - 4}" r="6" fill="{NOOP_C}"/>',
            f'<text x="344" y="{y}" font-size="12.5" fill="{INK}">NOOP\'s own scorers</text>',
            f'<line x1="520" y1="{y - 10}" x2="520" y2="{y + 2}" stroke="{WHOOP_C}" stroke-width="3"/>',
            f'<text x="530" y="{y}" font-size="12.5" fill="{INK}">WHOOP, the reference</text>',
            "</svg>"]
    open(a.out, "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
