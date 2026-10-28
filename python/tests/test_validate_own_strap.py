import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "re"))
import validate_own_strap as v  # noqa: E402

EXPORT = """Cycle start time,Cycle end time,Cycle timezone,Resting heart rate (bpm),Heart rate variability (ms),Skin temp (celsius),Blood oxygen %,Sleep onset,Wake onset,Respiratory rate (rpm)
2026-10-28 09:00:00,2026-10-29 07:00:00,UTC+01:00,52,61,33.4,96.1,2026-10-28 23:10:00,2026-10-29 07:00:00,14.6
2026-10-29 07:00:00,,UTC+01:00,,,,,,,
"""


class ValidateOwnStrapTest(unittest.TestCase):
    def test_export_is_parsed_with_its_zone_and_rows_without_sleep_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "physiological_cycles.csv"), "w").write(EXPORT)
            nights = v.load_export(d)
        self.assertEqual(len(nights), 1)
        n = nights[0]
        self.assertEqual(n["onset"], 1793225400)  # 23:10 at UTC+01:00 = 22:10 UTC
        self.assertEqual(n["wake"] - n["onset"], 7 * 3600 + 50 * 60)
        self.assertEqual((n["spo2"], n["resp_rate"], n["resting_hr"], n["hrv"], n["skin_temp"]),
                         (96.1, 14.6, 52.0, 61.0, 33.4))

    def test_pairing_takes_the_nearest_onset_within_three_hours(self):
        ours = [{"onset": 1000}, {"onset": 1000 + 2 * 3600}, {"onset": 100000}]
        whoop = [{"onset": 1000 + 2 * 3600 + 60}, {"onset": 50000}]
        self.assertEqual(v.pair(ours, whoop), [(ours[1], whoop[0])])

    def test_verdicts_follow_the_fixed_criteria(self):
        self.assertEqual(v.verdict("spo2", 0.8), "PASS")
        self.assertEqual(v.verdict("spo2", 1.2), "FAIL")
        self.assertEqual(v.verdict("spo2", 0.8, enough=False), "WAITING")
        self.assertEqual(v.verdict("rr_unit", 1.01), "PASS")
        self.assertEqual(v.verdict("rr_unit", 1.32), "FAIL")
        self.assertEqual(v.verdict("hrv", 0.75), "PASS")
        self.assertEqual(v.verdict("hrv", None), "WAITING")


if __name__ == "__main__":
    unittest.main()
