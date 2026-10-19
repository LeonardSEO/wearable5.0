"""Experimental metrics on synthetic inputs. The Swift twin (ParityTests.testExperimental*) uses the same
inputs and expected values; change both together."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from whoop5.experimental import (bandpass, find_peaks, hr_from_r26, respiratory_rate,  # noqa: E402
                                 skin_temp_baseline, sleep_periods)


def state(t):
    if (300 <= t < 2000 and not 1000 <= t < 1060) or 2900 <= t < 4000:
        return "SLEEP"
    return "STILL" if t % 2 else "WAKE"


def night():
    """4000 s: wake, sleep with a 60 s awakening, 900 s wake, then a 1100 s sleep run (too short)."""
    return [{"layout": 18, "unix_s": 10000 + t, "band_state": state(t),
             "heart_rate": 0 if t == 500 else (48 + t % 9 if state(t) == "SLEEP" else 70),
             "skin_temp_c": (3300 + t // 100) / 100} for t in range(4000)]


def r26_records():
    x = [100000 + 2 * i - (800 if i % 20 < 3 else 0) for i in range(30 * 25)]  # a dip every 0.8 s = 75 bpm
    recs = [{"layout": 26, "unix_s": 5000 + k, "record_index": k, "burst_counter": 3, "samples": x[25 * k:25 * k + 25]}
            for k in range(30)]
    recs.append(dict(recs[4]))  # duplicate record_index: dropped
    recs += [{"layout": 26, "unix_s": 6000 + k, "record_index": 100 + k, "burst_counter": 4,
              "samples": x[25 * k:25 * k + 25]} for k in range(5)]  # 5 s burst: too short
    return recs


class SleepPeriods(unittest.TestCase):
    def test_smoothing_merge_and_minimum(self):
        p = sleep_periods(night())
        self.assertEqual(len(p), 1)
        p = p[0]
        self.assertEqual((p["onset_unix"], p["offset_unix"], p["duration_s"], p["asleep_s"], p["records"], p["hr_min"]),
                         (10300, 11999, 1700, 1640, 1700, 48))
        self.assertAlmostEqual(p["hr_mean"], 52.63802236609771, places=9)

    def test_empty(self):
        self.assertEqual(sleep_periods([]), [])


class RespiratoryRate(unittest.TestCase):
    def test_four_beat_cycle_is_15_per_min(self):
        rr = [950, 1000, 1050, 1000] * 45
        rr[20], rr[60] = 250, 1500  # out of range / step artefacts are dropped
        w = respiratory_rate(rr)
        self.assertEqual([(x["start_s"], x["end_s"], x["beats"]) for x in w], [(0.0, 60.0, 59), (60.0, 120.0, 60)])
        self.assertAlmostEqual(w[0]["breaths_per_min"], 15.3, places=9)
        self.assertAlmostEqual(w[1]["breaths_per_min"], 15.0, places=9)
        self.assertAlmostEqual(w[0]["peak_fraction"], 0.16599567526638082, places=6)
        self.assertAlmostEqual(w[1]["peak_fraction"], 0.1985737846532536, places=6)

    def test_flat_and_short(self):
        self.assertEqual(respiratory_rate([1000] * 50), [])
        w = respiratory_rate([1000] * 70)
        self.assertEqual(len(w), 1)
        self.assertIsNone(w[0]["breaths_per_min"])


class SkinTemp(unittest.TestCase):
    def test_night_stats(self):
        s = skin_temp_baseline(night())[0]
        self.assertEqual((s["onset_unix"], s["offset_unix"], s["samples"], s["min_c"], s["max_c"]),
                         (10300, 11999, 1700, 33.03, 33.19))
        self.assertAlmostEqual(s["mean_c"], 33.11, places=9)
        self.assertAlmostEqual(s["sd_c"], 0.0489897948556632, places=9)
        self.assertIsNone(s["deviation_c"])
        self.assertAlmostEqual(skin_temp_baseline(night(), baseline_c=33.0)[0]["deviation_c"], 0.11, places=9)

    def test_rolling_baseline(self):
        periods = [{"onset_unix": 10000, "offset_unix": 10999}, {"onset_unix": 11000, "offset_unix": 11999}]
        a, b = skin_temp_baseline(night(), periods=periods)
        self.assertAlmostEqual(a["mean_c"], 33.045, places=9)
        self.assertIsNone(a["deviation_c"])
        self.assertAlmostEqual(b["baseline_c"], 33.045, places=9)
        self.assertAlmostEqual(b["deviation_c"], 0.1, places=9)


class HrFromR26(unittest.TestCase):
    def test_pulse_train(self):
        out = hr_from_r26(r26_records())
        self.assertEqual([(b["start_unix"], b["end_unix"], b["seconds"], b["burst_counter"], b["beats"]) for b in out],
                         [(5000, 5029, 30, 3, 37), (6000, 6004, 5, 4, 0)])
        self.assertAlmostEqual(out[0]["heart_rate_bpm"], 75.0, places=9)
        self.assertIsNone(out[1]["heart_rate_bpm"])

    def test_find_peaks_matches_scipy(self):
        y = [0, 2, 1, 3, 1, 0, 5, 4, 5, 0]  # expected values from scipy.signal.find_peaks
        self.assertEqual(find_peaks(y), [1, 3, 6, 8])
        self.assertEqual(find_peaks(y, distance=3), [3, 8])
        self.assertEqual(find_peaks(y, prominence=4), [6, 8])

    def test_bandpass_passes_1hz_rejects_drift(self):
        import math
        one = bandpass([math.sin(2 * math.pi * i / 25) for i in range(250)], 25, 0.6, 3.3)
        self.assertGreater(max(one[50:200]), 0.85)
        slow = bandpass([math.sin(2 * math.pi * 0.1 * i / 25) for i in range(250)], 25, 0.6, 3.3)
        self.assertLess(max(abs(v) for v in slow[50:200]), 0.01)


if __name__ == "__main__":
    unittest.main()
