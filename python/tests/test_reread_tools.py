import importlib.util
import os
import unittest

RE = os.path.join(os.path.dirname(__file__), "..", "..", "re")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(RE, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExportDiff(unittest.TestCase):
    def test_separates_older_newer_removed_and_rescored_cycles(self):
        ed = _load("export_diff")
        old = {"2026-11-02": {"Day Strain": "12.2"}, "2026-11-04": {"Day Strain": "4.8"}, "2026-11-05": {"Day Strain": ""}}
        new = {"2026-11-01": {"Day Strain": "9.0"}, "2026-11-02": {"Day Strain": "12.2"},
               "2026-11-04": {"Day Strain": "9.6"}, "2026-11-06": {"Day Strain": "5.0"}}
        d = ed.diff(old, new)
        self.assertEqual(d["added_older"], ["2026-11-01"])
        self.assertEqual(d["added_newer"], ["2026-11-06"])
        self.assertEqual(d["removed"], ["2026-11-05"])
        self.assertEqual(d["changed"], {"2026-11-04": {"Day Strain": ("4.8", "9.6")}})


class BackfillRefusal(unittest.TestCase):
    def setUp(self):
        try:
            self.probe = _load("probe_read_pointer")
        except ImportError:
            self.skipTest("needs bleak")

    def test_allows_an_older_page_the_ring_still_reaches(self):
        self.assertIsNone(self.probe.backfill_refusal(1000, 1100, 500, 100, 5000))

    def test_refuses_a_time_the_ring_no_longer_holds(self):
        self.assertIn("does not reach", self.probe.backfill_refusal(1000, 9000, 500, 100, 20000))

    def test_refuses_a_page_not_older_than_trim(self):
        self.assertIn("not older", self.probe.backfill_refusal(1000, 1100, 100, 100, 5000))

    def test_leftover_records_past_stop_do_not_count_as_reaching_it(self):
        self.assertEqual(self.probe.span_progress([900, 950], 500), (False, False, 0))
        self.assertEqual(self.probe.span_progress([900, 100, 200], 500), (True, False, 200))
        self.assertEqual(self.probe.span_progress([900, 100, 600], 500), (True, True, 600))

    def test_page_search_steps_over_pages_without_a_time(self):
        import asyncio

        async def time_at(behind):
            return 0 if 4000 <= behind <= 4010 else 100000 - behind

        distance = asyncio.run(self.probe.find_distance(time_at, 100000 - 5000, 131072))
        self.assertLessEqual(abs(distance - 5000), 8)

    def test_page_search_gives_up_when_no_page_has_a_time(self):
        import asyncio

        async def time_at(behind):
            return 0

        with self.assertRaises(RuntimeError):
            asyncio.run(self.probe.find_distance(time_at, 500, 131072))

    def test_refuses_a_future_start(self):
        self.assertIn("future", self.probe.backfill_refusal(6000, 6000, 500, 100, 5000))


class RegisteredModels(unittest.TestCase):
    SLEEPS = [
        {"onset": "2026-11-01 23:59:40", "asleep": 345.0, "need": 500.0, "debt": 0.0, "perf": 81.0, "nap": False},
        {"onset": "2026-11-03 00:46:11", "asleep": 336.0, "need": 545.0, "debt": 77.0, "perf": 75.0, "nap": True},
        {"onset": "2026-11-03 23:53:57", "asleep": 405.0, "need": 224.0, "debt": 77.0, "perf": 95.0, "nap": False},
        {"onset": "2026-11-05 00:07:47", "asleep": 413.0, "need": 466.0, "debt": 0.0, "perf": 90.0, "nap": False},
        {"onset": "2026-11-06 00:00:00", "asleep": 400.0, "need": 480.0, "debt": 26.0, "perf": 50.0, "nap": False},
    ]

    def test_only_later_cycles_count_and_frozen_models_keep_their_fit(self):
        sp = _load("score_predictions")
        rows = sp.predictions(self.SLEEPS, [], {})
        self.assertTrue(all(sp.in_rounding(r) for r in rows if not r["new"] and r["model"] in ("SP-Q", "SP-E", "SD-R", "SD-A", "SD-CAP")))
        new = {r["model"]: r for r in rows if r["new"]}
        self.assertFalse(sp.in_rounding(new["SP-Q"]))
        self.assertTrue(sp.in_rounding(new["SD-R"]))
        self.assertFalse(sp.in_rounding(new["SD-CAP"]))


class HrrZones(unittest.TestCase):
    def test_counts_seconds_in_each_zone_from_heart_rate_reserve(self):
        try:
            hz = _load("hrr_zones")
        except ImportError:
            self.skipTest("needs numpy")
        # With rest 50 and maximum 150 the edges are 90, 110, 120, 130 and 140 bpm.
        self.assertEqual(hz.zone_seconds([89, 90, 109, 110, 120, 130, 140, 150], 50, 150), [1, 2, 1, 1, 1, 2])
        self.assertEqual(hz.zone_error([89, 90], [1, 1, 0, 0, 0, 0], 50, 150), 0)


if __name__ == "__main__":
    unittest.main()
