"""Which protocol names does this library have that NOOP lacks, and the other way round?

Compares commands, events and packet types between protocol/whoop5_protocol.json and NOOP's whoop_protocol.json.
Facts only; NOOP's file stays in NOOP.

  python re/compare_noop.py <noop whoop_protocol.json>
  git -C noop show upstream/main:Packages/WhoopProtocol/Sources/WhoopProtocol/Resources/whoop_protocol.json > /tmp/n.json
"""
from __future__ import annotations

import json
import os
import sys

TABLES = {"commands": "CommandNumber", "events": "EventNumber", "packet_types": "PacketType"}


def diff_table(ours: dict, theirs: dict) -> dict:
    return {
        "only_ours": {k: ours[k] for k in sorted(set(ours) - set(theirs), key=int)},
        "only_noop": {k: theirs[k] for k in sorted(set(theirs) - set(ours), key=int)},
        "renamed": {k: (ours[k], theirs[k]) for k in sorted(set(ours) & set(theirs), key=int) if ours[k] != theirs[k]},
    }


def compare(ours: dict, noop: dict) -> dict:
    numbered = lambda table: {k: v for k, v in table.items() if k.isdigit()}  # our tables also hold request_bodies etc.
    return {t: diff_table(numbered(ours[t]), noop["enums"][e]) for t, e in TABLES.items()}


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ours = json.load(open(os.path.join(here, "..", "protocol", "whoop5_protocol.json")))
    for table, d in compare(ours, json.load(open(sys.argv[1]))).items():
        print(f"## {table}: {len(d['only_ours'])} only here, {len(d['only_noop'])} only in NOOP, {len(d['renamed'])} named differently")
        for kind, rows in d.items():
            for k, v in rows.items():
                print(f"  {kind:9} {k:>4} {v}")


if __name__ == "__main__":
    main()
