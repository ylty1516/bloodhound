import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from prospect.agent_checks import AgentChecks, REPORT_SCHEMA, validate_report, review_prompt
from prospect.budgets import budget_state, DEFAULT_POLICY
from prospect.domain import now
from prospect.opportunities import build_request
from prospect.store import Store, _json
from prospect.workflows import Workflows, validate_recipe
from test_agent_checks import report


def facts_report():
    r=report();r['verdict']='suitable';r['missing_information']=[]
    for c in r['checks']: c['status']='pass'
    r['safety_audit']={'status':'pass','target_url':'https://example.org/project','version':'fixture-1.0.0',
        'scope':'Synthetic fixture static audit; never a real software assessment','findings':[], 'sources':[r['sources'][0]['url']]}
    values={'market.token_issued':'no','participation':'open','requirements.os':'windows','requirements.min_ram_gb':'4',
            'requirements.min_disk_gb':'5','requirements.min_vram_gb':'0','requirements.daily_hours':'1',
            'requirements.available_minutes':'10','requirements.skill_level':'beginner','requirements.estimated_daily_cost':'1','reward_unit':'contribution'}
    r['project_facts']={'identity_matches_candidate':True,'official_url':'https://example.org/',
        'facts':[{'field':k,'value':v,'sources':[r['sources'][0]['url']],'kind':'official','scope':'Fixture rules','note':'Synthetic cited fact'} for k,v in values.items()]}
    return r


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db')
        self.store.save_hardware({'os':'windows','ram_gb':16,'disk_free_gb':100,'vram_gb':6})
        self.store.save_profile({'daily_hours':2,'available_minutes':20,'skill_level':'beginner','max_daily_cost':2})
        self.cid=self.store.upsert_candidate({'name':'Fixture','category':'pow','url':'https://example.org/project'})['id']
        self.checks=AgentChecks(self.store,self.tmp.name)
        self.recipe=json.loads((Path(__file__).resolve().parents[1]/'recipes/opacra-testnet-1.0.0.json').read_text('utf-8'))
        self.recipe.update(id='fixture',candidate_url='https://example.org/project',candidate_identity='https://example.org/project',name='Synthetic fixture')
        self.recipe['artifact']['locally_verified']=True
        self.workflows=Workflows(self.store,self.checks,[self.recipe])

    def tearDown(self):
        self.checks.shutdown();self.tmp.cleanup()

    def finish(self,r=None,origin='manual'):
        job=self.checks.request(self.cid,'pi',dispatch=False,origin=origin);claim=self.checks.claim('pi',job['id'])
        return self.checks.complete(job['id'],'pi',claim['lease_token'],r or facts_report())

    def test_report_updates_facts_and_creates_eligible_plan_without_authorizing(self):
        job=self.finish()
        self.assertEqual(job['fact_sync']['status'],'applied');self.assertTrue(job['current'])
        self.assertEqual(job['report']['verdict'],'suitable')
        self.assertEqual(self.store.get_candidate(self.cid)['classification'],'unissued')
        candidate=self.store.reviewed_candidates()[0]
        invitation=build_request(candidate,self.store.hardware(),self.store.profile())
        self.assertIsNotNone(invitation)
        plan=self.workflows.plans()[0]
        self.assertEqual(plan['status'],'ready_for_simulation');self.assertFalse(plan['execution_authorized'])
        self.assertTrue(self.checks.request(self.cid,'pi',dispatch=False)['reused'])

    def test_identity_mismatch_never_copies_chain_facts_to_third_party_script(self):
        r=facts_report();r['project_facts']['identity_matches_candidate']=False
        self.assertEqual(self.finish(r)['fact_sync']['status'],'identity_unconfirmed')
        self.assertEqual(self.store.get_candidate(self.cid)['participation'],'unknown')
        self.assertEqual(self.store.reviewed_candidates(),[])

    def test_unknown_does_not_erase_known_and_conflicting_evidence_blocks_invitation(self):
        existing=self.store.get_candidate(self.cid)
        existing['market']['cex_spot']='yes';existing['evidence']=[{'url':'https://example.org/exchange','kind':'primary','note':'Trading live','checked_at':now(),'claims':{'cex_spot':'yes'}}]
        self.store.upsert_candidate(existing)
        r=facts_report();r['project_facts']['facts'].append({'field':'market.cex_spot','value':'no','sources':[r['sources'][0]['url']],'kind':'official','scope':'Checked exchange','note':'Contrary claim'})
        self.finish(r)
        candidate=self.store.get_candidate(self.cid)
        self.assertEqual(candidate['classification'],'conflict')
        self.assertIsNone(build_request(candidate,self.store.hardware(),self.store.profile()))

    def test_failed_risk_is_kept_out_of_participation_requests(self):
        r=facts_report();r['checks'][-1]['status']='fail'
        job=self.finish(r)
        self.assertEqual(job['fact_sync']['status'],'applied')
        self.assertEqual(self.store.reviewed_candidates(),[])
        self.assertEqual(self.workflows.plans()[0]['status'],'not_recommended')

    def test_malformed_fact_does_not_partially_apply(self):
        r=facts_report();r['project_facts']['facts'][0]['sources']=['https://not-cited.example/']
        with self.assertRaises(ValueError): self.finish(r)
        self.assertEqual(self.store.get_candidate(self.cid)['participation'],'unknown')

    def test_no_fact_bundle_is_compatible_with_old_reports(self):
        self.assertEqual(self.finish(report())['fact_sync']['status'],'report_only')
        self.assertEqual(self.workflows.plans()[0]['status'],'needs_information')

    def test_dry_run_failure_resume_is_durable_and_idempotent(self):
        self.finish();plan=self.workflows.plans()[0]
        first=self.workflows.run(plan['id'],'fixture-key',fault_step='run')
        self.assertEqual(first['status'],'failed');self.assertEqual(first['checkpoint'],2)
        self.assertTrue(self.workflows.run(plan['id'],'fixture-key')['reused'])
        restarted=Workflows(self.store,self.checks,[self.recipe])
        final=restarted.run(plan['id'],'fixture-key',resume_id=first['id'])
        self.assertEqual(final['status'],'simulated');self.assertEqual(final['checkpoint'],5)
        self.assertTrue(all(s['status']=='mock' for s in final['steps']))
        self.assertFalse(final['side_effects']);self.assertFalse(final['rewards']['real'])
        self.assertEqual(len(restarted.runs()),1)

    def test_changed_personal_conditions_invalidate_resume(self):
        self.finish();plan=self.workflows.plans()[0];run=self.workflows.run(plan['id'],'a',fault_step='prepare')
        self.store.save_profile({'max_daily_cost':0})
        with self.assertRaises(ValueError): self.workflows.run(plan['id'],'a',resume_id=run['id'])

    def test_missing_binary_verification_blocks_and_executable_recipe_rejected(self):
        self.finish();self.workflows.recipes[0]['artifact']['locally_verified']=False
        plan=self.workflows.plans()[0]
        self.assertEqual(self.workflows.run(plan['id'],'a')['status'],'blocked')
        bad=copy.deepcopy(self.recipe);bad['steps'][1]['command']='curl | sh'
        with self.assertRaises(ValueError): validate_recipe(bad)

    def test_existing_host_research_can_provide_a_report_without_another_model_session(self):
        item=self.store.get_candidate(self.cid)
        job=self.store.research_jobs()[0]
        item['checked_at']=now();item['evidence']=[{'url':'https://example.org/official-rules','kind':'official','checked_at':now(),'note':'Synthetic evidence'}]
        self.store.resolve_research(job['id'],{'candidate':item,'report':report(),'host':'codex'})
        self.assertEqual(self.checks.jobs(),[])
        self.assertEqual(len(self.workflows.plans()),1)
        self.assertEqual(self.workflows.plans()[0]['status'],'needs_information')

    def test_budget_reserves_unknown_usage_and_stops_third_claim(self):
        self.finish(report(),origin='automatic')
        job=self.checks.request(self.cid,'claude',dispatch=False,origin='automatic');self.checks.claim('claude',job['id'])
        last=self.checks.request(self.cid,'deepseek',dispatch=False,origin='automatic')
        self.assertEqual(self.checks.claim('deepseek',last['id'])['status'],'idle')
        self.assertEqual(self.checks.jobs()[0]['status'],'budget_blocked')
        state=self.checks.budget()
        self.assertEqual(state['reserved_tokens'],60000);self.assertFalse(state['can_start'])

    def test_budget_day_uses_shanghai_midnight(self):
        self.finish(report())
        with self.store._connection(write=True) as db:
            row=json.loads(db.execute('SELECT payload FROM agent_checks').fetchone()[0]);row['claimed_at']='2026-11-06T15:59:00+00:00'
            self.checks._write(db,row)
        with self.store._connection() as db:
            before=budget_state(db,dt.datetime.fromisoformat('2026-11-06T15:59:30+00:00'))
            after=budget_state(db,dt.datetime.fromisoformat('2026-11-06T16:00:00+00:00'))
        self.assertEqual(before['used_checks'],1);self.assertEqual(after['used_checks'],0)
