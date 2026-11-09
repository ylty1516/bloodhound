"""Proxy regression and public announcement source contracts; all HTML is synthetic."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospect.launch_watch import LaunchWatch
from prospect.sources import parse,scan,source_proxies
from prospect.store import Store


class ProxyTests(unittest.TestCase):
    def test_no_proxy_alone_does_not_hide_windows_existing_proxy(self):
        with patch('prospect.sources.os.name','nt'),patch.dict(os.environ,{'NO_PROXY':'localhost,127.0.0.1'},clear=True),\
             patch('prospect.sources.urllib.request.getproxies',return_value={'no':'localhost,127.0.0.1'}),\
             patch('prospect.sources.urllib.request.getproxies_registry',return_value={'http':'http://win-proxy.example:8080','https':'http://win-proxy.example:8080'},create=True):
            proxies=source_proxies();self.assertEqual(proxies['https'],'http://win-proxy.example:8080');self.assertEqual(proxies['no'],'localhost,127.0.0.1')
            self.assertNotIn('HTTPS_PROXY',os.environ)

    def test_explicit_environment_proxy_and_explicit_disabled_proxy_are_preserved(self):
        for env,proxies,expected in [({'HTTPS_PROXY':'http://explicit.example:8080'},{'https':'http://explicit.example:8080'},'http://explicit.example:8080'),
                                     ({'HTTPS_PROXY':''},{},None),({'ALL_PROXY':'http://all.example:8080'},{'all':'http://all.example:8080'},'http://all.example:8080')]:
            with self.subTest(env=env),patch('prospect.sources.os.name','nt'),patch.dict(os.environ,env,clear=True),\
                patch('prospect.sources.urllib.request.getproxies',return_value=proxies),\
                patch('prospect.sources.urllib.request.getproxies_registry',return_value={'https':'http://registry.example:8080'},create=True):
                self.assertEqual(source_proxies().get('https'),expected)


class ForumTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'store.db')
        self.source={'id':'forum','kind':'launch_forum','url':'https://bitcointalk.org/index.php?board=159.0','category':'pow','enabled':True,'interval_seconds':900}
    def tearDown(self):self.tmp.cleanup()
    def page(self):
        future=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=7)).replace(microsecond=0).isoformat()
        return f'''<html><a href="https://bitcointalk.org/index.php?topic=101.0">[PRE-ANN] Fixture CPU PoW mainnet launch {future}</a>
            <a href="https://bitcointalk.org/index.php?topic=101.20">Fixture CPU mining reply pagination</a>
            <a href="https://evil.example/?topic=201.0">[ANN] Fake CPU mining</a>
            <a href="https://bitcointalk.org/index.php?topic=102.0">[ANN] Fixture CPU-mined mainnet live</a>
            <a href="https://bitcointalk.org/index.php?topic=103.0">[ANN] Fixture GPU CPU rendering network</a>
            <a href="https://bitcointalk.org/index.php?topic=104.0">Advertising spam is not allowed</a></html>'''.encode()

    def test_forum_titles_canonicalize_topics_without_trusting_community_as_official(self):
        items=parse(self.source|{'evidence_kind':'primary'},self.page())
        self.assertEqual(len(items),3);self.assertEqual(len({i['identity_key'] for i in items}),3)
        self.assertEqual(items[0]['launch_signal']['evidence_kind'],'community')
        self.assertEqual(items[0]['evidence'][0]['kind'],'discovery')
        self.assertEqual(items[1]['launch_signal']['status'],'open')
        self.assertEqual(items[2]['category'],'node')
        self.assertTrue(all('evil.example' not in item['url'] for item in items))

    def test_challenge_or_unsupported_forum_is_not_a_healthy_empty_result(self):
        for source,body in [(self.source,b'<html>Access challenge</html>'),(self.source|{'url':'https://evil.example/'},self.page())]:
            with self.assertRaises(ValueError):parse(source,body)

    def test_real_scan_contract_stores_all_relevant_leads_and_only_prelaunch_todo(self):
        self.store.set_setting('sources',[self.source]);body=self.page()
        result=scan(self.store,lambda s,h:(200,{},body));self.assertEqual(result['errors'],0);self.assertEqual(len(self.store.candidates()),3)
        todos=LaunchWatch(self.store).view()['items'];self.assertEqual(len(todos),1);self.assertEqual(todos[0]['compute'],'cpu')
        self.assertFalse(todos[0]['execution_authorized'])
        repeat=scan(self.store,lambda s,h:(304,{},b''),force=True)
        self.assertEqual(repeat['unchanged'],1);self.assertEqual(len(self.store.candidates()),3);self.assertEqual(len(LaunchWatch(self.store).view()['items']),1)

    def legacy(self,url=None):
        rss='https://bitcointalk.org/index.php?board=159.0&type=rss&action=.xml&limit=30'
        source={'id':'launch-announcements','url':url or rss,'kind':'launch_rss','enabled':False,'interval_seconds':1200,'category':'pow','label':'User label'}
        self.store.set_setting('sources',[source]);self.store.set_setting('launch_watch_migrated',True)
        self.store.set_setting('source_health',{'launch-announcements':{'status':'error','failures':4,'error':'timeout'}})
        self.store.set_setting('observation',{'status':'paused','source_plan':[{'id':'original','url':'https://example.org/original'}]})
        self.store.set_setting('agent_models',{'unchanged':'fixture'});return source

    def test_owned_source_upgrade_preserves_switches_old_failure_observation_and_model(self):
        self.legacy();before=self.store.get_setting('observation');LaunchWatch(self.store).migrate()
        sources=self.store.get_setting('sources');owned=next(s for s in sources if s['id']=='launch-announcements')
        self.assertEqual(owned['kind'],'launch_forum');self.assertFalse(owned['enabled']);self.assertEqual(owned['interval_seconds'],1200);self.assertEqual(owned['label'],'User label')
        self.assertEqual(self.store.get_setting('source_health')['launch-announcements']['previous_endpoint']['failures'],4)
        self.assertEqual(self.store.get_setting('observation'),before);self.assertEqual(self.store.get_setting('agent_models'),{'unchanged':'fixture'})
        LaunchWatch(self.store).migrate();self.assertEqual(self.store.get_setting('sources'),sources)

    def test_custom_source_is_not_overwritten_and_running_observation_is_not_modified(self):
        custom=self.legacy('https://example.org/custom-feed');LaunchWatch(self.store).migrate()
        self.assertEqual(self.store.get_setting('sources')[0],custom)
        self.store.set_setting('launch_source_revision',None);before=copy.deepcopy(self.store.get_setting('sources'))
        self.store.set_setting('observation',{'status':'running','source_plan':before});LaunchWatch(self.store).migrate()
        self.assertEqual(self.store.get_setting('sources'),before);self.assertIsNone(self.store.get_setting('launch_source_revision'))
