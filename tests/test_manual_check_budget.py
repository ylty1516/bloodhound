import json
from pathlib import Path
import tempfile
import unittest

from prospect.agent_checks import AgentChecks
from prospect.store import Store
from test_agent_checks import report


class ManualBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db')
        self.checks=AgentChecks(self.store,self.tmp.name)
        self.cid=self.store.upsert_candidate({'name':'Synthetic budget test','url':'https://example.org/budget','category':'tasks'})['id']
        self.store.set_setting('agent_budget',{'daily_checks':0,'daily_tokens':0,'reservation_tokens':30000})

    def tearDown(self):self.checks.shutdown();self.tmp.cleanup()

    def start(self,host='pi',origin='manual'):
        job=self.checks.request(self.cid,host,dispatch=False,origin=origin)
        return job,self.checks.claim(host,job['id'])

    def test_manual_failed_retries_have_no_daily_check_or_token_cap(self):
        for _ in range(4):
            job,claim=self.start();self.assertEqual(claim['status'],'running')
            self.checks.complete(job['id'],'pi',claim['lease_token'],None,error='Synthetic controlled failure')
        budget=self.checks.budget()
        self.assertEqual(budget['manual']['used_checks'],4)
        self.assertEqual(budget['manual']['unreported_checks'],4)
        self.assertTrue(budget['manual']['can_start'])
        self.assertFalse(budget['automatic']['can_start'])
        self.assertEqual(budget['automatic']['used_checks'],0)

    def test_legacy_manual_history_is_kept_without_exhausting_automatic_budget(self):
        job,claim=self.start()
        self.checks.complete(job['id'],'pi',claim['lease_token'],report(),usage={'input_tokens':400000,'output_tokens':1000})
        with self.store._connection(write=True) as db:
            old=self.checks._read(db,job['id']);old.pop('origin');old['reservation_tokens']=30000;self.checks._write(db,old)
        self.store.set_setting('agent_budget',{'daily_checks':1,'daily_tokens':30000,'reservation_tokens':30000})
        budget=self.checks.budget()
        self.assertEqual(budget['measured_tokens'],401000)
        self.assertEqual(budget['manual']['used_checks'],1)
        self.assertTrue(budget['automatic']['can_start'])
        self.assertEqual(self.start('claude','automatic')[1]['status'],'running')

    def test_manual_continue_promotes_waiting_automatic_task_instead_of_duplicating(self):
        waiting=self.checks.request(self.cid,'pi',dispatch=False,origin='automatic')
        manual=self.checks.request(self.cid,'pi',dispatch=False)
        self.assertTrue(manual['reused']);self.assertEqual(manual['id'],waiting['id'])
        self.assertEqual(manual['origin'],'manual')
        self.assertEqual(self.checks.claim('pi',manual['id'])['status'],'running')
        self.assertEqual(len(self.checks.jobs()),1)

    def test_automatic_block_does_not_block_a_new_manual_check(self):
        automatic,claim=self.start(origin='automatic')
        self.assertEqual(claim['status'],'idle')
        self.assertEqual(self.checks.jobs()[0]['status'],'budget_blocked')
        manual,claim=self.start()
        self.assertNotEqual(automatic['id'],manual['id']);self.assertEqual(claim['status'],'running')
        self.assertEqual(self.checks.budget()['automatic']['used_checks'],0)

    def test_duplicate_manual_request_still_reuses_active_task(self):
        first,claim=self.start()
        again=self.checks.request(self.cid,'pi',dispatch=False)
        self.assertTrue(again['reused']);self.assertEqual(first['id'],again['id'])
        self.assertEqual(self.checks.budget()['manual']['used_checks'],1)
