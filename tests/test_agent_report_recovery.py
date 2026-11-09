import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prospect.agent_checks import AgentChecks,HOSTS,REPORT_SCHEMA_ID
from prospect.store import Store
from test_agent_checks import report


def invalid_report():
    value=report();url=value['sources'][0]['url']
    value['project_facts']={'identity_matches_candidate':True,'official_url':'https://example.org/project','facts':[
        {'field':'participation','value':'not_started','sources':[url],'kind':'official','scope':'mainnet','note':'Synthetic announcement'}]}
    return value


class ReportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'store.db')
        self.cid=self.store.upsert_candidate({'name':'Fixture','category':'pow','url':'https://example.org/project'})['id']
        self.checks=AgentChecks(self.store,Path(self.tmp.name))
    def tearDown(self):self.checks.shutdown();self.tmp.cleanup()

    def test_all_four_hosts_correct_same_lease_without_losing_work_or_usage(self):
        for index,host in enumerate(HOSTS,1):
            with self.subTest(host=host):
                job=self.checks.request(self.cid,host,dispatch=False);claim=self.checks.claim(host,job['id'])
                self.assertEqual(claim['report_schema_id'],REPORT_SCHEMA_ID)
                result=self.checks.validate_submission(job['id'],host,claim['lease_token'],invalid_report(),{'input_tokens':100,'output_tokens':20})
                self.assertEqual(result['status'],'needs_correction');self.assertEqual(result['issue']['allowed_values'],['open','closed','unknown'])
                self.assertNotIn(claim['lease_token'],json.dumps(result))
                running=next(j for j in self.checks.jobs() if j['id']==job['id'])
                self.assertEqual(running['status'],'running');self.assertIsNone(running['report'])
                self.assertEqual(self.checks.usage()['agent_check_input_tokens'],100*index)
                self.assertEqual(self.checks.usage()['agent_check_usage_unreported'],0)
                self.assertEqual(self.store.get_candidate(self.cid)['participation'],'unknown')
                path=Path(self.tmp.name)/'agent-check-work'/job['id']/'report.json';self.assertTrue(path.is_file())
                self.assertEqual(self.checks.validate_submission(job['id'],host,claim['lease_token'],report())['status'],'valid')
                done=self.checks.complete(job['id'],host,claim['lease_token'],report())
                self.assertEqual(done['status'],'completed');self.assertEqual(done['usage']['input_tokens'],100)
                self.assertEqual(self.checks.usage()['agent_check_input_tokens'],100*index)
                self.assertNotIn('report_validation',done);self.assertFalse(path.exists())

    def test_wrong_host_or_lease_cannot_stage_report_and_unknown_model_is_not_invented(self):
        job=self.checks.request(self.cid,'pi',dispatch=False);claim=self.checks.claim('pi',job['id'])
        for host,token in [('deepseek',claim['lease_token']),('pi','wrong')]:
            with self.assertRaises(ValueError):self.checks.validate_submission(job['id'],host,token,report())
        self.assertFalse((Path(self.tmp.name)/'agent-check-work'/job['id']).exists())
        self.assertIsNone(claim['runtime_config']['requested_model']);self.assertEqual(claim['runtime_config']['observed_models'],[])

    def test_condition_changes_and_deleted_project_never_keep_a_current_flag(self):
        self.checks.request(self.cid,'pi',dispatch=False);self.checks.request(self.cid,'deepseek',dispatch=False)
        self.assertTrue(all(job['current'] for job in self.checks.jobs()))
        self.store.save_profile({'skill_level':'beginner'})
        self.assertTrue(all(not job['current'] for job in self.checks.jobs()))
        self.store.set_setting('profile',{})
        self.assertTrue(all(job['current'] for job in self.checks.jobs()))
        with self.store._connection(write=True) as db:db.execute('DELETE FROM candidates WHERE id=?',(self.cid,))
        self.assertTrue(all(not job['current'] for job in self.checks.jobs()))

    def test_missing_native_flags_stop_before_any_model_process(self):
        job=self.checks.request(self.cid,'claude',dispatch=False)
        with patch('prospect.agent_checks.find_native',return_value='claude.exe'),patch('prospect.agent_checks.native_profile',return_value={'missing_flags':['--json-schema'],'version':'old'}),patch('prospect.agent_checks.subprocess.Popen') as process:
            self.checks._native_once(job['id'],'claude');process.assert_not_called()
        failed=next(j for j in self.checks.jobs() if j['id']==job['id'])
        self.assertEqual(failed['failure']['source'],'capability_preflight');self.assertIsNone(failed['usage'])

    def test_claude_bad_structured_report_retains_usage_and_has_no_codex_flags(self):
        job=self.checks.request(self.cid,'claude',dispatch=False)
        def stream(process,prompt,event,heartbeat,timeout):
            event({'type':'result','is_error':False,'structured_output':invalid_report(),'usage':{'input_tokens':123,'output_tokens':45}})
            return ''
        profile={'missing_flags':[],'flags':{'--effort':True},'version':'2.1.218 (Claude Code)','source':'standalone','version_tuple':(2,1,218)}
        with patch('prospect.agent_checks.find_native',return_value='claude.exe'),patch('prospect.agent_checks.native_profile',return_value=profile),patch('prospect.agent_checks.consume',side_effect=stream),patch('prospect.agent_checks.subprocess.Popen') as process:
            process.return_value.returncode=0;process.return_value.poll.return_value=0
            self.checks._native_once(job['id'],'claude')
            self.assertNotIn('respect_system_proxy',process.call_args.args[0])
        failed=next(j for j in self.checks.jobs() if j['id']==job['id'])
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['usage']['input_tokens'],123)
        self.assertTrue(failed['failure']['unaccepted_report_preserved']);self.assertEqual(failed['runtime_config']['cli_source'],'standalone')
