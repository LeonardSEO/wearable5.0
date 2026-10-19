"""Turn your own WHOOP 5.0 / MG data into a privacy-safe donation for wearable5.0.

Accepts any mix of:
  - NOOP's raw history archive (`rejected_history.jsonl`, lines with "frameHex")
  - NOOP strap logs / capture files (.txt) and other JSONL files containing frame hex
  - HCI captures: iOS PacketLogger (.pklg) or Android `btsnoop_hci.log`
  - Your WHOOP data export (the .zip from app.whoop.com, or its unzipped folder)

and writes a donation folder plus a .zip next to it:
  frames.jsonl          CRC-valid WHOOP 5/MG frames only, de-duplicated (WHOOP 4.0 frames cannot pass)
  whoop_export/*.csv    physiological cycles, sleeps and workouts, without free-text columns
  MANIFEST.json         counts per frame type, time span, firmware version, what was removed
  README.txt            what the donation contains

Removed automatically:
  - frames that carry identity: GET_HELLO / GET_HELLO_HARVARD replies (serial, identity blocks), advertising
    name get/set, battery-pack info replies and events, the identity events 61/62
  - any frame whose bytes contain a strap-serial pattern (5AG…, 5AM…, MGB…) or a MAC address
  - everything else in an HCI capture (phone addresses, other devices, pairing keys): only WHOOP frames
    are extracted
  - the WHOOP journal export and any notes / free-text column
Dates and times are kept: they are what lets frames be lined up with the export.

Usage:
  python re/prepare_donation.py <file-or-folder> [...] [--out DIR]
Example:
  python re/prepare_donation.py rejected_history.jsonl noop-strap-log-*.txt my_whoop_data.zip --out donation
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import sys
import zipfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from harvest_frames import frames_in_buffer, frames_in_text  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402

SERIAL = re.compile(rb"(?:5A[GM]|MGB)[0-9]{6,}")
MAC_TEXT = re.compile(rb"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
IDENTITY_COMMANDS = {35, 145, 76, 77, 140, 141, 151}   # hello, advertising name, battery-pack info
IDENTITY_EVENTS = {61, 62, 109}                        # events that embed a serial / pack identity
EXPORT_FILES = {
    "physiological_cycles.csv": "physiological_cycles.csv", "physiologische_zyklen.csv": "physiological_cycles.csv",
    "sleeps.csv": "sleeps.csv", "schlaf.csv": "sleeps.csv",
    "workouts.csv": "workouts.csv", "trainings.csv": "workouts.csv",
}
FREE_TEXT = re.compile(r"note|notiz|question|frage|answer|antwort|comment|kommentar|email|e-mail", re.I)


def identity_reason(frame: bytes, d: dict) -> str | None:
    t = d["packet_type"]
    if t == 36 and d.get("command") in IDENTITY_COMMANDS:
        return f"identity reply ({d.get('command_name')})"
    if t == 35 and frame[10] in {77, 140}:
        return "advertising-name write"
    if t == 48 and d.get("event") in IDENTITY_EVENTS:
        return f"identity event ({d.get('event_name')})"
    if SERIAL.search(frame) or MAC_TEXT.search(frame):
        return "serial or MAC pattern"
    return None


def firmware_from_hello(d: dict) -> str | None:
    f = d.get("fields") or {}
    if d.get("command") == 145 and f.get("fw_major"):
        return f"{f['fw_major']}.{f['fw_minor']}.{f['fw_patch']}.{f.get('fw_build') or 0}"
    return None


def frames_from_file(path: str):
    """Yield (frame bytes, captured_at_ms or None) from one input file."""
    name = os.path.basename(path).lower()
    data = open(path, "rb").read()
    if name.endswith(".pklg") or data[:8] == b"btsnoop\0":
        from pklg_extract import whoop_frames  # only WHOOP frames leave the capture
        for ts, _direction, _handle, f in whoop_frames(data):
            yield f, round(ts * 1000)
        return
    if name.endswith(".jsonl") or name.endswith(".json"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            h = obj.get("frameHex") or obj.get("hex")
            if isinstance(h, str):
                for f in frames_in_buffer(bytes.fromhex(h)):
                    yield f, obj.get("capturedAtMs")
        if text and not any(k in text for k in ('"frameHex"', '"hex"')):
            for f in frames_in_text(text):
                yield f, None
        return
    for f in frames_in_buffer(data):
        yield f, None
    try:
        for f in frames_in_text(data.decode("utf-8", errors="ignore")):
            yield f, None
    except ValueError:
        pass


def copy_export(src, out_dir: str, removed: Counter) -> list[str]:
    """Copy allowed WHOOP export CSVs from a folder or zip, dropping free-text columns."""
    written = []
    entries = []
    if isinstance(src, zipfile.ZipFile):
        entries = [(n, lambda n=n: src.read(n)) for n in src.namelist()]
    else:
        for root, _, files in os.walk(src):
            entries += [(os.path.join(root, n), lambda p=os.path.join(root, n): open(p, "rb").read()) for n in files]
    for path, read in entries:
        base = os.path.basename(path).lower()
        if base not in EXPORT_FILES:
            if base.endswith(".csv"):
                removed[f"export file not copied: {base}"] += 1
            continue
        rows = list(csv.reader(io.StringIO(read().decode("utf-8-sig", errors="replace"))))
        if not rows:
            continue
        keep = [i for i, h in enumerate(rows[0]) if not FREE_TEXT.search(h)]
        for i, h in enumerate(rows[0]):
            if i not in keep:
                removed[f"export column removed: {h}"] += 1
        os.makedirs(os.path.join(out_dir, "whoop_export"), exist_ok=True)
        dest = os.path.join(out_dir, "whoop_export", EXPORT_FILES[base])
        with open(dest, "w", newline="") as fh:
            w = csv.writer(fh)
            for r in rows:
                w.writerow([r[i] for i in keep if i < len(r)])
        written.append(EXPORT_FILES[base])
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default="whoop5-donation")
    a = ap.parse_args(argv)

    out = a.out
    if os.path.exists(out):
        print(f"{out} already exists; choose another --out", file=sys.stderr)
        return 2
    os.makedirs(out)
    seen, kept, types, removed, firmware, exports = {}, [], Counter(), Counter(), set(), []
    times = []

    def consider(frame: bytes, captured):
        d = decode_frame(frame)
        fw = firmware_from_hello(d)
        if fw:
            firmware.add(fw)
        why = identity_reason(frame, d)
        if why:
            removed[why] += 1
            return
        key = hashlib.sha1(frame).hexdigest()
        if key in seen:
            return
        seen[key] = True
        rec = {"hex": frame.hex()}
        if captured is not None:
            rec["captured_at_ms"] = captured
        kept.append(rec)
        types[d["packet"] + (f"/R{d['layout']}" if d["packet_type"] in (43, 47) else "")] += 1
        if d.get("unix_s") and 1_600_000_000 < d["unix_s"] < 2_100_000_000:
            times.append(d["unix_s"])

    for inp in a.inputs:
        paths = []
        if os.path.isdir(inp):
            if any(os.path.basename(f).lower() in EXPORT_FILES for _, _, fs in os.walk(inp) for f in fs):
                exports += copy_export(inp, out, removed)
            paths = [os.path.join(r, f) for r, _, fs in os.walk(inp) for f in fs]
        elif zipfile.is_zipfile(inp):
            with zipfile.ZipFile(inp) as z:
                if any(os.path.basename(n).lower() in EXPORT_FILES for n in z.namelist()):
                    exports += copy_export(z, out, removed)
                    continue
                tmp = os.path.join(out, ".unzipped")
                z.extractall(tmp)
                paths = [os.path.join(r, f) for r, _, fs in os.walk(tmp) for f in fs]
        else:
            paths = [inp]
        for p in paths:
            if os.path.basename(p).lower() in EXPORT_FILES:
                continue
            for frame, captured in frames_from_file(p):
                consider(frame, captured)
    shutil.rmtree(os.path.join(out, ".unzipped"), ignore_errors=True)

    with open(os.path.join(out, "frames.jsonl"), "w") as fh:
        for rec in kept:
            fh.write(json.dumps(rec) + "\n")
    span = [dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat() for t in (min(times), max(times))] if times else None
    manifest = {"tool": "wearable5.0/re/prepare_donation.py", "frames": len(kept), "frame_types": dict(types.most_common()),
                "record_time_span_utc": span, "firmware": sorted(firmware), "whoop_export_files": sorted(set(exports)),
                "removed": dict(removed.most_common())}
    with open(os.path.join(out, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    with open(os.path.join(out, "README.txt"), "w") as fh:
        fh.write("WHOOP 5.0 / MG data donation for https://github.com/LeonardSEO/wearable5.0\n\n"
                 "frames.jsonl contains CRC-valid strap frames only (sensor records, events, command replies).\n"
                 "Identity-bearing frames, serial numbers and MAC addresses were removed; see MANIFEST.json.\n"
                 "whoop_export/ (if present) holds the WHOOP export without notes or journal entries.\n"
                 "Dates are kept so frames can be compared with the export. Check the files before sharing.\n")
    shutil.make_archive(out, "zip", out)
    print(json.dumps(manifest, indent=2))
    print(f"\nwrote {out}/ and {out}.zip; check them, then share the .zip (see re/README.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
