"""Domain regression cases and isolated SQLite integration tests; no external IO."""
import copy
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospect.domain import assess, normalize_candidate, now, simulate, validate_profile
from prospect.store import Store


def candidate(**changes):
    data = {"name": "Example", "identity_key": "example.org/project", "category": "pow", "url": "https://example.org/project",
            "summary": "Unverified project", "checked_at": now(), "market": {}, "evidence": [], "requirements": {},
            "reward_unit": "unknown", "participation": "unknown"}
    data.update(changes)
    return data


def evidence(claims, **changes):
    data = {"url": "https://example.org/rules", "kind": "official", "note": "Explicit published status",
            "checked_at": now(), "claims": claims, "scope": "Official announcement and specified venues as of this check"}
    data.update(changes)
    return data


class DomainTests(unittest.TestCase):
    def test_classification_regression_twenty_four_cases(self):
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
        cases = [
            ("empty facts", {}, [], "unknown"),
            ("search returned nothing", {"cex_spot": "no", "dex_spot": "no"}, [], "unknown"),
            ("unverified listing", {"cex_spot": "yes"}, [], "unknown"),
            ("official cex", {"cex_spot": "yes"}, [evidence({"cex_spot": "yes"})], "listed"),
            ("official dex", {"dex_spot": "yes"}, [evidence({"dex_spot": "yes"})], "listed"),
            ("dex despite cex absent", {"cex_spot": "no", "dex_spot": "yes"}, [evidence({"cex_spot": "no", "dex_spot": "yes"})], "listed"),
            ("premarket distinct", {"premarket": "yes"}, [evidence({"premarket": "yes"})], "premarket"),
            ("spot wins over premarket", {}, [evidence({"premarket": "yes", "dex_spot": "yes"})], "listed"),
            ("explicit unissued", {}, [evidence({"token_issued": "no"})], "unissued"),
            ("mainnet alone", {"mainnet": "yes"}, [evidence({"mainnet": "yes"})], "unknown"),
            ("tge alone", {"tge": "yes"}, [evidence({"tge": "yes"})], "unknown"),
            ("transferable alone", {"transferable": "yes"}, [evidence({"transferable": "yes"})], "unknown"),
            ("scoped negatives", {}, [evidence({"cex_spot": "no", "dex_spot": "no"})], "unlisted_supported"),
            ("only cex checked", {}, [evidence({"cex_spot": "no"})], "unknown"),
            ("only dex checked", {}, [evidence({"dex_spot": "no"})], "unknown"),
            ("negatives without scope", {}, [evidence({"cex_spot": "no", "dex_spot": "no"}, scope="")], "unknown"),
            ("discovery not official proof", {}, [evidence({"dex_spot": "yes"}, kind="discovery")], "unknown"),
            ("stale evidence", {}, [evidence({"dex_spot": "yes"}, checked_at=old)], "unknown"),
            ("undated evidence", {}, [evidence({"dex_spot": "yes"}, checked_at=None)], "unknown"),
            ("empty note", {}, [evidence({"dex_spot": "yes"}, note="")], "unknown"),
            ("opposing sources", {}, [evidence({"dex_spot": "yes"}), evidence({"dex_spot": "no"})], "conflict"),
            ("market disagrees with proof", {"dex_spot": "no"}, [evidence({"dex_spot": "yes"})], "conflict"),
            ("unknown claims", {}, [evidence({"cex_spot": "unknown", "dex_spot": "unknown"})], "unknown"),
            ("token issued not listing", {}, [evidence({"token_issued": "yes"})], "unknown"),
        ]
        for label, market, proof, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(normalize_candidate(candidate(market=market, evidence=proof))["classification"], expected)

    def test_categories_and_reward_units_stay_distinct(self):
        for category, unit in (("pow", "token"), ("node", "contribution"), ("tasks", "points")):
            result = normalize_candidate(candidate(category=category, reward_unit=unit))
            self.assertEqual((result["category"], result["reward_unit"]), (category, unit))
            self.assertEqual(result["market"]["token_issued"], "unknown")

    def test_timestamp_url_and_type_validation(self):
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        invalid = [{"checked_at": "2026-01-01"}, {"checked_at": future}, {"url": "javascript:alert(1)"},
                   {"url": "https://user:password@example.org/"}, {"url": "https://127.0.0.1/x"},
                   {"market": {"dex_spot": False}}, {"category": "maybe"}, {"name": ""},
                   {"evidence": [evidence({}, checked_at=future)]}, {"requirements": {"min_ram_gb": float("nan")}}]
        for update in invalid:
            with self.subTest(update=update), self.assertRaises(ValueError):
                normalize_candidate(candidate(**update))

    def test_unknown_hardware_and_requirements_do_not_guess(self):
        result = assess(candidate(), {}, {})
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["estimated_daily_cost"])
        self.assertFalse(result["live_execution_allowed"])

    @staticmethod
    def compatible_inputs():
        item = candidate(participation="open", requirements={"min_ram_gb": 8, "min_disk_gb": 20, "min_vram_gb": 0,
            "os": ["windows"], "skill_level": "beginner", "daily_hours": 2, "available_minutes": 10, "estimated_daily_cost": 1})
        hardware = {"ram_gb": 16, "disk_free_gb": 100, "vram_gb": None, "os": "Windows"}
        profile = {"skill_level": "intermediate", "daily_hours": 4, "available_minutes": 30, "max_daily_cost": 2}
        return item, hardware, profile

    def test_constraints_and_budget_are_binding(self):
        item, hardware, profile = self.compatible_inputs()
        self.assertEqual(assess(item, hardware, profile)["status"], "compatible")
        for hw, prefs, patch_item in ((hardware | {"ram_gb": 4}, profile, {}),
                                      (hardware, profile | {"max_daily_cost": 0}, {}),
                                      (hardware, profile | {"cpu_limit_pct": 0}, {}),
                                      (hardware, profile, {"participation": "closed"})):
            with self.subTest(hw=hw, prefs=prefs):
                self.assertEqual(assess(item | patch_item, hw, prefs)["status"], "incompatible")

    def test_simulation_is_pure_and_cannot_claim_real_rewards(self):
        inputs = self.compatible_inputs()
        before = copy.deepcopy(inputs)
        with patch("subprocess.Popen", side_effect=AssertionError("No processes")), patch("urllib.request.urlopen", side_effect=AssertionError("No network")), patch("builtins.open", side_effect=AssertionError("No filesystem")):
            result = simulate(*inputs)
        self.assertEqual(inputs, before)
        self.assertEqual(result["mode"], "simulation")
        self.assertEqual(result["status"], "simulated")
        self.assertTrue(all(step["status"] == "mock" for step in result["steps"]))
        self.assertFalse(result["side_effects"])
        self.assertFalse(result["rewards"]["real"])
        self.assertIsNone(result["rewards"]["amount"])
        self.assertEqual(simulate(candidate(), {}, {})["status"], "blocked")

    def test_profile_rejects_nonfinite_negative_and_wrong_types(self):
        invalid = [{"max_daily_cost": -1}, {"max_daily_cost": float("inf")}, {"electricity_price": float("nan")},
                   {"daily_hours": 25}, {"cpu_limit_pct": 101}, {"gpu_allowed": "false"}, {"skill_level": []},
                   {"max_daily_cost": True}, {"available_minutes": 1441}, {"private_key": "not-a-real-key"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_profile(value)


class StoreTests(unittest.TestCase):
    def setUp(self):
        # F: scratch paths avoid the Windows sandbox's restricted default temp ACL.
        self.temp = tempfile.TemporaryDirectory(prefix="prospect-domain-", dir=Path(__file__).resolve().parents[1])
        self.store = Store(Path(self.temp.name) / "test.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_repeated_input_and_refresh_only_enqueue_one_revision(self):
        item = candidate()
        first = self.store.upsert_candidate(item)
        for _ in range(100):
            self.assertFalse(self.store.upsert_candidate(item | {"checked_at": now()})["changed"])
        self.assertEqual(len(self.store.candidates()), 1)
        self.assertEqual(len(self.store.research_jobs()), 1)
        self.assertEqual(len(self.store.events()), 1)
        self.assertEqual(self.store.usage()["background_model_calls"], 0)
        self.assertEqual(self.store.get_candidate(first["id"])["name"], "Example")

    def test_revision_changes_and_reverts_do_not_duplicate_research(self):
        item = candidate()
        self.store.upsert_candidate(item)
        self.store.upsert_candidate(item | {"summary": "changed", "checked_at": now()})
        self.store.upsert_candidate(item | {"checked_at": now()})
        jobs = self.store.research_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(sum(job["status"] == "pending" for job in jobs), 1)
        self.assertEqual(len([e for e in self.store.events() if e["kind"] == "research_requested"]), 2)

    def test_concurrent_dedup_and_reopen(self):
        item = candidate()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.upsert_candidate(item), range(32)))
        self.assertEqual(sum(result["changed"] for result in results), 1)
        reopened = Store(self.store.path)
        self.assertEqual(len(reopened.candidates()), 1)
        self.assertEqual(len(reopened.research_jobs()), 1)

    def test_old_observation_cannot_overwrite_current_revision(self):
        item = candidate()
        ident = self.store.upsert_candidate(item)["id"]
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
        self.assertFalse(self.store.upsert_candidate(item | {"checked_at": old, "summary": "old"})["changed"])
        self.assertEqual(self.store.get_candidate(ident)["summary"], item["summary"])

    def test_invalid_profile_and_policy_do_not_replace_saved_values(self):
        self.store.save_profile({"max_daily_cost": 3})
        self.store.save_profile({"daily_hours": 4})
        with self.assertRaises(ValueError):
            self.store.save_profile({"max_daily_cost": -2})
        self.assertEqual(self.store.profile(), {"max_daily_cost": 3, "daily_hours": 4})
        self.store.set_setting("policy", {"daily_token_budget": 0})
        for value in (-1, float("nan"), True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.set_setting("policy", {"daily_token_budget": value})
        self.assertEqual(self.store.get_setting("policy"), {"daily_token_budget": 0})

    def test_research_requires_fresh_evidence_and_cannot_authorize(self):
        item = candidate()
        self.store.upsert_candidate(item)
        ident = self.store.research_jobs()[0]["id"]
        with self.assertRaises(ValueError):
            self.store.resolve_research(ident, {"summary": "Trust me"})
        with self.assertRaises(ValueError):
            self.store.resolve_research(ident, {"approved": True})
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).isoformat()
        with self.assertRaises(ValueError):
            self.store.resolve_research(ident, {"evidence": [evidence({}, checked_at=old)]})
        resolved = self.store.resolve_research(ident, {"checked_at": now(), "evidence": [evidence({"token_issued": "no"})]})
        self.assertFalse(resolved["live_execution_allowed"])
        self.assertEqual(resolved["candidate"]["classification"], "unissued")
        self.assertEqual(len(self.store.research_jobs()), 1)
        self.assertEqual(self.store.usage()["research_pending"], 0)
        self.assertEqual(self.store.resolve_research(ident, {}), resolved)

    def test_stale_research_cannot_change_new_revision(self):
        item = candidate()
        self.store.upsert_candidate(item)
        ident = self.store.research_jobs()[0]["id"]
        self.store.upsert_candidate(item | {"summary": "new", "checked_at": now()})
        with self.assertRaises(ValueError):
            self.store.resolve_research(ident, {"evidence": [evidence({})]})

    def test_source_refresh_preserves_review_and_does_not_requeue(self):
        item = candidate()
        candidate_id = self.store.upsert_candidate(item)["id"]
        job_id = self.store.research_jobs()[0]["id"]
        self.store.resolve_research(job_id, {"checked_at": now(), "evidence": [evidence({"token_issued": "no"})]})
        result = self.store.upsert_candidate(item | {"checked_at": now()})
        self.assertFalse(result["changed"])
        self.assertEqual(self.store.get_candidate(candidate_id)["classification"], "unissued")
        self.assertEqual(len(self.store.research_jobs()), 1)
        self.assertEqual(self.store.usage()["research_pending"], 0)

    def test_completed_research_accepts_fresh_corrections_without_new_job(self):
        item = candidate()
        candidate_id = self.store.upsert_candidate(item)["id"]
        job_id = self.store.research_jobs()[0]["id"]
        self.store.resolve_research(job_id, {"checked_at": now(), "evidence": [evidence({"token_issued": "no"})]})
        corrected = self.store.resolve_research(job_id, {"checked_at": now(), "evidence": [evidence({"dex_spot": "yes"})]})
        self.assertEqual(corrected["candidate"]["classification"], "listed")
        self.assertEqual(self.store.get_candidate(candidate_id)["classification"], "listed")
        self.assertEqual(len(self.store.research_jobs()), 1)
        self.assertEqual(self.store.events()[0]["kind"], "research_updated")
        yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            self.store.resolve_research(job_id, {"checked_at": yesterday, "evidence": [evidence({"token_issued": "no"})]})

    def test_scan_run_event_storage_and_host_usage_are_explicit(self):
        self.store.record_scan({"source_id": "source", "status": "ok", "count": 0})
        self.assertEqual(self.store.scans()[0]["status"], "ok")
        run = self.store.add_run({"id": "simulation-1", "mode": "simulation"})
        self.assertEqual(self.store.add_run({"id": "simulation-1", "mode": "simulation"}), run)
        with self.assertRaises(ValueError):
            self.store.add_run({"id": "simulation-1", "mode": "real"})
        self.assertEqual(len(self.store.runs()), 1)
        self.assertEqual(self.store.usage()["host_usage"], "unknown")
        self.store.set_setting("host_usage", {"input_tokens": 12, "output_tokens": 3})
        self.assertEqual(self.store.usage()["host_usage"]["input_tokens"], 12)
        event = self.store.add_event("manual", {"message": "read only"})
        self.assertEqual(self.store.events()[0], event)
        self.assertIsNone(self.store.get_candidate("absent"))


if __name__ == "__main__":
    unittest.main()
