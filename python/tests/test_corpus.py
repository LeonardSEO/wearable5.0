"""Opt-in regression over a local WHOOP 5/MG corpus (see re/README.md).

Set WHOOP5_CORPUS to a folder built by re/organize_corpus.py; skipped otherwise, so CI never needs
the data. Every frame must decode; real captures must have the layout's fixed length.
"""
import collections
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from whoop5.decode import decode_frame  # noqa: E402

CORPUS = os.environ.get("WHOOP5_CORPUS")
# Paths whose frames are hand-made test vectors, not strap output.
SYNTHETIC_HINTS = ("synthetic", "_oracle.json", ".mavconn", "fixtures/connectors")


@unittest.skipUnless(CORPUS, "set WHOOP5_CORPUS to run corpus regression")
class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(CORPUS, "frames", "all_frames.jsonl")
        cls.records = [json.loads(line) for line in open(path)]

    def test_every_frame_decodes(self):
        failures = []
        for r in self.records:
            try:
                decode_frame(bytes.fromhex(r["hex"]))
            except Exception as e:  # noqa: BLE001 - report every failure
                failures.append((r["sha1"], repr(e)))
        self.assertEqual(failures, [])

    def test_real_records_have_fixed_lengths(self):
        odd = []
        for r in self.records:
            d = decode_frame(bytes.fromhex(r["hex"]))
            if str(d.get("record", "")).endswith("unexpected_length"):
                if not all(any(h in s for h in SYNTHETIC_HINTS) for s in r["sources"]):
                    odd.append((d["record"], d["length"], r["sources"][:2]))
        self.assertEqual(odd, [])

    def test_layout_census(self):
        census = collections.Counter()
        for r in self.records:
            d = decode_frame(bytes.fromhex(r["hex"]))
            census[d.get("record", d["packet"])] += 1
        unknown = {k: v for k, v in census.items() if k.startswith("UNKNOWN")}
        print(f"\ncorpus: {len(self.records)} frames; unknown layouts: {unknown or 'none'}")
        self.assertGreater(len(self.records), 0)


if __name__ == "__main__":
    unittest.main()
