import importlib.util
import json
import os
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location("whoop_api_fetch", os.path.join(os.path.dirname(__file__), "..", "..", "re", "whoop_api_fetch.py"))
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)

CREDS = {"WHOOP_CLIENT_ID": "id", "WHOOP_CLIENT_SECRET": "SECRET-VALUE", "WHOOP_REDIRECT_URI": "http://localhost:8765/callback"}


def client(replies, tokens=None):
    calls = []

    def call(url, headers, data=None):
        calls.append((url, headers, data))
        return replies.pop(0)

    saved = []
    c = api.Client(CREDS, tokens or {"access_token": "old", "refresh_token": "r"}, saved.append, call, lambda _: None)
    return c, calls, saved


def ok(value):
    return 200, {}, json.dumps(value).encode()


class Paging(unittest.TestCase):
    def test_follows_next_token_until_the_last_page(self):
        c, calls, _ = client([ok({"records": [{"id": 1}], "next_token": "n"}), ok({"records": [{"id": 2}]})])
        self.assertEqual(c.all_records("/v2/cycle"), [{"id": 1}, {"id": 2}])
        self.assertIn("nextToken=n", calls[1][0])
        self.assertIn("limit=25", calls[0][0])


class Failures(unittest.TestCase):
    def test_waits_and_retries_after_a_rate_limit(self):
        c, calls, _ = client([(429, {"Retry-After": "1"}, b""), ok({"records": []})])
        self.assertEqual(c.all_records("/v2/cycle"), [])
        self.assertEqual(len(calls), 2)

    def test_refreshes_once_on_401_and_stores_the_new_tokens(self):
        c, calls, saved = client([(401, {}, b""), ok({"access_token": "new", "refresh_token": "r2"}), ok({"records": []})])
        c.all_records("/v2/cycle")
        self.assertEqual(saved[0]["access_token"], "new")
        self.assertEqual(calls[2][1]["Authorization"], "Bearer new")

    def test_token_failure_does_not_show_the_reply_or_the_secret(self):
        c, _, _ = client([(401, {}, b""), (400, {}, b"bad SECRET-VALUE")])
        with self.assertRaises(api.ApiError) as e:
            c.get("/v2/cycle")
        self.assertNotIn("SECRET", str(e.exception))

    def test_one_failed_collection_does_not_lose_the_others(self):
        replies = [(403, {}, b""), ok({"records": [{"id": 1, "start": "2026-11-01T00:00:00Z", "score_state": "SCORED"}]}),
                   ok({"records": []}), ok({"records": []}), ok({"max_heart_rate": 200})]
        c, _, _ = client(replies)
        with tempfile.TemporaryDirectory() as d:
            out = api.save_everything(c, d)
            self.assertEqual(json.load(open(os.path.join(out, "recoveries.json")))[0]["id"], 1)
            self.assertEqual(len(json.load(open(os.path.join(out, "manifest.json")))["errors"]), 1)
            self.assertEqual(os.stat(os.path.join(out, "cycles.json")).st_size if os.path.exists(os.path.join(out, "cycles.json")) else 0, 0)


