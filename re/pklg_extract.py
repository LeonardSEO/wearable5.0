"""Extract WHOOP 5/MG frames from an HCI capture: Apple PacketLogger (.pklg) or Android btsnoop.

Parses PacketLogger records, reassembles ACL → L2CAP → ATT, keeps notifications/indications
(strap → phone) and writes (handle-value writes, phone → strap), reassembles each characteristic
handle's byte stream into format-1 frames, and keeps only CRC-valid ones.

Usage: python re/pklg_extract.py <capture.pklg|btsnoop_hci.log> <out.jsonl>
"""
from __future__ import annotations

import json
import os
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
from whoop5.decode import decode_frame  # noqa: E402
from whoop5.framing import Reassembler  # noqa: E402

ATT_NOTIFY, ATT_INDICATE, ATT_WRITE_REQ, ATT_WRITE_CMD = 0x1B, 0x1D, 0x12, 0x52


def records(blob: bytes):
    """PacketLogger: u32 BE length, u32 BE secs, u32 BE usecs, u8 type, payload."""
    i = 0
    while i + 13 <= len(blob):
        length = struct.unpack_from(">I", blob, i)[0]
        if length < 9 or i + 4 + length > len(blob):
            break
        secs, usecs = struct.unpack_from(">II", blob, i + 4)
        ptype = blob[i + 12]
        yield secs + usecs / 1e6, ptype, blob[i + 13:i + 4 + length]
        i += 4 + length


def btsnoop_records(blob: bytes):
    """btsnoop v1, H4 datalink (1002): 24-byte record header, then an H4 packet-type byte."""
    if blob[:8] != b"btsnoop\0" or struct.unpack_from(">I", blob, 12)[0] != 1002:
        raise ValueError("unsupported btsnoop datalink")
    i = 16
    while i + 24 <= len(blob):
        _orig, incl, flags, _drops, ts = struct.unpack_from(">IIIIq", blob, i)
        data = blob[i + 24:i + 24 + incl]
        i += 24 + incl
        if data[:1] == b"\x02":  # H4 ACL
            yield ts / 1e6, (0x03 if flags & 1 else 0x02), data[1:]


def main(path: str, out_path: str) -> None:
    blob = open(path, "rb").read()
    source = btsnoop_records(blob) if blob[:8] == b"btsnoop\0" else records(blob)
    l2cap: dict[tuple, bytearray] = {}
    need: dict[tuple, int] = {}
    streams: dict[tuple, Reassembler] = defaultdict(Reassembler)
    frames = []
    for ts, ptype, data in source:
        if ptype not in (0x02, 0x03) or len(data) < 4:   # 2 = ACL sent, 3 = ACL received
            continue
        direction = "rx" if ptype == 0x03 else "tx"
        handle_flags, acl_len = struct.unpack_from("<HH", data, 0)
        conn, pb = handle_flags & 0x0FFF, (handle_flags >> 12) & 0x3
        body = data[4:4 + acl_len]
        key = (direction, conn)
        if pb in (0x0, 0x2):  # first fragment
            if len(body) < 4:
                continue
            need[key] = struct.unpack_from("<H", body, 0)[0] + 4
            l2cap[key] = bytearray(body)
        elif key in l2cap:     # continuation
            l2cap[key] += body
        else:
            continue
        if len(l2cap[key]) < need[key]:
            continue
        pdu = bytes(l2cap.pop(key))
        cid = struct.unpack_from("<H", pdu, 2)[0]
        att = pdu[4:need.pop(key)]
        if cid != 0x0004 or len(att) < 3:
            continue
        op = att[0]
        if op not in (ATT_NOTIFY, ATT_INDICATE, ATT_WRITE_REQ, ATT_WRITE_CMD):
            continue
        att_handle = struct.unpack_from("<H", att, 1)[0]
        for f in streams[(direction, conn, att_handle)].feed(att[3:]):
            d = decode_frame(f)
            frames.append({"ts": round(ts, 6), "dir": direction, "att_handle": att_handle, "hex": f.hex(),
                           "packet": d["packet"], "layout": d.get("layout")})
    with open(out_path, "w") as out:
        for r in frames:
            out.write(json.dumps(r) + "\n")
    from collections import Counter
    c = Counter(r["packet"] + (f"/L{r['layout']}" if r["layout"] is not None and r["packet"].endswith("DATA") else "")
                for r in frames)
    print(f"{len(frames)} CRC-valid frames -> {out_path}")
    for k, v in c.most_common():
        print(f"{v:7d} {k}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
