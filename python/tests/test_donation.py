"""The donation tool keeps sensor frames and drops anything that identifies a person or strap."""
import csv
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "re"))

from whoop5 import synth  # noqa: E402
from whoop5.decode import decode_frame  # noqa: E402
import prepare_donation  # noqa: E402


def hello_reply(serial: bytes = b"5AG0123456") -> bytes:
    body = bytearray(107)
    body[0] = 1
    body[14:14 + len(serial)] = serial
    return synth.wrap(bytes([36, 1, 145, 1, 1]) + bytes(body))


class Donation(unittest.TestCase):
    def test_identity_rules(self):
        keep = synth.r18()
        self.assertIsNone(prepare_donation.identity_reason(keep, decode_frame(keep)))
        hello = hello_reply()
        self.assertIn("identity", prepare_donation.identity_reason(hello, decode_frame(hello)))
        console = synth.console(1, "paired MGB0261172 ok")
        self.assertEqual(prepare_donation.identity_reason(console, decode_frame(console)), "serial or MAC pattern")
        mac = synth.console(2, "peer AA:BB:CC:DD:EE:FF")
        self.assertEqual(prepare_donation.identity_reason(mac, decode_frame(mac)), "serial or MAC pattern")

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "rejected_history.jsonl")
            with open(archive, "w") as f:
                for i, frame in enumerate([synth.r18(), synth.r18(), hello_reply(), synth.r26()]):
                    f.write(json.dumps({"capturedAtMs": 1000 + i, "trim": 1, "family": "whoop5",
                                        "frameHex": frame.hex()}) + "\n")
            export = os.path.join(tmp, "my_whoop_data.zip")
            with zipfile.ZipFile(export, "w") as z:
                z.writestr("physiological_cycles.csv", "Cycle start time,Blood oxygen %\n2026-07-09,96\n")
                z.writestr("workouts.csv", "Workout start time,Activity name,Notes\n2026-07-09,Running,secret\n")
                z.writestr("journal_entries.csv", "Question text,Notes\nAlcohol?,private\n")
            out = os.path.join(tmp, "donation")
            self.assertEqual(prepare_donation.main([archive, export, "--out", out]), 0)
            frames = [json.loads(line) for line in open(os.path.join(out, "frames.jsonl"))]
            self.assertEqual(len(frames), 2)  # duplicate R18 merged, hello removed
            manifest = json.load(open(os.path.join(out, "MANIFEST.json")))
            self.assertEqual(manifest["removed"]["identity reply (GET_HELLO)"], 1)
            self.assertEqual(sorted(os.listdir(os.path.join(out, "whoop_export"))),
                             ["physiological_cycles.csv", "workouts.csv"])
            rows = list(csv.reader(open(os.path.join(out, "whoop_export", "workouts.csv"))))
            self.assertEqual(rows[0], ["Workout start time", "Activity name"])
            self.assertTrue(os.path.exists(out + ".zip"))


if __name__ == "__main__":
    unittest.main()
