import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospect.launch_watch import LaunchWatch,validate_signal,infer,canonical_announcement,POLICY
from prospect.sources import parse,scan
from prospect.store import Store,_json
from prospect.agent_checks import AgentChecks,validate_report
from test_agent_checks import report


def signal(**updates):
    return {'announced':True,'status':'not_started','starts_at':'2099-12-21T14:00:00+00:00','compute':'cpu',
        'network':'mainnet','wallet':'native','evidence_url':'https://example.org/official-rules',
        'evidence_note':'合成公告：主网尚未开挖，CPU优先。','evidence_kind':'primary'}|updates


class LaunchWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db');self.watch=LaunchWatch(self.store)
    def tearDown(self):self.tmp.cleanup()
    def candidate(self,name='Fixture'):
        return self.store.upsert_candidate({'name':name,'category':'pow','url':'https://example.org/'+name})['id']

    def test_unpriced_native_wallet_project_is_automatically_important(self):
        cid=self.candidate();self.watch.observe(cid,signal())
        row=self.watch.view()['items'][0]
        self.assertTrue(row['critical']);self.assertEqual(row['todo_status'],'pending');self.assertFalse(row['execution_authorized'])
        self.assertEqual(row['wallet'],'native');self.assertEqual(self.store.get_candidate(cid)['classification'],'unknown')

    def test_cpu_precedes_earlier_gpu_launch_and_unknown_hardware(self):
        for name,compute,start in [('Gpu','gpu','2098-01-01T00:00:00Z'),('Unknown','unknown','2097-01-01T00:00:00Z'),('Cpu','cpu','2099-01-01T00:00:00Z')]:
            self.watch.observe(self.candidate(name),signal(compute=compute,starts_at=start))
        self.assertEqual([r['name'] for r in self.watch.view()['items']],['Cpu','Gpu','Unknown'])

    def test_duplicate_poll_does_not_create_duplicate_task_or_event(self):
        cid=self.candidate();first=self.watch.observe(cid,signal());events=len(self.store.events())
        self.watch.observe(cid,signal());self.assertEqual(len(self.watch.view()['items']),1);self.assertEqual(len(self.store.events()),events)
        self.assertEqual(self.watch.view()['items'][0]['id'],first['id'])

    def test_done_state_survives_poll_and_restart(self):
        cid=self.candidate();row=self.watch.observe(cid,signal());self.watch.decide(row['id'],'done')
        self.watch.observe(cid,signal(starts_at='2099-12-22T14:00:00Z'))
        recovered=LaunchWatch(Store(self.store.path)).view();self.assertEqual(recovered['important_count'],0)
        self.assertEqual(recovered['items'][0]['todo_status'],'done')

    def test_already_open_or_testnet_only_does_not_create_new_prelaunch_todo(self):
        cid=self.candidate()
        for value in [signal(status='open'),signal(status='cancelled'),signal(network='testnet'),signal(starts_at='2020-01-01T00:00:00Z')]:
            self.assertIsNone(self.watch.observe(cid,value))
        self.assertEqual(self.watch.view()['items'],[])

    def test_open_update_preserves_original_task_but_removes_upcoming_claim(self):
        cid=self.candidate();self.watch.observe(cid,signal());self.watch.observe(cid,signal(status='open'))
        row=self.watch.view()['items'][0];self.assertEqual(row['phase'],'open');self.assertFalse(row['critical'])
        self.watch.observe(cid,signal(announced=False,status='unknown'))
        self.assertEqual(self.watch.view()['items'][0]['phase'],'retracted');self.assertFalse(self.watch.view()['items'][0]['critical'])

    def test_reaching_time_means_due_not_confirmed_open(self):
        cid=self.candidate();row=self.watch.observe(cid,signal())
        with self.store._connection(write=True) as db:
            row['starts_at']='2020-01-01T00:00:00+00:00';db.execute('UPDATE launch_watch SET payload=?',(_json(row),))
        result=self.watch.view()['items'][0];self.assertEqual(result['phase'],'due');self.assertTrue(result['critical'])

    def test_old_evidence_is_marked_for_recheck(self):
        cid=self.candidate();row=self.watch.observe(cid,signal())
        with self.store._connection(write=True) as db:
            row['checked_at']='2020-01-01T00:00:00+00:00';db.execute('UPDATE launch_watch SET payload=?',(_json(row),))
        self.assertEqual(self.watch.view()['items'][0]['phase'],'needs_recheck')
        self.watch.observe(cid,signal(announced=False,status='unknown'))
        with self.store._connection(write=True) as db:
            row=self.watch.view()['items'][0];row['checked_at']='2020-01-01T00:00:00+00:00';db.execute('UPDATE launch_watch SET payload=?',(_json(row),))
        self.assertEqual(self.watch.view()['items'][0]['phase'],'retracted');self.assertFalse(self.watch.view()['items'][0]['critical'])

    def test_community_text_cannot_overwrite_primary_schedule(self):
        cid=self.candidate();self.watch.observe(cid,signal());self.watch.observe(cid,signal(evidence_kind='community',starts_at='2098-01-01T00:00:00Z'))
        self.assertEqual(self.watch.view()['items'][0]['starts_at'],'2099-12-21T14:00:00+00:00')

    def test_unchanged_rule_poll_preserves_agent_findings_but_new_schedule_needs_review(self):
        cid=self.candidate();self.watch.observe(cid,signal(wallet='unknown'),'official-feed')
        self.watch.observe(cid,signal(wallet='native',evidence_note='Agent 已读取项目原生钱包公告'))
        self.watch.observe(cid,signal(wallet='unknown'),'official-feed')
        row=self.watch.view()['items'][0]
        self.assertEqual(row['wallet'],'native');self.assertTrue(row['agent_reviewed']);self.assertEqual(row['source_id'],'official-feed')
        self.watch.observe(cid,signal(starts_at='2099-12-22T14:00:00Z',wallet='unknown'),'official-feed')
        self.assertFalse(self.watch.view()['items'][0]['agent_reviewed'])

    def test_invalid_timezone_local_urls_and_commands_are_rejected(self):
        for value in [signal(starts_at='2099-12-21T14:00:00'),signal(evidence_url='http://127.0.0.1/a'),signal(command='run.exe')]:
            with self.assertRaises(ValueError):validate_signal(value)

    def test_schedule_parsing_distinguishes_testnet_from_future_mainnet(self):
        result=infer('CPU PoW testnet is live. Mainnet is not live and the public countdown is 21st December 2099 at 1400hrs UK time.','https://example.org/','primary')
        self.assertEqual(result['starts_at'],'2099-12-21T14:00:00+00:00');self.assertEqual(result['status'],'not_started')
        self.assertEqual(result['compute'],'cpu');self.assertEqual(result['network'],'mainnet')

    def test_past_launch_is_not_a_new_opportunity(self):
        self.assertIsNone(infer('CPU mining Mainnet launch 2020-01-01T00:00:00Z','https://example.org/'))
        self.assertIsNone(infer('GPU miner already running. Traded on exchanges.','https://example.org/'))
        self.assertIsNone(infer('Material for learning Data Mining, ML. Restructuring coming soon.','https://example.org/'))
        self.assertIsNone(infer('My old mining stuff. Coming soon.','https://example.org/'))

    def test_ambiguous_schedule_does_not_invent_a_time(self):
        value=infer('CPU mining coming soon. Mainnet launch: 21st December 2099.','https://example.org/')
        self.assertEqual(value['starts_at'],'');self.assertEqual(value['status'],'unknown')
        value=infer('CPU mining mainnet launch 2099-01-01T00:00:00Z. Mainnet launch 2099-02-01T00:00:00Z','https://example.org/')
        self.assertEqual(value['starts_at'],'');self.assertEqual(value['status'],'unknown')

    def test_forum_replies_share_one_topic_identity(self):
        self.assertEqual(canonical_announcement('https://bitcointalk.org/index.php?topic=123.msg999#msg999'),'https://bitcointalk.org/index.php?topic=123.0')

    def test_actual_connector_pipeline_auto_enqueues_and_304_deduplicates(self):
        source={'id':'fixture','kind':'launch_rss','url':'https://example.org/feed','category':'pow','enabled':True,'interval_seconds':900}
        self.store.set_setting('sources',[source])
        body=b'<rss><channel><item><title>CPU mining coming soon</title><link>https://example.org/coin</link><description>Mainnet launch 2099-12-21T14:00:00Z</description></item></channel></rss>'
        scan(self.store,fetcher=lambda *_:(200,{},body));first=self.watch.view()['items'][0]
        scan(self.store,fetcher=lambda *_:(304,{},b''),force=True)
        self.assertEqual(len(self.watch.view()['items']),1);self.assertEqual(first['candidate_id'],self.watch.view()['items'][0]['candidate_id'])

    def test_agent_report_creates_task_atomically_without_market_or_audit_pass(self):
        cid=self.candidate();checks=AgentChecks(self.store,Path(self.tmp.name))
        try:
            job=checks.request(cid,'pi',dispatch=False);claim=checks.claim('pi',job['id']);r=report();r['mining_launch']=signal()
            done=checks.complete(job['id'],'pi',claim['lease_token'],r)
            self.assertEqual(done['status'],'completed');self.assertEqual(self.watch.view()['important_count'],1)
        finally:checks.shutdown()

    def test_report_launch_evidence_must_be_a_declared_source(self):
        r=report();r['mining_launch']=signal(evidence_url='https://example.org/unread')
        with self.assertRaises(ValueError):validate_report(r,{})
        r=report();r['sources'][0]['url']+='\u0023launch';r['checks']=[dict(c,sources=[r['sources'][0]['url']]) for c in r['checks']]
        r['mining_launch']=signal(evidence_url='https://example.org/official-rules#launch');validate_report(r,{})

    def test_policy_migration_is_idempotent_and_never_authorizes_execution(self):
        self.store.set_setting('sources',[{'id':'old','enabled':True}]);self.watch.migrate();self.watch.migrate()
        self.assertEqual(self.store.get_setting('discovery_policy')['id'],POLICY['id'])
        self.assertFalse(self.store.get_setting('sources')[0]['enabled']);self.assertFalse(POLICY['requires_live_market'])
        self.assertFalse(POLICY['requires_binance_wallet']);self.assertEqual({s['id'] for s in self.store.get_setting('sources') if s.get('enabled')},
            {'launch-announcements','launch-token-announcements','launch-github-cpu','launch-github-ann','launch-shear'})


if __name__=='__main__':unittest.main()
