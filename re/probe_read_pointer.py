"""Probe SET_READ_POINTER(33) on your own WHOOP 5.0 / MG: can the strap re-serve history it already trimmed?

Not used by the official app. Never sends FORCE_TRIM(25). Only drain, fetch, rewind and midstream acknowledge history;
fetch and midstream --ack-older move trim backwards (FINDINGS §17), which makes the strap serve that history again. Every received frame goes to
<out>/frames.jsonl. Quit NOOP and the WHOOP app first: the strap serves one central at a time.

  range          read write/trim/capacity only
  probe TARGET   try each payload, read back with GET_DATA_RANGE; stops as soon as the range changes
  fetch          re-read --span with an older acknowledgement during a burst, then optionally --restore trim
  drain          a normal sync with acknowledgements, up to --seconds
  midstream PAGE move the pointer while history is being served, no acknowledgement
  rewind STEP    IRREVERSIBLE RISK: acknowledge a page STEP behind trim, read back, then peek
  times --pages  move the pointer to each page and read the time stored there; no history is requested
  peek [TARGET]  request history without acknowledging, optionally after one payload (--payload N), and report the
                 record times and metadata cursors, then abort the transfer

Usage: .venv/bin/python wearable5.0/re/probe_read_pointer.py range --out whoop5-data/own_strap/probe
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import struct
import sys
import time

from bleak import BleakClient, BleakScanner

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402
from whoop5.framing import Reassembler, build_command  # noqa: E402

SERVICE = "fd4b0001-cce1-4033-93ce-002d5875f58a"
TO_STRAP = "fd4b0002-cce1-4033-93ce-002d5875f58a"
NOTIFY = ["fd4b0003-cce1-4033-93ce-002d5875f58a", "fd4b0004-cce1-4033-93ce-002d5875f58a",
          "fd4b0005-cce1-4033-93ce-002d5875f58a"]
CLIENT_HELLO, SEND_HISTORY, HISTORY_RESULT, ABORT_HISTORY, SET_READ_POINTER, GET_DATA_RANGE = 145, 22, 23, 20, 33, 34


def payloads(target: int) -> list[tuple[str, bytes]]:
    # Little-endian only: a byte-swapped or unknown-mode guess could point the strap anywhere.
    u32 = struct.pack("<I", target)
    return [("u32", u32), ("01+u32", b"\x01" + u32), ("u32+u32", u32 + bytes(4)), ("01+u32+u32", b"\x01" + u32 + bytes(4))]


class Strap:
    def __init__(self, client: BleakClient, out: str):
        self.c, self.seq, self.replies, self.records, self.meta = client, 0, [], [], []
        self.log = open(os.path.join(out, "frames.jsonl"), "a")
        self.streams = {u: Reassembler() for u in NOTIFY}

    def on_notify(self, uuid: str, data: bytearray) -> None:
        for f in self.streams[uuid].feed(bytes(data)):
            self.log.write(json.dumps({"hex": f.hex(), "t": time.time()}) + "\n")
            self.log.flush()
            d = decode_frame(f)
            if d.get("packet") == "COMMAND_RESPONSE" or f[8] == 36:
                self.replies.append(f)
            elif d.get("layout") is not None and d.get("unix_s"):
                self.records.append((d["layout"], d["unix_s"]))
            if d.get("packet") == "METADATA":
                self.meta.append((d.get("meta_type"), d.get("trim_cursor"), d.get("unix_s")))
                if d.get("meta_type") == 2:
                    self.end_token = f[21:29]

    async def send(self, command: int, args: bytes = b"") -> None:
        self.seq = (self.seq + 1) & 0xFF
        await self.c.write_gatt_char(TO_STRAP, build_command(command, args, sequence=self.seq), response=True)

    async def reply(self, command: int, seconds: float = 3.0, min_len: int = 0) -> bytes | None:
        """The newest reply to `command` after clearing older ones; None on timeout."""
        end = time.time() + seconds
        while time.time() < end:
            for f in reversed(self.replies):
                if f[10] == command and len(f) >= min_len:
                    return f
            await asyncio.sleep(0.05)
        return None

    async def data_range(self) -> dict | None:
        self.replies.clear()
        await self.send(GET_DATA_RANGE, b"\x00")
        f = await self.reply(GET_DATA_RANGE, min_len=78)
        if not f:
            return None
        w, u, cap = (struct.unpack_from("<I", f, 13 + o)[0] for o in (9, 13, 21))
        pointer, at_pointer = struct.unpack_from("<I", f, 18)[0], struct.unpack_from("<I", f, 62)[0]
        wrap = struct.unpack_from("<I", f, 30)[0]
        return {"wrap": wrap, "pointer": pointer, "pointer_time": dt.datetime.fromtimestamp(at_pointer).strftime("%m-%d %H:%M:%S"),
                "write": w, "trim": u, "capacity": cap, "behind": (w - u) % cap if cap else None, "hex": f.hex()}


def page_wrap(behind: int, r: dict) -> tuple[int, int]:
    """Page and wrap count `behind` pages before the write head; pages above it are from the previous ring pass."""
    wrap = struct.unpack_from("<I", bytes.fromhex(r["hex"]), 30)[0]
    page = r["write"] - behind
    return (page, wrap) if page >= 0 else (page + r["capacity"], wrap - 1)


async def time_of(s: "Strap", page: int, wrap: int) -> int:
    await s.send(SET_READ_POINTER, struct.pack("<II", page, wrap))
    await asyncio.sleep(0.15)
    r = await s.data_range()
    return struct.unpack_from("<I", bytes.fromhex(r["hex"]), 62)[0]


async def find_page(s: "Strap", when: float, r: dict) -> tuple[int, int]:
    """Binary search by distance behind the write head: stored times grow towards the head."""
    lo, hi = 1, r["capacity"] - 200
    while hi - lo > 8:
        mid = (lo + hi) // 2
        if await time_of(s, *page_wrap(mid, r)) > when:
            lo = mid
        else:
            hi = mid
    return page_wrap(hi, r)


async def run(args) -> int:
    os.makedirs(args.out, exist_ok=True)
    print("scanning ...", flush=True)
    dev = await BleakScanner.find_device_by_filter(lambda d, a: SERVICE in (a.service_uuids or []), timeout=20)
    if dev is None:
        print("strap not found: it is probably connected to the phone (quit the WHOOP app, Bluetooth off).")
        return 2
    print("found", dev.name, flush=True)
    async with BleakClient(dev, timeout=30) as c:
        s = Strap(c, args.out)
        for u in NOTIFY:
            await c.start_notify(u, lambda ch, d, u=u: s.on_notify(u, d))
        await s.send(CLIENT_HELLO, b"\x01")
        await asyncio.sleep(1)
        before = await s.data_range()
        print("range:", {k: v for k, v in (before or {}).items() if k != "hex"}, flush=True)
        if not before:
            return 3
        if args.mode == "fetch":
            # Re-read one time span: an older acknowledgement during a burst moves trim back; afterwards trim is
            # left where the span ended, or at --restore PAGE:WRAP.
            parse = lambda v: dt.datetime.strptime(v, "%Y-%m-%d %H:%M").timestamp()
            start, stop = parse(args.span[0]), parse(args.span[1])
            page, wrap = await find_page(s, start, before)
            print(f"start page {page} wrap {wrap} at", dt.datetime.fromtimestamp(await time_of(s, page, wrap)), flush=True)
            s.meta.clear()
            await s.send(SEND_HISTORY, b"\x00")
            end = time.time() + 15
            while time.time() < end and not any(m[0] == 2 for m in s.meta):
                await asyncio.sleep(0.05)
            if not any(m[0] == 2 for m in s.meta):
                print("no first chunk")
                return 5
            s.records.clear()
            s.meta.clear()
            await s.send(HISTORY_RESULT, b"\x01" + struct.pack("<II", page, wrap))
            acked, last, t0 = 0, time.time(), time.time()
            while time.time() - last < 25:
                ends = [m for m in s.meta if m[0] == 2]
                newest = max((t for _, t in s.records), default=0)
                if len(ends) > acked:
                    acked = len(ends)
                    last = time.time()
                    if acked % 20 == 0:
                        rate = (newest - start) / max(1, time.time() - t0)
                        print(f"chunk {acked} at {dt.datetime.fromtimestamp(newest)}, {rate:.1f}x realtime", flush=True)
                    if newest >= stop:
                        break
                    await s.send(HISTORY_RESULT, b"\x01" + s.end_token)
                await asyncio.sleep(0.02)
            times = [t for _, t in s.records]
            print(f"chunks {acked}, records {len(times)}, {dt.datetime.fromtimestamp(min(times))} .. "
                  f"{dt.datetime.fromtimestamp(max(times))}" if times else "no records", flush=True)
            if args.restore:
                p, w = (int(v) for v in args.restore.split(":"))
                await s.send(HISTORY_RESULT, b"\x01" + struct.pack("<II", p, w))
                await asyncio.sleep(1)
                print("restored to", p, w, flush=True)
            await s.send(ABORT_HISTORY, b"\x00")
            await asyncio.sleep(1)
            r = await s.data_range()
            print("end:", {k: v for k, v in (r or {}).items() if k != "hex"}, flush=True)
        elif args.mode == "drain":
            # A normal sync: every HISTORY_END is logged to frames.jsonl (flushed) before its acknowledgement.
            s.meta.clear()
            s.records.clear()
            await s.send(SEND_HISTORY, b"\x00")
            acked, last, end = 0, time.time(), time.time() + args.seconds
            while time.time() < end and time.time() - last < 15:
                ends = [m for m in s.meta if m[0] == 2]
                if len(ends) > acked:
                    acked = len(ends)
                    last = time.time()
                    await s.send(HISTORY_RESULT, b"\x01" + s.end_token)
                if any(m[0] == 3 for m in s.meta):
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(1)
            r = await s.data_range()
            print(f"chunks {acked}, records {len(s.records)}, end:", {k: v for k, v in (r or {}).items() if k != "hex"}, flush=True)
        elif args.mode == "midstream":
            s.records.clear()
            s.meta.clear()
            await s.send(SEND_HISTORY, b"\x00")
            end = time.time() + 10
            while time.time() < end and not any(m == 2 for m, _, _ in s.meta):
                await asyncio.sleep(0.05)
            fmt = lambda t: dt.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")
            first = len(s.records)
            print(f"first chunk: {first} records, meta {s.meta[:2]}", flush=True)
            if args.ack_older:
                wrap = struct.unpack_from("<I", s.end_token, 4)[0]
                print(f"in-burst ack to page {args.target} wrap {wrap}", flush=True)
                await s.send(HISTORY_RESULT, b"\x01" + struct.pack("<II", args.target, wrap))
                await asyncio.sleep(1)
                r = await s.data_range()
                print("right after:", {k: v for k, v in (r or {}).items() if k != "hex"}, flush=True)
            else:
                await s.send(SET_READ_POINTER, struct.pack("<I", args.target))
            if args.ack_current:
                await asyncio.sleep(0.3)
                print("ack token", s.end_token.hex(), flush=True)
                await s.send(HISTORY_RESULT, b"\x01" + s.end_token)
            await asyncio.sleep(args.seconds)
            later = [t for _, t in s.records[first:]]
            print(f"after 33 to page {args.target}: {len(later)} records"
                  + (f", {fmt(min(later))} .. {fmt(max(later))}" if later else ""), flush=True)
            print("metadata:", sorted({(m, u) for m, u, _ in s.meta}, key=str), flush=True)
            await s.send(ABORT_HISTORY, b"\x00")
            await asyncio.sleep(1)
            r = await s.data_range()
            print("end:", {k: v for k, v in (r or {}).items() if k != "hex"}, flush=True)
        elif args.mode == "rewind":
            if not 0 < args.target <= 1000 or args.target >= before["trim"]:
                print("rewind step must be 1-1000 pages and stay above 0; nothing sent")
                return 4
            page, wrap = before["trim"] - args.target, struct.unpack_from("<I", bytes.fromhex(before["hex"]), 30)[0]
            s.replies.clear()
            await s.send(HISTORY_RESULT, b"\x01" + struct.pack("<II", page, wrap))
            resp = await s.reply(HISTORY_RESULT, seconds=3)
            print(f"23 to page {page} wrap {wrap}: reply={resp.hex() if resp else None}", flush=True)
            after = await s.data_range()
            print("after:", {k: v for k, v in (after or {}).items() if k != "hex"}, flush=True)
            s.records.clear()
            s.meta.clear()
            await s.send(SEND_HISTORY, b"\x00")
            await asyncio.sleep(args.seconds)
            await s.send(ABORT_HISTORY, b"\x00")
            await asyncio.sleep(1)
            times = [t for _, t in s.records]
            fmt = lambda t: dt.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")
            print(f"records {len(times)}" + (f", {fmt(min(times))} .. {fmt(max(times))}" if times else ""), flush=True)
            print("metadata (type, trim, time):", [(m, u, fmt(t) if t else None) for m, u, t in s.meta[:6]], flush=True)
            end = await s.data_range()
            print("end:", {k: v for k, v in (end or {}).items() if k != "hex"}, flush=True)
        elif args.mode == "times":
            for target in args.pages:
                await s.send(SET_READ_POINTER, struct.pack("<I", target))
                await asyncio.sleep(0.3)
                r = await s.data_range()
                print(f"page {target}: pointer {r['pointer']} time {r['pointer_time']}", flush=True)
        elif args.mode == "probe":
            oldest = max(0, before["write"] - before["capacity"])
            if not oldest <= args.target < before["trim"]:
                print("target is not behind trim; nothing sent")
                return 4
            for label, pl in payloads(args.target):
                s.replies.clear()
                await s.send(SET_READ_POINTER, pl)
                resp = await s.reply(SET_READ_POINTER, seconds=2)
                after = await s.data_range()
                print(f"33 {label:12s} {pl.hex():20s} reply={resp.hex() if resp else None} -> "
                      f"{ {k: v for k, v in (after or {}).items() if k != 'hex'} }", flush=True)
                if not after or after["trim"] != before["trim"] or after["write"] != before["write"]:
                    print("range changed: stopping")
                    return 0
            print("no payload moved trim")
        elif args.mode == "peek":
            if args.target is not None:
                label, pl = payloads(args.target)[args.payload]
                if args.wrap is not None:
                    label, pl = f"page+wrap {args.wrap}", struct.pack("<II", args.target, args.wrap)
                await s.send(SET_READ_POINTER, pl)
                print(f"33 {label} {pl.hex()} reply={(await s.reply(SET_READ_POINTER, seconds=2) or b'').hex()}", flush=True)
            s.records.clear()
            s.meta.clear()
            moved = await s.data_range()
            print("before history:", {k: v for k, v in (moved or {}).items() if k != "hex"}, flush=True)
            await s.send(SEND_HISTORY, bytes([args.history_arg]))
            await asyncio.sleep(args.seconds)
            await s.send(ABORT_HISTORY, b"\x00")
            await asyncio.sleep(1)
            times = [t for _, t in s.records]
            fmt = lambda t: dt.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")
            print(f"records {len(times)}" + (f", {fmt(min(times))} .. {fmt(max(times))}" if times else ""), flush=True)
            print("metadata (type, trim, time):", [(m, u, fmt(t) if t else None) for m, u, t in s.meta[:8]], flush=True)
            after = await s.data_range()
            print("range after:", {k: v for k, v in (after or {}).items() if k != "hex"}, flush=True)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["range", "probe", "peek", "times", "rewind", "midstream", "drain", "fetch"])
    ap.add_argument("target", nargs="?", type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", type=int, nargs="*", default=[])
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--payload", type=int, default=0)
    ap.add_argument("--history-arg", type=int, default=0)
    ap.add_argument("--ack-current", action="store_true")
    ap.add_argument("--wrap", type=int)
    ap.add_argument("--span", nargs=2, help='"YYYY-MM-DD HH:MM" start and stop, local time')
    ap.add_argument("--restore", help="PAGE:WRAP to leave trim at after a fetch")
    ap.add_argument("--ack-older", action="store_true")
    a = ap.parse_args()
    if a.mode == "probe" and a.target is None:
        ap.error("probe needs TARGET")
    sys.exit(asyncio.run(run(a)))
