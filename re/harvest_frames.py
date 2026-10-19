"""Harvest every CRC-valid WHOOP 5/MG format-1 frame from a tree of checked-out repositories.

Scans text files for hex strings (contiguous or byte-separated) and binary files for raw bytes,
validates each candidate with the reference framing (header CRC16 + body CRC32), and writes one
de-duplicated JSONL with the sources each frame was seen in. CRC validation makes false positives
practically impossible; it does NOT tell captured frames from hand-constructed test vectors, so
the source path is kept for that judgement.

Usage: python re/harvest_frames.py <sources_dir> <out.jsonl>
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402
from whoop5.framing import FrameError, validate  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".build", "build", "DerivedData", "Pods", ".gradle", "target"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".mp4", ".mov", ".zip", ".gz", ".jar", ".so",
            ".dylib", ".a", ".mlmodel", ".mlpackage", ".ttf", ".otf", ".woff", ".woff2", ".ico", ".svg"}
MAX_BYTES = 60 * 1024 * 1024
HEX_RUN = re.compile(r"aa01(?:[0-9a-f]{2}){14,4100}", re.I)
SEP_RUN = re.compile(r"(?:0x)?aa[\s,:]+(?:0x)?01(?:[\s,:]+(?:0x)?[0-9a-f]{2}){14,4100}", re.I)


def frames_in_buffer(buf: bytes):
    """Yield every CRC-valid frame starting anywhere in `buf`."""
    i = buf.find(b"\xaa\x01")
    while i >= 0:
        if i + 4 <= len(buf):
            total = int.from_bytes(buf[i + 2:i + 4], "little") + 8
            if 16 <= total <= 4096 and i + total <= len(buf):
                cand = buf[i:i + total]
                try:
                    validate(cand)
                    yield cand
                except FrameError:
                    pass
        i = buf.find(b"\xaa\x01", i + 1)


def frames_in_text(text: str):
    for m in HEX_RUN.finditer(text):
        yield from frames_in_buffer(bytes.fromhex(m.group(0)[: len(m.group(0)) // 2 * 2]))
    for m in SEP_RUN.finditer(text):
        digits = re.sub(r"0x|[\s,:]", "", m.group(0), flags=re.I)
        yield from frames_in_buffer(bytes.fromhex(digits[: len(digits) // 2 * 2]))


def main(root: str, out_path: str) -> None:
    seen: dict[str, dict] = {}
    files_with_frames = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".mlpackage")]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    continue
                data = open(path, "rb").read()
            except OSError:
                continue
            rel = os.path.relpath(path, root)
            found = list(frames_in_buffer(data))
            try:
                found += list(frames_in_text(data.decode("utf-8")))
            except UnicodeDecodeError:
                pass
            if not found:
                continue
            files_with_frames += 1
            for f in found:
                key = hashlib.sha1(f).hexdigest()
                rec = seen.get(key)
                if rec is None:
                    d = decode_frame(f)
                    rec = seen[key] = {"sha1": key, "hex": f.hex(), "length": len(f), "packet_type": d["packet_type"],
                                       "packet": d["packet"], "layout": d.get("layout"),
                                       "unix_s": d.get("unix_s"), "sources": []}
                if rel not in rec["sources"]:
                    rec["sources"].append(rel)
    with open(out_path, "w") as out:
        for rec in sorted(seen.values(), key=lambda r: (r["packet_type"], r["layout"] or 0, r["unix_s"] or 0)):
            out.write(json.dumps(rec) + "\n")
    print(f"{len(seen)} unique CRC-valid frames from {files_with_frames} files -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
