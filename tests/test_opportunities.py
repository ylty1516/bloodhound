"""Pure opportunity invitation rules. All projects below are synthetic fixtures."""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

from prospect.opportunities import build_request


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        checked = self.now.isoformat()
        self.candidate = {
            "name": "Synthetic review candidate", "url": "https://example.org/participation", "category": "node",
            "checked_at": checked, "participation": "open", "reward_unit": "contribution",
            "market": {"token_issued": "no"},
            "requirements": {"min_ram_gb": 8, "min_disk_gb": 20, "min_vram_gb": 0, "os": ["windows"],
                             "daily_hours": 1, "available_minutes": 10, "skill_level": "beginner", "estimated_daily_cost": 1},
            "evidence": [{"url": "https://example.org/rules", "kind": "official", "note": "Synthetic rules: open contribution, published resources, token not issued.",
                          "checked_at": checked, "claims": {"token_issued": "no"}, "scope": "Official participation rules"}],
        }
        self.hardware = {"ram_gb": 16, "disk_free_gb": 100, "vram_gb": 6, "os": "Windows"}
        self.profile = {"daily_hours": 3, "available_minutes": 30, "skill_level": "intermediate", "max_daily_cost": 2}

    def build(self, candidate=None, hardware=None, profile=None, now_time=None):
        return build_request(self.candidate if candidate is None else candidate,
                             self.hardware if hardware is None else hardware,
                             self.profile if profile is None else profile,
                             self.now if now_time is None else now_time)

    def test_complete_review_invitation_is_not_execution_authority(self):
        result = self.build()
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["readiness"], "plan_review_only")
        self.assertIn("不会启动任务", result["plan"]["execution_note"])
        self.assertTrue(result["blockers"])
        self.assertEqual(len(result["plan"]["resources"]), 4)
        self.assertEqual(result["evidence"][0]["kind"], "official")

    def test_discovery_and_unsubstantiated_market_claims_never_invite(self):
        for mode in ("empty", "discovery", "primary_only", "no_claims", "empty_note"):
            candidate = copy.deepcopy(self.candidate)
            if mode == "empty": candidate["evidence"] = []
            elif mode == "discovery": candidate["evidence"][0]["kind"] = "discovery"
            elif mode == "primary_only": candidate["evidence"][0]["kind"] = "primary"
            elif mode == "no_claims": candidate["evidence"][0]["claims"] = {}
            else: candidate["evidence"][0]["note"] = ""
            with self.subTest(mode=mode): self.assertIsNone(self.build(candidate))

    def test_trading_premarket_and_conflicting_evidence_reject(self):
        for field in ("cex_spot", "dex_spot", "premarket", "token_issued"):
            candidate = copy.deepcopy(self.candidate)
            candidate["evidence"].append(candidate["evidence"][0] | {"claims": {field: "yes"}})
            with self.subTest(field=field): self.assertIsNone(self.build(candidate))
        self.assertIsNone(self.build(self.candidate | {"market": {"token_issued": "yes"}}))
        self.assertIsNone(self.build(self.candidate | {"market": {"cex_spot": "yes"}}))

    def test_stale_or_closed_candidate_never_invites(self):
        self.assertIsNone(self.build(self.candidate | {"participation": "closed"}))
        self.assertIsNone(self.build(self.candidate | {"participation": "unknown"}))
        self.assertIsNone(self.build(now_time=self.now + dt.timedelta(hours=48, seconds=1)))
        self.assertIsNotNone(self.build(now_time=self.now + dt.timedelta(hours=48)))
        candidate = copy.deepcopy(self.candidate)
        candidate["evidence"][0]["checked_at"] = (self.now - dt.timedelta(hours=49)).isoformat()
        self.assertIsNone(self.build(candidate))
        self.assertIsNone(self.build(self.candidate | {"checked_at": None}))

    def test_old_positive_trading_evidence_is_not_erased_by_heartbeat(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["evidence"].append(candidate["evidence"][0] | {
            "checked_at": (self.now - dt.timedelta(days=9)).isoformat(), "claims": {"dex_spot": "yes"}})
        self.assertIsNone(self.build(candidate))

    def test_hardware_unknown_insufficient_or_unsupported_reject(self):
        for changes in ({"ram_gb": 4}, {"disk_free_gb": 1}, {"os": "linux"}, {"ram_gb": None}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.build(hardware=self.hardware | changes))
        self.assertIsNone(self.build(hardware={}))
        for field in ("min_ram_gb", "min_disk_gb", "min_vram_gb", "daily_hours", "available_minutes", "skill_level", "os"):
            candidate = copy.deepcopy(self.candidate)
            candidate["requirements"].pop(field)
            with self.subTest(field=field): self.assertIsNone(self.build(candidate))

    def test_unknown_user_profile_yields_questions_but_known_limits_bind(self):
        result = self.build(profile={})
        self.assertIsNotNone(result)
        self.assertIn("尚需确认使用者的操作经验", result["blockers"])
        self.assertIn("尚需确认可接受的日成本上限", result["blockers"])
        for change in ({"max_daily_cost": 0}, {"cpu_limit_pct": 0}, {"daily_hours": .5}, {"available_minutes": 1}):
            with self.subTest(change=change): self.assertIsNone(self.build(profile=self.profile | change))

    def test_unknown_cost_and_points_are_not_promised_currency(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["requirements"]["estimated_daily_cost"] = None
        candidate["reward_unit"] = "points"
        result = self.build(candidate)
        self.assertIn("不是已到账代币", result["plan"]["reward"])
        self.assertEqual(result["plan"]["estimated_cost"], "日成本尚待估算")
        self.assertIn("项目日成本缺少可靠估算", result["blockers"])
        result = self.build(candidate | {"reward_unit": "unknown"})
        self.assertIn("尚未确认", result["plan"]["reward"])

    def test_revision_ignores_heartbeat_profile_and_evidence_order(self):
        original = self.build()
        candidate = copy.deepcopy(self.candidate)
        candidate["checked_at"] = (self.now + dt.timedelta(seconds=1)).isoformat()
        candidate["evidence"][0]["checked_at"] = candidate["checked_at"]
        candidate["summary"] = "Display-only summary"
        refreshed = self.build(candidate, profile={}, now_time=self.now + dt.timedelta(seconds=1))
        self.assertEqual(original["id"], refreshed["id"])
        self.assertEqual(original["revision"], refreshed["revision"])
        self.assertNotEqual(original["blockers"], refreshed["blockers"])
        candidate["evidence"].append(candidate["evidence"][0] | {"url": "https://example.org/resources"})
        first = self.build(candidate)
        candidate["evidence"].reverse()
        self.assertEqual(first["revision"], self.build(candidate)["revision"])

    def test_substantive_cost_and_resource_changes_have_new_revision(self):
        old = self.build()
        for field, value in (("estimated_daily_cost", 1.5), ("min_disk_gb", 30)):
            candidate = copy.deepcopy(self.candidate)
            candidate["requirements"][field] = value
            with self.subTest(field=field): self.assertNotEqual(old["id"], self.build(candidate)["id"])

    def test_scoped_spot_absence_is_accepted_but_partial_search_is_not(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["market"] = {"token_issued": "yes"}
        candidate["evidence"][0]["claims"] = {"cex_spot": "no", "dex_spot": "no"}
        self.assertIsNotNone(self.build(candidate))
        candidate["evidence"][0]["scope"] = ""
        self.assertIsNone(self.build(candidate))
        candidate["evidence"][0]["scope"] = "Some known venues"
        candidate["evidence"][0]["claims"].pop("dex_spot")
        self.assertIsNone(self.build(candidate))

    def test_rule_is_pure_and_historical_clock_is_supported(self):
        before = copy.deepcopy((self.candidate, self.hardware, self.profile))
        with patch("subprocess.Popen", side_effect=AssertionError("No process")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("No network")), \
             patch("builtins.open", side_effect=AssertionError("No file")):
            self.assertIsNotNone(self.build())
        self.assertEqual(before, (self.candidate, self.hardware, self.profile))
        historical = self.now - dt.timedelta(days=30)
        candidate = copy.deepcopy(self.candidate)
        candidate["checked_at"] = historical.isoformat()
        candidate["evidence"][0]["checked_at"] = historical.isoformat()
        self.assertIsNotNone(self.build(candidate, now_time=historical))
        with self.assertRaises(ValueError): self.build(now_time="2026-01-01")


if __name__ == "__main__":
    unittest.main()
