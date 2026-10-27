"""Export the raw frames NOOP kept (table `rawBatch`, filled when `enableRawCapture` is on) as frames.jsonl.

Reads a read-only snapshot of NOOP's whoop.sqlite, so it is safe while the app is running. The output has one
{"hex": ...} line per frame and feeds prepare_donation.py, the Python decoder and the Kotlin corpus report.

Usage:
  python re/export_noop_db.py [--db ~/Library/Application\\ Support/OpenWhoop/whoop.sqlite] --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import struct
import sys
import zlib
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402

DEFAULT_DB = os.path.expanduser("~/Library/Application Support/OpenWhoop/whoop.sqlite")


def unpack_frames(blob: bytes) -> list[bytes]:
    """NOOP's RawOutbox layout: [count u32 LE]{[len u32 LE][bytes]} x count, optionally zlib-compressed."""
    try:
        blob = zlib.decompress(blob)
    except zlib.error:
        pass
    (count,), off, out = struct.unpack_from("<I", blob, 0), 4, []
    for _ in range(count):
        (n,) = struct.unpack_from("<I", blob, off)
        out.append(blob[off + 4: off + 4 + n])
        off += 4 + n
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    snap = os.path.join(args.out, "whoop.sqlite")
    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as src, sqlite3.connect(snap) as dst:
        src.backup(dst)
    db = sqlite3.connect(snap)
    seen, kinds = set(), Counter()
    with open(os.path.join(args.out, "frames.jsonl"), "w") as fh:
        for batch_id, blob in db.execute("SELECT batchId, framesBlob FROM rawBatch ORDER BY capturedAt, rowid"):
            for f in unpack_frames(blob):
                if f in seen:
                    continue
                seen.add(f)
                try:
                    d = decode_frame(f)
                    kinds[f"R{d['layout']}" if d.get("layout") is not None else d.get("packet", "?")] += 1
                except Exception:
                    kinds["undecodable"] += 1
                fh.write(json.dumps({"hex": f.hex(), "batch": batch_id}) + "\n")
    print(f"{len(seen)} unique frames -> {args.out}/frames.jsonl")
    for k, n in kinds.most_common():
        print(f"  {k}: {n}")


if __name__ == "__main__":
    frames = [b"\xaa\x01", b"\x01\x02\x03"]
    packed = struct.pack("<I", 2) + b"".join(struct.pack("<I", len(f)) + f for f in frames)
    assert unpack_frames(packed) == frames and unpack_frames(zlib.compress(packed)) == frames
    main()
