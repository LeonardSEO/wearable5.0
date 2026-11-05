import importlib.util
import math
import os
import random
import unittest

try:
    import numpy  # noqa: F401
except ImportError:
    numpy = None

_path = os.path.join(os.path.dirname(__file__), "..", "..", "re", "score_search.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_search", _path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nights(n, seed):
    r = random.Random(seed)
    return [{"hrv": r.gauss(60, 12), "rhr": r.gauss(55, 4), "resp": r.gauss(15, 1), "sleep_perf": r.uniform(50, 100),
             "skin_temp": r.gauss(34, 0.4), "spo2": r.gauss(96, 1), "asleep": r.uniform(300, 500),
             "need": r.uniform(400, 520), "start": str(i)} for i in range(n)]


@unittest.skipUnless(numpy, "needs numpy")
class Search(unittest.TestCase):
    def test_finds_a_planted_baseline_relative_formula(self):
        ss = _load()
        rows = _nights(120, 1)
        z = ss.baseline_features(numpy.array([r["hrv"] for r in rows]))["z14"]
        for r, zi in zip(rows, z):
            r["recovery"] = math.nan if math.isnan(zi) else round(100 / (1 + math.exp(-(0.2 + 1.3 * zi))))
        res = ss.run_target(rows, "recovery", max_terms=1, beam=20, shuffles=3)
        self.assertEqual(res["verdict"], "FORMULA")
        self.assertIn("z14(hrv)", res["final"])

    def test_rejects_scores_unrelated_to_the_inputs(self):
        ss = _load()
        rows = _nights(80, 2)
        r = random.Random(3)
        for row in rows:
            row["recovery"] = r.uniform(0, 100)
        self.assertEqual(ss.run_target(rows, "recovery", max_terms=2, beam=20, shuffles=3)["verdict"], "NONE")

    def test_refuses_to_fit_too_few_cycles(self):
        ss = _load()
        rows = _nights(5, 4)
        for row in rows:
            row["recovery"] = 50.0 + row["hrv"] / 10
        self.assertEqual(ss.run_target(rows, "recovery", 3, 20, 3)["verdict"], "TOO_FEW")

    def test_recovery_never_sees_todays_strain(self):
        ss = _load()
        self.assertNotIn("strain", ss.TARGETS["recovery"]["inputs"])
        self.assertNotIn("recovery", ss.TARGETS["recovery"]["inputs"])

    def test_noop_input_uses_only_well_covered_cycles_and_turns_nan_into_null(self):
        spec = importlib.util.spec_from_file_location("noop_compare", os.path.join(os.path.dirname(_path), "noop_compare.py"))
        nc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nc)
        import datetime as dt
        start = dt.datetime(2026, 11, 1, 0, 0)
        hr = {int(start.timestamp()) + i: 60 for i in range(90)}
        full = {"start": str(start), "end": str(start + dt.timedelta(seconds=100)), "rhr": math.nan}
        thin = {"start": str(start), "end": str(start + dt.timedelta(seconds=1000)), "rhr": 50.0}
        out = nc.build_input([full, thin], hr)
        self.assertEqual(len(out["cycles"][0]["hr"]), 90)
        self.assertEqual(out["cycles"][1]["hr"], [])
        self.assertIsNone(out["cycles"][0]["restingHR"])


if __name__ == "__main__":
    unittest.main()
