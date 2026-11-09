"""Synthetic catalogue fixtures: lossless history and evidence-scoped stages."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from prospect.agent_checks import AgentChecks,TOPICS
from prospect.leads import LeadCatalog,MARKER
from prospect.launch_watch import LaunchWatch
from prospect.store import Store


def signal(**overrides):
    return {'announced':True,'status':'not_started','starts_at':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=7)).isoformat(),
        'compute':'cpu','network':'mainnet','wallet':'native','evidence_url':'https://example.org/launch',
        'evidence_note':'Synthetic official mining announcement','evidence_kind':'primary'}|overrides


class LeadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'store.db')
        self.cpu=self.add('Unpriced CPU','CPU mining','pow')
        self.gpu=self.add('GPU traded','GPU mining','pow',market={'cex_spot':'yes'},requirements={'min_ram_gb':999})
        self.node=self.add('Unknown node','Public node','node')
        self.catalog=LeadCatalog(self.store)
    def tearDown(self):self.tmp.cleanup()
    def add(self,name,summary,category,**extra):
        return self.store.upsert_candidate({'name':name,'url':'https://example.org/'+name.replace(' ','-'),
            'category':category,'summary':summary}|extra)['id']

    def test_history_migration_preserves_all_data_and_settings_and_does_not_capture_future_leads(self):
        self.store.set_setting('agent_models',{'selected':'fixture'});self.store.set_setting('sources',[{'id':'old','enabled':False}])
        LaunchWatch(self.store).observe(self.cpu,signal())
        before=self.store.candidates();self.catalog.initialize();marker=self.store.get_setting(MARKER)
        self.assertEqual(self.store.candidates(),before);self.assertEqual(set(marker['legacy_candidate_ids']),{self.gpu,self.node})
        new=self.add('New unknown','Unknown new announcement','pow');self.catalog.initialize()
        self.assertNotIn(new,self.store.get_setting(MARKER)['legacy_candidate_ids'])
        self.assertEqual(self.store.get_setting('agent_models'),{'selected':'fixture'})
        self.assertEqual(self.store.get_setting('sources'),[{'id':'old','enabled':False}])
        self.assertEqual(self.catalog.detail(self.gpu)['lead_info']['reason_code'],'legacy_unreviewed')
        self.assertEqual(self.catalog.detail(new)['lead_info']['reason_code'],'announcement_unverified')

    def test_unknown_market_wallet_hardware_and_missing_review_do_not_exclude_leads(self):
        self.catalog.initialize();page=self.catalog.page()
        self.assertEqual(page['total'],3);self.assertEqual(page['counts']['unverified'],3);self.assertEqual(page['counts']['excluded'],0)
        self.assertEqual({item['id'] for item in page['items']},{self.cpu,self.gpu,self.node})
        self.assertEqual(self.catalog.detail(self.gpu)['lead_info']['stage'],'unverified')
        self.assertIn('不代表',self.catalog.detail(self.gpu)['lead_info']['reason'])

    def test_primary_mainnet_announcement_is_upcoming_community_claim_remains_unverified(self):
        watch=LaunchWatch(self.store);watch.observe(self.cpu,signal());watch.observe(self.gpu,signal(compute='gpu',evidence_kind='community'))
        self.catalog.initialize();page=self.catalog.page()
        self.assertEqual(page['items'][0]['id'],self.cpu)
        self.assertEqual(self.catalog.detail(self.cpu)['lead_info']['stage'],'upcoming')
        self.assertEqual(self.catalog.detail(self.gpu)['lead_info']['stage'],'unverified')
        self.assertTrue(self.catalog.detail(self.gpu)['lead_info']['important'])
        self.assertFalse(self.catalog.detail(self.cpu)['lead_info']['execution_authorized'])

    def test_actual_opening_and_retraction_have_explainable_reasons_and_keep_records(self):
        watch=LaunchWatch(self.store);watch.observe(self.cpu,signal());watch.observe(self.gpu,signal(compute='gpu'))
        watch.observe(self.cpu,signal(status='open'));watch.observe(self.gpu,signal(status='cancelled',compute='gpu'))
        self.assertEqual(self.catalog.page()['total'],3)
        opened=self.catalog.detail(self.cpu)['lead_info'];excluded=self.catalog.detail(self.gpu)['lead_info']
        self.assertEqual(opened['stage'],'open');self.assertEqual(excluded['stage'],'excluded')
        self.assertTrue(excluded['reason_sources']);self.assertIn('取消',excluded['reason'])

    def test_time_reached_never_implies_actual_opening_and_dismissal_is_not_evidence_exclusion(self):
        watch=LaunchWatch(self.store);task=watch.observe(self.cpu,signal())
        watch.observe(self.cpu,signal(starts_at=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)).isoformat()))
        watch.decide(task['id'],'dismissed');info=self.catalog.detail(self.cpu)['lead_info']
        self.assertEqual(info['stage'],'unverified');self.assertEqual(info['reason_code'],'scheduled_time_reached');self.assertFalse(info['important'])

    def test_pagination_filters_and_cpu_gpu_both_do_not_drop_or_duplicate_records(self):
        watch=LaunchWatch(self.store);watch.observe(self.cpu,signal(compute='either'))
        for n in range(24):self.add('Page '+str(n),'Unknown','tasks')
        ids=[];offset=0
        while offset is not None:
            page=self.catalog.page(offset=offset,limit=5);ids.extend(item['id'] for item in page['items']);offset=page['next_offset']
        self.assertEqual(len(ids),27);self.assertEqual(len(set(ids)),27)
        self.assertIn(self.cpu,{item['id'] for item in self.catalog.page(compute='cpu')['items']})
        self.assertIn(self.cpu,{item['id'] for item in self.catalog.page(compute='gpu')['items']})
        self.assertEqual(self.catalog.page(q='GPU TRADED')['matched'],1)
        self.assertEqual(self.catalog.page(category='tasks')['matched'],24)
        self.assertEqual(self.catalog.page(stage='upcoming')['matched'],1)
        for arguments in ({'offset':True},{'offset':-1},{'limit':51},{'q':'x'*161},{'stage':'fake'},{'category':'wallet'},{'compute':'nvidia'}):
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):self.catalog.page(**arguments)

    def test_completed_review_is_history_not_automatic_security_pass_and_private_fields_never_leak(self):
        checks=AgentChecks(self.store,Path(self.tmp.name));job=checks.request(self.node,'pi',dispatch=False);claim=checks.claim('pi',job['id'])
        url='https://example.org/rules';report={'verdict':'needs_info','identity':'Synthetic node','summary':'Synthetic review, still needs launch evidence.',
            'checks':[{'topic':topic,'status':'unknown','finding':'Unknown','sources':[url]} for topic in TOPICS],
            'sources':[{'url':url,'title':'Fixture','note':'Synthetic'}],'missing_information':['Mainnet launch'],'next_steps':['Read official rules']}
        checks.complete(job['id'],'pi',claim['lease_token'],report)
        info=self.catalog.detail(self.node)['lead_info'];self.assertEqual(info['review_status'],'completed');self.assertEqual(info['stage'],'unverified')
        text=json.dumps(self.catalog.page());self.assertNotIn(claim['lease_token'],text);self.assertNotIn('lease_hash',text);self.assertNotIn('model_policy',text)
        self.assertEqual(self.catalog.page()['reviewed_count'],1)
        checks.shutdown()
