import datetime as dt
import http.cookiejar
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from prospect.service import Handler, LocalServer, Runtime, DirectoryLock
from prospect.sources import import_legacy, parse, scan, validate_public_url


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="prospect-test-")
        self.server = LocalServer(("127.0.0.1", 0), Handler)
        self.rt = Runtime(Path(self.tmp.name), self.server.server_port)
        self.server.runtime = self.rt
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.rt.store.save_hardware({"os": "windows", "ram_gb": 32, "disk_free_gb": 100, "vram_gb": 12})

    def tearDown(self):
        self.rt.executions.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def req(self, path, payload=None, auth=True, extra=None):
        headers = {"Content-Type": "application/json"}
        if auth: headers["Authorization"] = "Bearer " + self.rt.token
        headers.update(extra or {})
        data = json.dumps(payload).encode() if payload is not None else None
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data=data, headers=headers), timeout=3)

    def test_api_requires_control_credential(self):
        with self.assertRaises(urllib.error.HTTPError) as error: self.req("/api/state", auth=False)
        self.assertEqual(error.exception.code, 403)

    def test_complete_catalogue_http_and_cli_keep_hidden_leads_accessible_without_checks(self):
        from test_leads import signal
        from prospect.cli import tool
        ids=[]
        for index in range(72):
            ids.append(self.rt.store.upsert_candidate({'name':f'Fixture lead {index:02}','category':'pow',
                'summary':'CPU mining fixture','url':f'https://example.org/lead/{index}'})['id'])
        self.rt.launch_watch.observe(ids[0],signal())
        with self.req('/api/state') as response:state=json.load(response)
        self.assertEqual(len(state['candidates']),1);self.assertEqual(len(state['discovery_archive']),71)
        self.assertEqual(state['lead_catalog']['total'],72)
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/leads',auth=False)
        received=[];offset=0
        while offset is not None:
            with self.req(f'/api/leads?offset={offset}&limit=20') as response:page=json.load(response)
            received.extend(item['id'] for item in page['items']);offset=page['next_offset']
        self.assertEqual(set(received),set(ids));self.assertEqual(len(received),72)
        with self.req('/api/leads?stage=unverified') as response:self.assertEqual(json.load(response)['matched'],71)
        with self.req('/api/leads/detail?id='+ids[-1]) as response:self.assertEqual(json.load(response)['id'],ids[-1])
        for path in ('/api/leads?limit=0','/api/leads?offset=-1','/api/leads?stage=unknown','/api/leads?limit=1&limit=2','/api/leads/detail?id=missing'):
            with self.subTest(path=path),self.assertRaises(urllib.error.HTTPError):self.req(path)
        (Path(self.tmp.name)/'control.json').write_text(json.dumps({'port':self.server.server_port,'token':self.rt.token}),'utf-8')
        with patch('prospect.cli.ensure'),patch('prospect.cli.observe_agent'):
            page=tool(Path(self.tmp.name),self.server.server_port,'prospect_candidates',{'offset':20,'limit':10,'compute':'cpu'})
            self.assertEqual(page['total'],72);self.assertEqual(len(page['items']),10);self.assertIn('lead_info',page['items'][0])
            detail=tool(Path(self.tmp.name),self.server.server_port,'prospect_assess',{'candidate_id':ids[-1]})
            self.assertEqual(detail['id'],ids[-1])
            with self.assertRaises(ValueError):tool(Path(self.tmp.name),self.server.server_port,'prospect_candidates',{'limit':True})
        self.assertEqual(self.rt.agent_checks.jobs(),[]);self.assertEqual(self.rt.executions.runs(),[])
        for asset in ('/leads.js','/leads.css'):
            with self.req(asset,auth=False) as response:self.assertEqual(response.status,200)

    def test_execution_http_scope_start_logs_receipt_and_auth(self):
        from prospect.execution_drivers import SELF_CHECK
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/executions',auth=False)
        for path,body in (('/api/executions/preview',{}),('/api/executions/start',{'quote_id':'absent','key':'x','confirmed':True}),('/api/executions/cancel',{'id':'absent'})):
            with self.assertRaises(urllib.error.HTTPError):self.req(path,body,auth=False)
            with self.assertRaises(urllib.error.HTTPError):self.req(path,body,extra={'Origin':'https://evil.example'})
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/executions/preview',{'command':'calc.exe'})
        with self.req('/api/executions/preview',{'driver':SELF_CHECK}) as r:quote=json.load(r)
        self.assertTrue(quote['ready']);self.assertFalse(quote['started'])
        with self.req('/api/executions') as r:self.assertEqual(json.load(r)['jobs'],[])
        with patch('prospect.executions.build_spec',return_value={'driver':SELF_CHECK,'seconds':.2}):
            with self.req('/api/executions/start',{'quote_id':quote['id'],'key':'http','confirmed':True}) as r:job=json.load(r)
            for _ in range(60):
                with self.req('/api/executions') as r:latest=json.load(r)['jobs'][0]
                if latest.get('receipt'):break
                time.sleep(.05)
        self.assertEqual(latest['status'],'completed');self.assertTrue(latest['diagnostic_verified'])
        with self.req('/api/executions/logs?id='+job['id']) as r:self.assertGreater(len(json.load(r)['lines']),0)
        with self.req('/api/executions/receipt?id='+job['id']) as r:self.assertFalse(json.load(r)['rewards_verified'])
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/executions/logs?id='+job['id']+'&after=oops')
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/executions/receipt?id=../../control')
        with self.req('/executions.js',auth=False) as r:self.assertEqual(r.status,200)
        with self.req('/participation.js',auth=False) as r:self.assertEqual(r.status,200)

    def test_agent_model_settings_use_local_auth_validate_and_persist(self):
        with self.req('/api/agent-settings') as response: settings=json.load(response)
        policy=settings['policy'];policy['hosts']['codex']={'model':'gpt-fixture','effort':'medium'}
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/agent-settings',policy,auth=False)
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/agent-settings',policy,extra={'Origin':'https://evil.example'})
        with self.req('/api/agent-settings',policy) as response: updated=json.load(response)
        self.assertEqual(updated['policy']['hosts']['codex']['model'],'gpt-fixture')
        invalid={'default_host':'codex','hosts':{'codex':{'model':'x','effort':'unknown'}}}
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/agent-settings',invalid)
        with self.req('/api/agent-settings') as response: self.assertEqual(json.load(response)['policy'],policy)
        self.assertEqual(self.rt.agent_checks.jobs(),[])
        with self.req("/api/state") as response:
            state = json.load(response)
        self.assertEqual(state["service"]["mode"], "managed_execution")
        self.assertNotIn(self.rt.token, json.dumps(state))

    def test_current_agent_routing_uses_live_observation_and_native_auth(self):
        import os
        from prospect.agent_context import process_started
        observation={'host':'codex','pid':os.getpid(),'started':process_started(os.getpid()),'source':'tool'}
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/agent-context',auth=False)
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/agent-context/observe',observation,auth=False)
        with self.req('/',auth=False) as response:cookie=response.headers['Set-Cookie'].split(';')[0]
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.req('/api/agent-context/observe',observation,auth=False,extra={'Origin':self.base,'Cookie':cookie})
        self.assertEqual(error.exception.code,403)
        with patch.object(self.rt.agent_checks,'request',return_value={'status':'queued'}) as dispatch:
            with self.assertRaises(urllib.error.HTTPError):self.req('/api/checks/request',{'candidate_id':'c','host':'current'})
            dispatch.assert_not_called()
            with self.req('/api/agent-context/observe',observation) as response:
                current=json.load(response);self.assertEqual(current['host'],'codex');self.assertNotIn('pid',current)
            # A saved API/CLI preference must not override the actual caller.
            policy=self.rt.agent_checks.settings.policy();policy['default_host']='deepseek_api';self.rt.agent_checks.settings.save(policy)
            with self.req('/api/checks/request',{'candidate_id':'c','host':'current'}):pass
            dispatch.assert_called_once_with('c','codex')
            with self.req('/api/checks/request',{'candidate_id':'c','host':'claude'}):pass
            self.assertEqual(dispatch.call_args.args,('c','claude'))
        with self.req('/api/checks') as response:self.assertEqual(json.load(response)['agent_context']['host'],'codex')

    def test_deepseek_settings_and_connection_routes_require_local_auth(self):
        from prospect.deepseek_provider import DEFAULT
        for path, body in (('/api/agent-settings/deepseek', DEFAULT), ('/api/agent-settings/deepseek/test', {})):
            with self.assertRaises(urllib.error.HTTPError): self.req(path, body, auth=False)
            with self.assertRaises(urllib.error.HTTPError): self.req(path, body, extra={'Origin':'https://evil.example'})
        with self.req('/api/agent-settings/deepseek', DEFAULT) as response:
            self.assertFalse(json.load(response)['key_configured'])
        with patch.object(self.rt.agent_checks.deepseek, 'test', return_value={'connected':True,'generation_started':False}) as test:
            with self.req('/api/agent-settings/deepseek/test', {}) as response:
                self.assertFalse(json.load(response)['generation_started'])
            self.assertEqual(test.call_count, 1)
        with self.req('/api/agent-settings') as response:
            settings=json.load(response);self.assertIn('deepseek_api', settings)
        settings['policy']['default_host']='deepseek_api'
        with self.req('/api/agent-settings', settings['policy']) as response:
            self.assertEqual(json.load(response)['policy']['default_host'], 'deepseek_api')

    def test_browser_manual_check_can_be_claimed_with_zero_automatic_budget(self):
        with self.req('/api/budget',{'daily_checks':0,'daily_tokens':0,'reservation_tokens':30000}) as response:
            budget=json.load(response);self.assertFalse(budget['automatic']['can_start']);self.assertTrue(budget['manual']['can_start'])
        candidate=self.rt.store.upsert_candidate({'name':'Synthetic manual budget','url':'https://example.org/manual-budget','category':'tasks'})
        with self.req('/api/checks/request',{'candidate_id':candidate['id'],'host':'pi'}) as response:job=json.load(response)
        with self.req('/api/checks/claim',{'id':job['id'],'host':'pi'}) as response:claim=json.load(response)
        self.assertEqual(claim['status'],'running');self.assertEqual(claim['origin'],'manual')
        with self.req('/api/checks/complete',{'id':job['id'],'host':'pi','lease_token':claim['lease_token'],'error':'Synthetic controlled failure'}) as response:
            self.assertEqual(json.load(response)['status'],'failed')
        with self.req('/api/checks') as response:
            state=json.load(response);self.assertEqual(state['budget']['manual']['used_checks'],1);self.assertEqual(state['budget']['automatic']['used_checks'],0)

    def test_monitoring_budget_and_scheduler_are_separate_from_formal_observation(self):
        with self.req('/api/monitoring', {'enabled':True}) as response: self.assertTrue(json.load(response)['enabled'])
        with patch.object(self.rt.stop_event,'wait',side_effect=[False,True]), patch.object(self.rt,'do_scan') as scan_once:
            self.rt.loop();scan_once.assert_called_once()
        self.assertEqual(self.rt.observation()['status'],'not_started')
        self.assertTrue(Runtime(Path(self.tmp.name),self.server.server_port).monitoring()['enabled'])
        with self.req('/api/budget',{'daily_checks':0,'daily_tokens':0,'reservation_tokens':30000}) as response: self.assertFalse(json.load(response)['can_start'])
        with self.assertRaises(urllib.error.HTTPError): self.req('/api/budget',{'daily_checks':100,'daily_tokens':0,'reservation_tokens':30000})

    def test_report_to_facts_request_and_preparation_plan_through_http(self):
        from test_workflows import facts_report
        self.rt.store.save_profile({'daily_hours':2,'available_minutes':20,'skill_level':'beginner','max_daily_cost':2})
        cid=self.rt.store.upsert_candidate({'name':'Fixture','category':'pow','url':'https://example.org/project'})['id']
        with self.req('/api/checks/request',{'candidate_id':cid,'host':'pi'}) as response: job=json.load(response)
        with self.req('/api/checks/claim',{'id':job['id'],'host':'pi'}) as response: claim=json.load(response)
        with self.req('/api/checks/complete',{'id':job['id'],'host':'pi','lease_token':claim['lease_token'],'report':facts_report()}) as response:
            self.assertEqual(json.load(response)['fact_sync']['status'],'applied')
        with self.req('/api/state') as response: state=json.load(response)
        self.assertEqual(len(state['participation_requests']),0)  # Unknown wallet/tradability is excluded by the current policy.
        self.assertEqual(len(state['candidates']),0)
        self.assertEqual(len(state['discovery_archive']),1)
        plan=state['preparation_plans'][0]
        self.assertFalse(plan['execution_authorized'])
        with self.req('/api/plans/simulate',{'plan_id':plan['id'],'key':'http-test'}) as response: run=json.load(response)
        self.assertEqual(run['status'],'blocked');self.assertFalse(run['side_effects'])

    def test_economic_scan_skips_legacy_sources(self):
        self.rt.store.set_setting('discovery_policy',{'id':'binance-wallet-tradable-v1'})
        with patch.object(self.rt.executions.mining,'refresh',return_value={'status':'checking'}) as refresh,patch('prospect.service.scan') as legacy:
            with self.req('/api/scan',{}) as response:result=json.load(response)
        self.assertEqual(result['economic_discovery'],'checking');legacy.assert_not_called();refresh.assert_called_once()

    def test_launch_report_creates_priority_todo_without_wallet_or_market_gate(self):
        from test_launch_watch import signal
        cid=self.rt.store.upsert_candidate({'name':'Unpriced native CPU coin','category':'pow','url':'https://example.org/native'})['id']
        with self.req('/api/launch-watch/report',{'candidate_id':cid,'signal':signal()}) as response:row=json.load(response)
        with self.req('/api/state') as response:state=json.load(response)
        self.assertEqual(state['launch_watch']['important_count'],1);self.assertEqual(state['candidates'][0]['id'],cid)
        self.assertEqual(state['candidates'][0]['compute_profile']['priority'],'cpu')
        self.assertFalse(state['discovery_policy']['requires_live_market'])
        with self.req('/api/launch-watch/decision',{'id':row['id'],'status':'watching'}) as response:
            self.assertEqual(json.load(response)['todo_status'],'watching')
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/launch-watch/report',{'candidate_id':cid,'signal':signal()},auth=False)

    def test_report_submission_can_be_corrected_over_http_with_same_lease(self):
        from test_agent_checks import report
        from test_agent_report_recovery import invalid_report
        cid=self.rt.store.upsert_candidate({'name':'Correction fixture','category':'pow','url':'https://example.org/project'})['id']
        for host in ('codex','claude','pi','deepseek'):
            job=self.rt.agent_checks.request(cid,host,dispatch=False);claim=self.rt.agent_checks.claim(host,job['id'])
            payload={'id':job['id'],'host':host,'lease_token':claim['lease_token'],'report':invalid_report(),'usage':{'input_tokens':50,'output_tokens':10}}
            with self.req('/api/checks/complete',payload) as response:self.assertEqual(json.load(response)['status'],'needs_correction')
            with self.assertRaises(urllib.error.HTTPError):self.req('/api/checks/validate',payload,auth=False)
            payload['report']=report();payload.pop('usage')
            with self.req('/api/checks/complete',payload) as response:
                done=json.load(response);self.assertEqual(done['status'],'completed');self.assertEqual(done['usage']['input_tokens'],50)

    def test_announcement_scan_returns_immediately_and_repeated_scan_uses_same_work(self):
        entered=threading.Event();release=threading.Event()
        def fake_scan(*_):
            entered.set();release.wait(8)
            return {'checked':1,'errors':0,'items':0,'changed':0,'unchanged':0,'skipped':0}
        try:
            with patch('prospect.service.scan',side_effect=fake_scan) as scanner:
                with self.req('/api/scan',{}) as response:self.assertEqual(json.load(response)['status'],'checking')
                self.assertTrue(entered.wait(2))
                with self.req('/api/scan',{}) as response:self.assertEqual(json.load(response)['status'],'already_running')
                with self.req('/api/launch-watch') as response:self.assertEqual(json.load(response)['scan']['status'],'running')
                release.set();self.rt.scan_thread.join(3);scanner.assert_called_once()
        finally:release.set()

    def test_launch_assets_are_served_and_previous_observation_cannot_resume_after_policy_change(self):
        for asset in ['/launch-watch.js','/launch-watch.css']:
            with self.req(asset) as response:self.assertEqual(response.status,200)
        self.rt.store.set_setting('observation',{'status':'paused','source_plan':[{'id':'old-source'}]})
        with self.assertRaises(ValueError):self.rt.set_observation('resume')

    def test_unknown_wallet_project_does_not_enter_pending_research(self):
        self.rt.store.upsert_candidate({'name':'Unknown','category':'pow','url':'https://example.org/unknown'})
        self.rt.store.set_setting('discovery_policy',{'id':'binance-wallet-tradable-v1'})
        with patch.object(self.rt.executions.mining,'candidate',return_value=None):
            with self.req('/api/research') as response:jobs=json.load(response)
        self.assertFalse(any(j['status']=='pending' for j in jobs))

    def test_wallet_connect_requires_authenticated_explicit_confirmation(self):
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/wallet/connect',{'confirmed':True},auth=False)
        with self.assertRaises(urllib.error.HTTPError):self.req('/api/wallet/connect',{'confirmed':False})
        with patch.object(self.rt.executions.mining.wallet_connection,'start',return_value={'status':'starting'}) as start:
            with self.req('/api/wallet/connect',{'confirmed':True}) as response:self.assertEqual(json.load(response)['status'],'starting')
            start.assert_called_once_with(True)

    def test_agent_check_api_and_browser_cannot_submit_agent_report(self):
        self.rt.store.upsert_candidate({"name": "Test", "url": "https://example.org/test", "category": "tasks"})
        cid = self.rt.store.candidates()[0]["id"]
        with self.req("/api/checks/request", {"candidate_id": cid, "host": "deepseek"}) as response:
            job = json.load(response)
        with self.req("/api/checks/claim", {"host": "deepseek", "id": job["id"]}) as response:
            claim = json.load(response)
        self.assertEqual(claim["status"], "running")
        with self.req("/api/checks") as response:
            public = json.load(response)
        self.assertNotIn(claim["lease_token"], json.dumps(public))
        self.assertNotIn("lease_hash", json.dumps(public))
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        opener.open(self.base + "/").close()
        for endpoint in ("claim", "complete", "progress"):
            request = urllib.request.Request(self.base + "/api/checks/" + endpoint,
                data=json.dumps({"host": "pi"}).encode(), headers={"Content-Type": "application/json", "Origin": self.base})
            with self.assertRaises(urllib.error.HTTPError) as error: opener.open(request)
            self.assertEqual(error.exception.code, 403)

    def test_cross_origin_rejected_even_with_valid_credential(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.req("/api/profile", {}, extra={"Origin": "https://evil.example"})
        self.assertEqual(error.exception.code, 403)

    def test_multiple_local_services_do_not_replace_browser_sessions(self):
        other = LocalServer(('127.0.0.1',0),Handler)
        other.runtime = Runtime(Path(self.tmp.name)/'other',other.server_port)
        thread = threading.Thread(target=other.serve_forever,daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        urls = [self.base, f'http://127.0.0.1:{other.server_port}']
        try:
            for url in urls:
                with opener.open(url+'/',timeout=3) as response: self.assertEqual(response.status,200)
            for url in urls:
                with opener.open(url+'/api/state',timeout=3) as response: self.assertEqual(response.status,200)
        finally:
            other.shutdown(); other.server_close(); thread.join(2)

    def test_invalid_host_and_sessionless_post_rejected(self):
        with self.assertRaises(urllib.error.HTTPError): self.req("/health", extra={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError): self.req("/api/scan", {}, auth=False)

    def test_observation_needs_168_hours_and_actual_coverage(self):
        self.rt.set_observation("start")
        self.assertFalse(self.rt.observation()["ready_for_review"])
        ob = self.rt.store.get_setting("observation")
        ob["start_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=169)).isoformat()
        self.rt.store.set_setting("observation", ob)
        report = self.rt.observation()
        self.assertFalse(report["ready_for_review"])
        self.assertEqual(report["coverage_pct"], 0)
        self.assertEqual(report["status"], "running")

    def test_observation_scope_frozen_and_pause_preserved(self):
        self.rt.set_observation("start")
        initial = self.rt.observation()
        self.assertEqual(initial["source_plan"][0]["id"], "launch-announcements")
        self.assertEqual((dt.datetime.fromisoformat(initial["target_at"]) - dt.datetime.fromisoformat(initial["start_at"])).total_seconds(), 168 * 3600)
        with self.assertRaises(urllib.error.HTTPError): self.req("/api/sources", {"id": "launch-announcements", "enabled": False})
        self.rt.set_observation("pause")
        self.assertEqual(self.rt.observation()["status"], "paused")
        restarted = Runtime(Path(self.tmp.name), self.server.server_port)
        self.assertEqual(restarted.observation()["status"], "paused")
        with self.assertRaises(ValueError): self.rt.set_observation("start")

    def test_paused_observation_allows_source_changes_without_rewriting_original_plan(self):
        self.rt.set_observation('start')
        original_plan=self.rt.observation()['source_plan']
        source_id=original_plan[0]['id']
        self.rt.set_observation('pause')
        with self.req('/api/sources',{'id':source_id,'enabled':False}) as response:
            self.assertFalse(json.load(response)['enabled'])
        self.assertEqual(self.rt.observation()['source_plan'],original_plan)
        self.assertEqual(self.rt.observation()['status'],'paused')
        with self.assertRaises(ValueError):self.rt.set_observation('resume')
        with self.req('/api/sources',{'id':source_id,'enabled':True}) as response:
            self.assertTrue(json.load(response)['enabled'])
        self.assertEqual(self.rt.set_observation('resume')['status'],'running')

    def test_scans_no_change_no_extra_research(self):
        source = {"id": "test", "label": "Test", "url": "https://api.github.com/search/repositories?q=test",
                  "kind": "github", "category": "node", "enabled": True, "interval_seconds": 60}
        self.rt.store.set_setting("sources", [source])
        payload = json.dumps({"items": [{"id": 1, "full_name": "example/testnet", "html_url": "https://github.com/example/testnet",
                                         "description": "Testnet node"}]}).encode()
        count = 0
        def fake_fetch(s, h):
            nonlocal count
            count += 1
            return (200, {"ETag": "one"}, payload) if count == 1 else (304, {}, b"")
        first = scan(self.rt.store, fake_fetch, force=True)
        jobs = len(self.rt.store.research_jobs())
        for _ in range(100): scan(self.rt.store, fake_fetch, force=True)
        self.assertEqual(first["changed"], 1)
        self.assertEqual(len(self.rt.store.research_jobs()), jobs)
        self.assertEqual(len(self.rt.store.candidates()), 1)
        self.assertEqual(self.rt.store.get_setting("source_health")["test"]["status"], "unchanged")

    def test_failed_source_backoff_and_stale_status(self):
        self.rt.store.set_setting("sources", [{"id": "x", "url": "https://example.com/rss", "kind": "atom",
                                               "category": "node", "enabled": True, "interval_seconds": 60}])
        def fail(s, h): raise ValueError("rate limited")
        result = scan(self.rt.store, fail)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(scan(self.rt.store, fail)["skipped"], 1)
        self.assertEqual(self.rt.store.get_setting("source_health")["x"]["status"], "error")

    def test_live_routes_are_unavailable(self):
        with self.assertRaises(urllib.error.HTTPError) as error: self.req("/api/execute", {"project": "anything"})
        self.assertEqual(error.exception.code, 404)

    def test_profile_rejects_nonfinite_and_negative(self):
        for profile in ({"daily_hours": -1}, {"daily_hours": 25}, {"cpu_limit_pct": 101}, {"max_daily_cost": float("nan")}):
            with self.subTest(profile=profile), self.assertRaises(urllib.error.HTTPError): self.req("/api/profile", profile)


    def test_reviewed_opportunity_creates_request_then_interest_without_execution(self):
        from prospect.domain import now
        data = {'name':'Isolated proposal fixture','url':'https://example.org/fixture','category':'tasks',
                'checked_at':now(),'participation':'open','reward_unit':'points',
                'requirements':{'min_ram_gb':4,'min_disk_gb':2,'min_vram_gb':0,'os':['windows'],
                                'daily_hours':1,'available_minutes':5,'skill_level':'beginner','estimated_daily_cost':0},
                'evidence':[{'url':'https://example.org/official','kind':'official','note':'Fixture official rules, resource requirements and participation; never a real offer',
                             'checked_at':now(),'claims':{'token_issued':'no','cex_spot':'no','dex_spot':'no','premarket':'no'},'scope':'fixture'}]}
        self.rt.store.upsert_candidate(data)
        self.assertEqual(self.rt.refresh_participation(), [])
        job = self.rt.store.research_jobs()[0]
        with self.req('/api/research/resolve',{'id':job['id'],'result':{'candidate':data}}) as response:
            reviewed=json.load(response)
        self.assertEqual(reviewed['participation_requests'], [])
        from test_workflows import facts_report
        reviewed_report=facts_report();reviewed_report['safety_audit']['target_url']=data['url']
        with self.req('/api/research/resolve',{'id':job['id'],'result':{'candidate':data,'host':'pi','report':reviewed_report}}) as response:
            reviewed=json.load(response)
        proposal=reviewed['participation_requests'][0]
        self.assertEqual(proposal['status'],'pending')
        with self.req('/api/participation/decision',{'id':proposal['id'],'decision':'interested'}) as response:
            result=json.load(response)
        self.assertEqual(result['status'],'interested')
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(self.rt.store.runs(),[])
        data['participation']='closed'
        self.rt.store.resolve_research(job['id'],{'candidate':data})
        with self.assertRaises(urllib.error.HTTPError):
            self.req('/api/participation/decision',{'id':proposal['id'],'decision':'interested'})


class SourceSafetyTests(unittest.TestCase):
    def test_directory_lock_rejects_second_owner_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            first = DirectoryLock(Path(temp))
            try:
                with self.assertRaises(RuntimeError): DirectoryLock(Path(temp))
            finally: first.close()
            second = DirectoryLock(Path(temp))
            second.close()

    def test_empty_and_uncached_responses_are_errors(self):
        from prospect.store import Store
        for status in (200, 204, 304):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                store = Store(Path(temp) / "test.sqlite3")
                store.set_setting("sources", [{"id": "x", "url": "https://example.com/rss", "kind": "atom",
                                               "enabled": True, "category": "node", "interval_seconds": 60}])
                result = scan(store, lambda s, h: (status, {}, b""))
                self.assertEqual(result["errors"], 1)
                self.assertEqual(store.get_setting("source_health")["x"]["status"], "error")

    def test_private_sources_rejected(self):
        for url in ("http://example.com", "https://127.0.0.1/x", "https://[::1]/", "https://localhost/x",
                    "https://169.254.169.254/", "https://a:b@example.com", "https://example.com:8443"):
            with self.subTest(url=url), self.assertRaises(ValueError): validate_public_url(url, resolve=False)

    def test_search_result_does_not_claim_unlisted(self):
        result = parse({"kind": "github", "category": "pow"}, json.dumps({"items": [{"id": 1, "full_name": "a/b",
                        "html_url": "https://github.com/a/b", "description": "Guaranteed mining"}]}).encode())
        self.assertEqual(result[0]["market"], {})
        self.assertEqual(result[0]["participation"], "unknown")
        self.assertEqual(result[0]["evidence"][0]["kind"], "discovery")

    def test_missing_legacy_db_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "not-there.sqlite"
            self.assertEqual(import_legacy(None, p)["imported"], 0)
            self.assertFalse(p.exists())


if __name__ == "__main__": unittest.main()
