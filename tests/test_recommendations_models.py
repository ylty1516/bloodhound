import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from prospect.agent_checks import AgentChecks, validate_report
from prospect.agent_settings import AgentSettings, observed_models
from prospect.domain import now
from prospect.recommendations import trial_advice, trial_request
from prospect.store import Store
from prospect.workflows import Workflows
from test_workflows import facts_report


class TrialAdviceTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {"url": "https://example.org/project", "participation": "open", "classification": "listed", "category":"tasks"}

    def test_safety_pass_allows_trial_despite_hardware_cost_and_market_failures(self):
        report = facts_report()
        for check in report["checks"]:
            if check["topic"] in ("hardware", "cost", "effort", "market"): check["status"] = "fail"
        report["missing_information"] = ["预算尚未填写"]
        validated = validate_report(report, {"status": "incompatible"})
        self.assertEqual(validated["verdict"], "suitable")
        result = trial_advice(validated, self.candidate, now())
        self.assertEqual(result["status"], "suggested_trial")
        self.assertGreaterEqual(len(result["notes"]), 4)
        self.assertFalse(result["execution_authorized"])

    def test_unknown_safety_or_web_only_report_is_pending_not_rejected(self):
        report = facts_report(); report.pop("safety_audit")
        report["verdict"] = "unsuitable"
        self.assertEqual(trial_advice(report, self.candidate)["status"], "audit_pending")
        self.assertEqual(validate_report(report, {"status": "incompatible"})["verdict"], "needs_info")

    def test_risk_and_closed_window_are_not_relaxed(self):
        report = facts_report(); report["checks"][-1]["status"] = "fail"
        self.assertEqual(trial_advice(report, self.candidate)["status"], "security_concern")
        self.assertEqual(trial_advice(facts_report(), self.candidate | {"participation": "closed"})["status"], "unavailable")

    def test_official_web_route_does_not_require_unavailable_website_source_code(self):
        report=facts_report();report['safety_audit'].update(method='official_web',version='',scope='Synthetic verified official web entry and permission checks; no software installation')
        result=validate_report(report,{})
        self.assertEqual(trial_advice(result,self.candidate,now())['status'],'suggested_trial')
        self.assertEqual(trial_advice(result,self.candidate|{'category':'node'},now())['status'],'audit_pending')
        result['checks'][0]['status']='unknown'
        self.assertEqual(trial_advice(result,self.candidate,now())['status'],'audit_pending')

    def test_target_version_scope_evidence_and_freshness(self):
        for key, bad in (("version", "latest"), ("scope", ""), ("sources", []), ("target_url", "http://127.0.0.1")):
            report = facts_report(); report["safety_audit"][key] = bad
            with self.assertRaises(ValueError): validate_report(report, {})
        report = facts_report();report["safety_audit"]["target_url"] = "https://example.org/some-other-script"
        self.assertEqual(trial_advice(report, self.candidate)["status"], "audit_pending")
        old = (dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=49)).isoformat()
        self.assertEqual(trial_advice(facts_report(), self.candidate, old)["status"], "review_expired")
        self.assertEqual(trial_advice(facts_report(), self.candidate, now(), False)["status"], "review_expired")

    def test_hardware_change_does_not_remove_trial_but_keeps_execution_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"state.db");checks=AgentChecks(store,tmp)
            store.save_hardware({"os":"windows","ram_gb":1,"disk_free_gb":1,"vram_gb":0})
            cid=store.upsert_candidate({"name":"Fixture","url":self.candidate["url"],"category":"pow"})["id"]
            job=checks.request(cid,"pi",dispatch=False);lease=checks.claim("pi",job["id"])
            checks.complete(job["id"],"pi",lease["lease_token"],facts_report())
            workflows=Workflows(store,checks,[])
            plan=workflows.plans()[0]
            self.assertEqual(plan["recommendation"]["status"],"suggested_trial")
            self.assertEqual(plan["status"],"needs_information")
            invitation=trial_request(plan);self.assertIsNotNone(invitation)
            store.save_hardware({"os":"linux","ram_gb":2,"disk_free_gb":1})
            next_plan=workflows.plans()[0]
            self.assertEqual(next_plan["recommendation"]["status"],"suggested_trial")
            self.assertEqual(trial_request(next_plan)["id"],invitation["id"])
            self.assertEqual(workflows.run(next_plan["id"],"test-only")["status"],"blocked")


class AgentModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.store=Store(self.home/"state.db");self.settings=AgentSettings(self.store,self.home)
        self.checks=AgentChecks(self.store,self.home);self.checks.settings=self.settings
        self.cid=self.store.upsert_candidate({"name":"Fixture","url":"https://example.org/project","category":"node"})["id"]
    def tearDown(self): self.tmp.cleanup()

    def test_only_non_secret_allowlisted_host_preferences_are_exposed(self):
        folder=self.home/".codex";folder.mkdir()
        config='model="gpt-fixture"\nmodel_reasoning_effort="max"\nsecret="DO-NOT-EXPOSE"\n'
        (folder/"config.toml").write_text(config,"utf-8")
        result=self.settings.view()
        self.assertEqual(result["host_defaults"]["codex"]["model"],"gpt-fixture")
        self.assertNotIn("DO-NOT-EXPOSE",json.dumps(result))
        self.assertEqual(result["policy"]["hosts"]["codex"],{"model":"","effort":"low"})
        policy=result["policy"];policy["hosts"]["codex"]={"model":"gpt-other","effort":"high"}
        self.settings.save(policy)
        self.assertEqual((folder/"config.toml").read_text("utf-8"),config)
        self.assertEqual(AgentSettings(self.store,self.home).policy(),policy)

    def test_invalid_secrets_commands_and_unsupported_effort_are_rejected(self):
        for value in ("--shell", "model\n--flag", "sk-project-secret", "https://provider.example/model", "foo\";exit", "x"*161):
            policy=self.settings.policy();policy["hosts"]["codex"]["model"]=value
            with self.assertRaises(ValueError):self.settings.save(policy)
        policy=self.settings.policy();policy["hosts"]["codex"]["effort"]="ultra"
        with self.assertRaises(ValueError):self.settings.save(policy)
        policy=self.settings.policy();policy["hosts"]["pi"]={"model":"fake","effort":"high"}
        with self.assertRaises(ValueError):self.settings.save(policy)

    def test_model_catalog_restricts_declared_effort_and_omits_private_data(self):
        folder=self.home/".codex";folder.mkdir()
        (folder/"models_cache.json").write_text(json.dumps({"models":[{"slug":"gpt-fixture","supported_reasoning_levels":[{"effort":"low"}],"private":"DO-NOT-EXPOSE"}]}),"utf-8")
        policy=self.settings.policy();policy["hosts"]["codex"]={"model":"gpt-fixture","effort":"high"}
        with self.assertRaises(ValueError):self.settings.save(policy)
        self.assertNotIn("DO-NOT-EXPOSE",json.dumps(self.settings.view()))

    def test_queue_configuration_is_frozen_and_changed_settings_bypass_completed_cache(self):
        policy=self.settings.policy();policy["hosts"]["codex"]={"model":"gpt-first","effort":"high"}
        self.settings.save(policy)
        job=self.checks.request(self.cid,"codex",dispatch=False)
        policy["hosts"]["codex"]={"model":"gpt-second","effort":"medium"};self.settings.save(policy)
        self.assertEqual(self.checks.request(self.cid,"codex",dispatch=False)["id"],job["id"])
        lease=self.checks.claim("codex",job["id"],"native_cli")
        self.assertEqual(lease["runtime_config"]["requested_model"],"gpt-first")
        self.assertEqual(lease["runtime_config"]["requested_effort"],"high")
        done=self.checks.complete(job["id"],"codex",lease["lease_token"],facts_report())
        self.assertEqual(done["runtime_config"]["requested_model"],"gpt-first")
        self.assertNotEqual(self.checks.request(self.cid,"codex",dispatch=False)["id"],job["id"])

    def test_default_host_routing_and_host_session_are_honest(self):
        policy=self.settings.policy();policy["default_host"]="pi";self.settings.save(policy)
        job=self.checks.request(self.cid,dispatch=False)
        self.assertEqual(job["requested_host"],"pi")
        self.assertEqual(self.checks.claim("codex",job["id"])["status"],"idle")
        lease=self.checks.claim("pi",job["id"])
        self.assertEqual(lease["runtime_config"]["model_source"],"host_session")
        self.assertIsNone(lease["runtime_config"]["requested_model"])

    def test_actual_model_metadata_excludes_transcript_and_credentials(self):
        event={"type":"system","subtype":"init","model":"claude-fixture","session":"secret","system":"private"}
        self.assertEqual(observed_models(event,"claude"),["claude-fixture"])
        event["model"]="sk-secret"
        self.assertEqual(observed_models(event,"claude"),[])
        self.assertEqual(observed_models({"type":"reasoning","model":"fake"},"codex"),[])
