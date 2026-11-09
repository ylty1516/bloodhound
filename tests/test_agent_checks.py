import concurrent.futures
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from prospect.agent_checks import AgentChecks, HOSTS, TOPICS, validate_report, public_url, measured_usage, cli_failure
from prospect.store import Store, _json


def report():
    url = "https://example.org/official-rules"
    return {"verdict": "needs_info", "summary": "仅测试报告，不是真实项目。", "identity": "合成项目",
            "checks": [{"topic": t, "status": "unknown", "finding": "资料待核验", "sources": [url]} for t in TOPICS],
            "sources": [{"url": url, "title": "测试来源", "note": "测试用依据"}],
            "missing_information": ["实际资格"], "next_steps": ["核验官方资格"]}


class AgentCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "state.db")
        self.store.set_setting("agent_budget", {"daily_checks":10,"daily_tokens":600000,"reservation_tokens":30000})
        self.store.upsert_candidate({"name": "Fixture", "url": "https://example.org/project", "category": "tasks"})
        self.cid = self.store.candidates()[0]["id"]
        self.checks = AgentChecks(self.store, self.tmp.name)

    def tearDown(self):
        self.checks.shutdown()
        self.tmp.cleanup()

    def request(self, host="any"):
        return self.checks.request(self.cid, host, dispatch=False)

    def test_all_four_hosts_can_claim_and_report(self):
        for host in HOSTS:
            with self.subTest(host=host):
                job = self.request(host)
                claim = self.checks.claim(host, job["id"])
                self.assertEqual(claim["host"], host)
                self.assertIn("UNTRUSTED_CONTEXT_JSON", claim["prompt"])
                done = self.checks.complete(job["id"], host, claim["lease_token"], report())
                self.assertEqual(done["status"], "completed")
                self.assertFalse(done["live_execution_allowed"])
                self.assertNotIn("lease_hash", done)
                self.assertNotIn("context", done)

    def test_concurrent_requests_deduplicate_and_claim_is_exclusive(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            jobs = list(pool.map(lambda _: self.request(), range(5)))
        self.assertEqual(len({j["id"] for j in jobs}), 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda h: self.checks.claim(h), HOSTS))
        self.assertEqual(sum(c["status"] == "running" for c in claims), 1)

    def test_wrong_host_or_token_cannot_complete(self):
        job = self.request("pi")
        self.assertEqual(self.checks.claim("codex", job["id"])["status"], "idle")
        claim = self.checks.claim("pi", job["id"])
        with self.assertRaises(ValueError): self.checks.complete(job["id"], "claude", claim["lease_token"], report())
        with self.assertRaises(ValueError): self.checks.complete(job["id"], "pi", "wrong", report())

    def test_cancel_rejects_late_report(self):
        job = self.request()
        claim = self.checks.claim("codex", job["id"])
        self.assertEqual(self.checks.cancel(job["id"])["status"], "cancelled")
        with self.assertRaises(ValueError): self.checks.complete(job["id"], "codex", claim["lease_token"], report())

    def test_context_change_rejects_result_and_allows_new_check(self):
        job = self.request()
        claim = self.checks.claim("codex", job["id"])
        self.store.save_profile({"daily_hours": 1})
        result = self.checks.complete(job["id"], "codex", claim["lease_token"], report())
        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["report"])
        self.assertNotEqual(self.request()["id"], job["id"])

    def test_expired_and_interrupted_jobs_are_not_silently_retried(self):
        job = self.request()
        claim = self.checks.claim("codex", job["id"])
        with self.store._connection(write=True) as db:
            raw = self.checks._read(db, job["id"]); raw["lease_until"] = time.time() - 1; self.checks._write(db, raw)
        self.assertEqual(self.checks.jobs()[0]["status"], "failed")
        another = self.request(); self.checks.claim("pi", another["id"])
        self.checks.recover()
        self.assertEqual(self.checks.jobs()[0]["status"], "failed")

    def test_report_requires_all_topics_and_citations_and_cannot_authorize(self):
        value = report(); value["execute"] = True
        with self.assertRaises(ValueError): validate_report(value, {})
        value = report(); value["checks"][0]["status"] = "pass"; value["checks"][0]["sources"] = []
        with self.assertRaises(ValueError): validate_report(value, {})
        value = report(); value["checks"].pop()
        with self.assertRaises(ValueError): validate_report(value, {})

    def test_unknown_safety_stays_unknown_even_when_hardware_incompatible(self):
        value = report(); value["verdict"] = "suitable"
        self.assertEqual(validate_report(value, {"status": "unknown"})["verdict"], "needs_info")
        self.assertEqual(validate_report(value, {"status": "incompatible"})["verdict"], "needs_info")

    def test_failed_check_keeps_agent_verdict_and_explains_merged_decision(self):
        job = self.request(); claim = self.checks.claim("pi", job["id"])
        value = report(); value["checks"][-1]["status"] = "fail"
        done = self.checks.complete(job["id"], "pi", claim["lease_token"], value)
        self.assertEqual(done["report"]["agent_verdict"], "needs_info")
        self.assertEqual(done["report"]["verdict"], "unsuitable")
        self.assertIn("未通过", done["decision_note"])

    def test_shutdown_prevents_queued_native_work_from_starting(self):
        job = self.request("codex")
        self.checks.shutdown()
        with patch("prospect.agent_checks.subprocess.Popen") as spawn:
            self.checks._native(job["id"], "codex")
            spawn.assert_not_called()
        self.assertEqual(self.checks.jobs()[0]["status"], "queued")
        with self.assertRaises(ValueError): self.request("claude")

    def test_native_setup_error_becomes_visible_failure(self):
        job = self.request("codex")
        with patch("prospect.agent_checks.find_native", return_value="codex"), patch.object(Path, "mkdir", side_effect=OSError("Test setup failure")):
            self.checks._native(job["id"], "codex")
        self.assertEqual(self.checks.jobs()[0]["status"], "failed")
        self.assertIn("Test setup failure", self.checks.jobs()[0]["progress"])

    def test_private_links_rejected(self):
        for url in ["http://example.org/a", "https://127.0.0.1/", "https://user:pass@example.org/", "https://internal.local/x"]:
            with self.subTest(url=url), self.assertRaises(ValueError): public_url(url)

    def test_cached_completed_result_reuses_model_work(self):
        job = self.request(); claim = self.checks.claim("codex", job["id"])
        self.checks.complete(job["id"], "codex", claim["lease_token"], report())
        self.assertTrue(self.request()["reused"])
        self.assertEqual(len(self.checks.jobs()), 1)

    def test_no_native_process_for_bridge_only_host(self):
        with patch("prospect.agent_checks.find_native", return_value=None), patch("prospect.agent_checks.subprocess.Popen") as spawn:
            job = self.checks.request(self.cid, "deepseek")
            self.assertEqual(job["status"], "queued")
            spawn.assert_not_called()

    def test_unreported_host_usage_and_missing_counters_are_not_zero(self):
        job = self.request("pi"); claim = self.checks.claim("pi", job["id"])
        self.checks.complete(job["id"], "pi", claim["lease_token"], report())
        self.assertEqual(self.checks.usage()["agent_check_usage_unreported"], 1)
        self.assertIsNone(measured_usage({"output_tokens": 10}))
        self.assertIsNone(measured_usage({"input_tokens": -1, "output_tokens": 10}))
        self.assertIsNone(measured_usage({"input_tokens": float("nan"), "output_tokens": 10}))
        self.assertEqual(measured_usage({"input_tokens": 10, "output_tokens": 2}), {"input_tokens": 10, "output_tokens": 2})

    def test_cli_failure_exposes_only_classified_reason(self):
        self.assertIn("余额不足",cli_failure("claude","API Error 403 Insufficient account balance"))
        self.assertNotIn("secret",cli_failure("claude","unknown credential: secret"))
        self.assertIn('连接中断',cli_failure('codex','stream disconnected before completion: error sending request for url (https://example.org/?key=secret)'))
        self.assertNotIn('secret',cli_failure('codex','stream disconnected before completion: key=secret'))
        self.assertIn('格式定义',cli_failure('codex','invalid_json_schema: secret'))
        self.assertIn('余额不足',cli_failure('codex','429 insufficient_quota'))
        self.assertIn('模型',cli_failure('codex','model_not_found'))

    def test_rejected_native_report_preserves_known_usage_and_private_report(self):
        job=self.request('codex');folder=Path(self.tmp.name)/'agent-check-work'/job['id']
        value=report();url=value['sources'][0]['url']
        value['project_facts']={'identity_matches_candidate':True,'official_url':'https://example.org/project','facts':[
            {'field':'participation','value':'not_started','sources':[url],'kind':'official','scope':'mainnet','note':'Synthetic future launch'}]}
        def stream(process,prompt,event,heartbeat,timeout):
            (folder/'report.json').write_text(json.dumps(value),encoding='utf-8')
            event({'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':30}});return ''
        with patch('prospect.agent_checks.find_native',return_value='codex.exe'),patch('prospect.agent_checks.native_profile',return_value={}),patch('prospect.agent_checks.consume',side_effect=stream),patch('prospect.agent_checks.subprocess.Popen') as popen:
            popen.return_value.returncode=0;popen.return_value.poll.return_value=0
            self.checks._native_once(job['id'],'codex')
        result=next(j for j in self.checks.jobs() if j['id']==job['id'])
        self.assertEqual(result['status'],'failed');self.assertIn('参与状态',result['progress'])
        self.assertEqual(result['usage']['input_tokens'],120);self.assertTrue(result['failure']['unaccepted_report_preserved'])
        self.assertTrue((folder/'report.json').is_file());self.assertEqual(self.store.get_candidate(self.cid)['participation'],'unknown')
