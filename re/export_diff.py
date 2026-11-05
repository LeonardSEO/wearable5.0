"""What changed between two WHOOP exports? Cycles added, removed or rescored, with old cycles flagged.

Settles whether WHOOP scores history sent to it again, and whether it double-counts it.

  python re/export_diff.py <older export.zip> <newer export.zip>
"""
from __future__ import annotations

import csv
import io
import os
import sys
import zipfile

KEY = "Cycle start time"
WATCH = ["Recovery score %", "Day Strain", "Sleep performance %", "Heart rate variability (ms)", "Resting heart rate (bpm)",
         "Asleep duration (min)", "Energy burned (cal)"]


def cycles(path: str) -> dict[str, dict]:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if os.path.basename(n).lower() == "physiological_cycles.csv")
        return {r[KEY]: r for r in csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig")))}


def diff(old: dict[str, dict], new: dict[str, dict]) -> dict:
    oldest = min(old, default="")
    shared = old.keys() & new.keys()
    return {
        "added_older": sorted(k for k in new.keys() - old.keys() if k < oldest),
        "added_newer": sorted(k for k in new.keys() - old.keys() if k >= oldest),
        "removed": sorted(old.keys() - new.keys()),
        "changed": {k: {c: (old[k].get(c), new[k].get(c)) for c in WATCH if old[k].get(c) != new[k].get(c)}
                    for k in sorted(shared) if any(old[k].get(c) != new[k].get(c) for c in WATCH)},
    }


def main() -> None:
    old, new = cycles(sys.argv[1]), cycles(sys.argv[2])
    d = diff(old, new)
    print(f"{len(old)} cycles before, {len(new)} now")
    print(f"\nolder than the first export ({len(d['added_older'])}): history WHOOP scored afterwards")
    for k in d["added_older"]:
        print(" ", k, {c: new[k].get(c) for c in WATCH[:3]})
    print(f"\nnew at the recent end: {len(d['added_newer'])}")
    for k in d["added_newer"]:
        print(" ", k, {c: new[k].get(c) for c in WATCH[:3]})
    print(f"\nremoved: {d['removed'] or 'none'}")
    print(f"\nrescored ({len(d['changed'])}); a Day Strain or energy jump on a re-sent cycle means double counting")
    for k, changes in d["changed"].items():
        print(" ", k, changes)


if __name__ == "__main__":
    main()
