"""What does the official WHOOP app send to a 5/MG strap, and in what order?

Input: frames.jsonl written by re/pklg_extract.py from an HCI capture of the official app.
Reports the command cadence of history syncs, the feature-flag and device-config key exchanges, and
every SET_FF_VALUE / SET_DEVICE_CONFIG_VALUE write (key and value). Contains no identifiers.

Usage: python re/analyze_official_sync.py <frames.jsonl>
"""
from __future__ import annotations

import collections
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame, schema  # noqa: E402


def text(b: bytes) -> str:
    return re.sub(rb"\x00.*$", b"", b, flags=re.S).decode("latin1")


def main(path: str) -> None:
    names = schema()["commands"]
    rows = [json.loads(line) for line in open(path)]
    t0 = rows[0]["ts"]
    tx = [(r["ts"] - t0, bytes.fromhex(r["hex"])) for r in rows if r["dir"] == "tx"]
    cmds = [(t, raw[10], raw[11:-4]) for t, raw in tx if raw[8] == 35]
    print(f"capture span {rows[-1]['ts'] - t0:.0f} s; phone->strap commands: {len(cmds)}")
    print("command counts:", dict(collections.Counter(names.get(str(c), c) for _, c, _ in cmds).most_common()))

    starts = [t for t, c, _ in cmds if c == 34]  # GET_DATA_RANGE opens each sync
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    print(f"\nsync rounds (one GET_DATA_RANGE each): {len(starts)}; interval median {statistics.median(gaps):.0f} s "
          f"(min {min(gaps):.0f}, max {max(gaps):.0f})")
    first = [names.get(str(c), c) for t, c, _ in cmds if starts[0] - 1 <= t <= starts[0] + 12]
    print("typical round:", " -> ".join(dict.fromkeys(first)))

    print("\nfeature-flag / device-config writes (key = value):")
    writes = collections.Counter()
    for _, c, a in cmds:
        if c in (119, 120) and len(a) >= 65:
            writes[(names[str(c)], text(a[1:33]), text(a[33:65]))] += 1
    for (cmd, key, val), n in sorted(writes.items()):
        print(f"  {cmd:24s} {key:32s} = {val!r}  x{n}")

    print("\nkey enumeration replies (index, key):")
    keys = {}
    for r in rows:
        raw = bytes.fromhex(r["hex"])
        if r["dir"] == "rx" and raw[8] == 36 and raw[10] in (116, 118):
            d = decode_frame(raw)
            b = bytes.fromhex(d["body_hex"])
            keys[(d["command_name"], b[1])] = text(b[3:40])
    for (cmd, idx), key in sorted(keys.items()):
        print(f"  {cmd:24s} index {idx:3d}  {key}")


if __name__ == "__main__":
    main(sys.argv[1])