class SignIn(unittest.TestCase):
    def test_rejects_a_reply_with_the_wrong_state(self):
        with self.assertRaises(api.ApiError):
            api.code_from_redirect("http://localhost:8765/callback?code=c&state=other", "mine")

    def test_reads_the_code_and_reports_a_refusal(self):
        self.assertEqual(api.code_from_redirect("/callback?code=c&state=s", "s"), "c")
        with self.assertRaises(api.ApiError):
            api.code_from_redirect("/callback?error=access_denied&state=s", "s")

    def test_asks_only_for_the_needed_scopes(self):
        self.assertNotIn("read%3Aprofile", api.authorize_url(CREDS, "s"))
        self.assertIn("read%3Abody_measurement", api.authorize_url(CREDS, "s"))

    def test_credentials_file_is_locked_down_and_checked(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "credentials.env")
            with open(path, "w") as f:
                f.write("WHOOP_CLIENT_ID=a\nWHOOP_CLIENT_SECRET=b\n")
            os.chmod(path, 0o644)
            with self.assertRaises(api.ApiError):
                api.read_credentials(path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


class ApiChecks(unittest.TestCase):
    @staticmethod
    def sleep(nap, light, needed):
        return {"nap": nap, "score": {"sleep_needed": dict(zip(("baseline_milli", "need_from_sleep_debt_milli", "need_from_recent_strain_milli",
                                                                 "need_from_recent_nap_milli"), needed)),
                                      "stage_summary": {"total_light_sleep_time_milli": light, "total_slow_wave_sleep_time_milli": 0,
                                                        "total_rem_sleep_time_milli": 0, "total_awake_time_milli": 10,
                                                        "total_in_bed_time_milli": light + 10}}}

    def checks(self):
        spec = importlib.util.spec_from_file_location("api_checks", os.path.join(os.path.dirname(__file__), "..", "..", "re", "api_checks.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_debt_is_half_the_shortfall_held_across_a_nap_with_nap_credit(self):
        chain = [self.sleep(False, 300, (1001, 0, 0, 0)), self.sleep(True, 200, (900, 350, 5, 0)), self.sleep(False, 400, (900, 350, 5, -200))]
        lines = self.checks().check_sleep_chain(chain)
        self.assertIn("debt = half the shortfall of the last main sleep: 2 of 2 exact", lines)
        self.assertIn("nap credit = the nap's asleep time: 1 of 1 exact", lines)

    def test_reports_a_debt_that_breaks_the_rule(self):
        chain = [self.sleep(False, 300, (1000, 0, 0, 0)), self.sleep(False, 400, (900, 351, 0, 0))]
        lines = self.checks().check_sleep_chain(chain)
        self.assertIn("debt = half the shortfall of the last main sleep: 0 of 1 exact", lines)
        self.assertTrue(any("expected 350 got 351" in line for line in lines))


class VerifyFindings(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("verify_findings", os.path.join(os.path.dirname(__file__), "..", "..", "re", "verify_findings.py"))
        self.vf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.vf)
        stage = {"total_light_sleep_time_milli": 120000, "total_slow_wave_sleep_time_milli": 0, "total_rem_sleep_time_milli": 0,
                 "total_awake_time_milli": 60000, "total_in_bed_time_milli": 180000}
        self.sleeps = [{"start": "2026-01-01T00:00:00Z", "timezone_offset": "+01:00", "nap": False,
                        "score": {"sleep_needed": {"baseline_milli": 240000, "need_from_sleep_debt_milli": 0, "need_from_recent_strain_milli": 0,
                                                   "need_from_recent_nap_milli": 0}, "stage_summary": stage,
                                  "sleep_performance_percentage": 80.0}}]
        self.export_sleeps = [{"Sleep onset": "2026-01-01 01:00:00", "Sleep need (min)": "4", "Asleep duration (min)": "2", "In bed duration (min)": "3"}]

    def results(self, export_sleeps):
        return {r["claim"]: r["ok"] for r in self.vf.verify(export_sleeps, [], self.sleeps, [], [], [])}

    def test_a_matching_export_passes_the_minute_claims(self):
        self.assertTrue(self.results(self.export_sleeps)["export need = floor(sum of the four API components)"])

    def test_a_changed_export_value_fails_its_claim(self):
        self.export_sleeps[0]["Sleep need (min)"] = "5"
        self.assertFalse(self.results(self.export_sleeps)["export need = floor(sum of the four API components)"])

    def test_a_claim_with_no_cases_does_not_count_as_holding(self):
        self.assertFalse(self.results(self.export_sleeps)["nap credit = the nap's asleep time"])


class Round2(unittest.TestCase):
    def test_only_sleeps_after_the_freeze_are_scored(self):
        spec = importlib.util.spec_from_file_location("api_checks", os.path.join(os.path.dirname(__file__), "..", "..", "re", "api_checks.py"))
        checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checks)
        old = ApiChecks.sleep(False, 60000 * 300, (60000 * 400, 0, 0, 0))
        new = ApiChecks.sleep(False, 60000 * 300, (27834334, 3000000, 0, 0))  # second record: k = 0
        for s, start in ((old, "2026-11-05T22:00:00Z"), (new, "2026-11-06T22:00:00Z")):
            s.update({"start": start, "timezone_offset": "+01:00", "id": start})
            s["score"].update({"sleep_performance_percentage": 80.0, "sleep_efficiency_percentage": 96.0, "sleep_consistency_percentage": 0})
        rows = {r["model"]: r for r in checks.round2([old, new], [], None)}
        self.assertTrue(rows["debt replace"]["ok"])
        self.assertTrue(rows["BL-L baseline"]["ok"])
        self.assertEqual({r["start"] for r in checks.round2([old, new], [], None)}, {"2026-11-06 23:00:00"})


class FrozenOnApi(unittest.TestCase):
    def test_sp_m_drops_consistency_when_missing(self):
        spec = importlib.util.spec_from_file_location("api_checks", os.path.join(os.path.dirname(__file__), "..", "..", "re", "api_checks.py"))
        checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checks)
        self.assertAlmostEqual(checks.sp_m(100, 100, None, 0), 100)
        self.assertAlmostEqual(checks.sp_m(50, 90, 0, 10), (20 + 18 + 18) / 0.8)
        self.assertAlmostEqual(checks.sp_m(50, 90, 80, 10), 20 + 18 + 18 + 16)

    def test_uses_exact_inputs_and_links_recovery_to_its_own_sleep(self):
        spec = importlib.util.spec_from_file_location("api_checks", os.path.join(os.path.dirname(__file__), "..", "..", "re", "api_checks.py"))
        checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checks)
        sleep = ApiChecks.sleep(False, 60000 * 400, (60000 * 400, 0, 0, 0))
        sleep["id"] = "s1"
        sleep["score"]["sleep_performance_percentage"] = 93.0
        rows = checks.frozen_on_api([sleep], [{"sleep_id": "s1", "score": {"hrv_rmssd_milli": 40.0, "recovery_score": 40.0}}])
        by_model = {r["model"]: r for r in rows}
        self.assertAlmostEqual(by_model["R-SLEEP"]["predicted"], 0.13 * 400 - 11.17)
        self.assertAlmostEqual(by_model["R-HRV"]["predicted"], 119.5 - 2.25 * 40)
        self.assertEqual(by_model["SP-Q"]["actual"], 93.0)


if __name__ == "__main__":
    unittest.main()
