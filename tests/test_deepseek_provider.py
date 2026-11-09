import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from prospect.agent_checks import AgentChecks, REPORT_SCHEMA
from prospect.deepseek_provider import DeepSeekProvider, DEFAULT, endpoint
from prospect.store import Store, _json
from test_agent_checks import report
from prospect.report_protocol import ProviderReportError

FAKE_KEY = 'test-only-not-a-real-provider-key'


class MockAPI(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.server.calls.append(('GET',self.path,None))
        if self.server.redirect:
            self.send_response(302);self.send_header('Location',self.server.base+'/other');self.end_headers();return
        self.send_response(self.server.code);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps({'data':[{'id':'deepseek-flash'},{'id':'deepseek-v4-pro'}],'error':FAKE_KEY}).encode())
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls.append(('POST',self.path,body))
        self.server.authorization=self.headers.get('Authorization')
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        events=[{'model':'deepseek-flash-actual','choices':[{'delta':{'reasoning_content':'private-thought-must-not-be-stored'}}]},
                {'choices':[{'delta':{'content':json.dumps(self.server.report,ensure_ascii=False)},'finish_reason':self.server.finish_reason}]},
                {'choices':[],'usage':{'prompt_tokens':125,'completion_tokens':240}}]
        try:
            for event in events:self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # The client intentionally closes rejected or cancelled streams.


@unittest.skipUnless(os.name=='nt','Windows encrypted credential storage')
class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/'state.db')
        self.checks=AgentChecks(self.store,self.root);self.provider=self.checks.deepseek
        self.server=ThreadingHTTPServer(('127.0.0.1',0),MockAPI);self.server.base=f'http://127.0.0.1:{self.server.server_port}'
        self.server.calls=[];self.server.code=200;self.server.redirect=False;self.server.report=report();self.server.finish_reason='stop'
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.config=DEFAULT|{'base_url':self.server.base,'enabled':True,'api_key':FAKE_KEY}
        self.provider.save(self.config)
        self.store.set_setting('agent_budget',{'daily_checks':10,'daily_tokens':600000,'reservation_tokens':30000})
        self.cid=self.store.upsert_candidate({'name':'Fixture','url':'https://example.org/project','category':'tasks'})['id']
        self.packet=[{'url':'https://example.org/official-rules','text':'Synthetic public evidence only'}]

    def tearDown(self):
        self.checks.shutdown();self.server.shutdown();self.server.server_close();self.thread.join(2);self.tmp.cleanup()

    def review(self, cancelled=None):
        stages=[];models=[]
        result,usage=self.provider.review(self.provider.config(),'fixture',REPORT_SCHEMA,self.packet,cancelled or threading.Event(),stages.append,models.append)
        return result,usage,stages,models

    def test_dpapi_storage_redacted_views_and_key_preservation(self):
        view=self.provider.view();self.assertTrue(view['key_configured']);self.assertNotIn(FAKE_KEY,_json(view))
        self.assertNotIn(FAKE_KEY,_json(self.provider.config()))
        for path in self.provider.directory.iterdir():self.assertNotIn(FAKE_KEY.encode(),path.read_bytes())
        self.assertNotIn(FAKE_KEY.encode(),self.store.path.read_bytes())
        old=self.provider.config()['credential_ref'];self.provider.save(self.config|{'api_key':''})
        self.assertEqual(self.provider.config()['credential_ref'],old)
        self.assertEqual(self.provider._key(self.provider.config()),FAKE_KEY)
        result=self.provider.save(self.config|{'enabled':False,'api_key':'','remove_key':True})
        self.assertFalse(result['key_configured']);self.assertFalse((self.provider.directory/(old+'.bin')).exists())

    def test_endpoint_change_requires_reentering_destination_key(self):
        with self.assertRaises(ValueError):self.provider.save(self.config|{'api_key':'','base_url':'https://example.com/v1'})
        self.assertEqual(self.provider.config()['base_url'],self.server.base)

    def test_models_connection_test_has_no_generation_and_no_secret_echo(self):
        result=self.provider.test();self.assertTrue(result['connected']);self.assertFalse(result['generation_started'])
        self.assertEqual(len(result['models']),2);self.assertEqual([c[0] for c in self.server.calls],['GET'])
        self.assertNotIn(FAKE_KEY,_json(result))

    def test_auth_errors_and_redirects_never_echo_key_or_follow_redirect(self):
        self.server.code=401
        with self.assertRaises(ValueError) as exc:self.provider.test()
        self.assertIn('401',str(exc.exception));self.assertNotIn(FAKE_KEY,str(exc.exception))
        self.server.code=200;self.server.redirect=True
        with self.assertRaises(ValueError):self.provider.test()
        self.assertEqual([c[1] for c in self.server.calls],['/models','/models'])

    def test_real_http_sse_parameters_usage_and_reasoning_privacy(self):
        result,usage,stages,models=self.review()
        self.assertEqual(result,report());self.assertEqual(usage,{'input_tokens':125,'output_tokens':240})
        self.assertEqual(models,['deepseek-flash-actual']);self.assertIn('writing',stages)
        payload=self.server.calls[-1][2]
        self.assertEqual(payload['model'],'deepseek-flash');self.assertEqual(payload['reasoning_effort'],'high')
        self.assertEqual(payload['thinking'],{'type':'enabled'});self.assertEqual(self.server.authorization,'Bearer '+FAKE_KEY)
        self.assertNotIn(FAKE_KEY,_json(payload));self.assertNotIn('private-thought',_json(result))

    def test_thinking_off_and_cancel_before_request(self):
        self.provider.save(self.config|{'effort':'off','api_key':''})
        self.review();body=self.server.calls[-1][2]
        self.assertNotIn('reasoning_effort',body);self.assertEqual(body['thinking'],{'type':'disabled'})
        cancelled=threading.Event();cancelled.set();before=len(self.server.calls)
        with self.assertRaises(InterruptedError):self.review(cancelled)
        self.assertEqual(len(self.server.calls),before)

    def test_truncated_or_uncited_result_rejected(self):
        self.server.finish_reason='length'
        with self.assertRaises(ValueError):self.review()
        self.server.finish_reason='stop';self.server.report['sources'][0]['url']='https://invented.example/'
        with self.assertRaises(ValueError):self.review()

    def test_truncated_response_retains_usage_and_does_not_retain_reasoning(self):
        self.server.finish_reason='length'
        with self.assertRaises(ProviderReportError) as error:self.review()
        self.assertEqual(error.exception.usage,{'input_tokens':125,'output_tokens':240})
        self.assertNotIn('private-thought',error.exception.report_text)

    def test_known_model_mismatch_stops_before_generation_without_switching_models(self):
        self.provider.test();self.provider.save(self.config|{'api_key':'','model':'not-in-catalog'})
        before=len(self.server.calls)
        with self.assertRaises(ValueError) as error:self.review()
        self.assertIn('模型列表',str(error.exception));self.assertEqual(len(self.server.calls),before)
        self.assertEqual(self.provider.config()['model'],'not-in-catalog')
        catalog=self.store.get_setting('deepseek_model_catalog');catalog['checked_epoch']=0
        self.store.set_setting('deepseek_model_catalog',catalog)
        self.assertFalse(self.provider.preflight(self.provider.config())['model_verified'])

    def test_api_report_validation_preserves_usage_and_private_unaccepted_report(self):
        from test_agent_report_recovery import invalid_report
        self.server.report=invalid_report();job=self.checks.request(self.cid,'deepseek_api',dispatch=False)
        with patch('prospect.agent_checks.api_evidence',return_value=self.packet):self.checks._api(job['id'])
        failed=next(j for j in self.checks.jobs() if j['id']==job['id'])
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['usage']['input_tokens'],125)
        self.assertEqual(failed['failure']['source'],'report_validation')
        path=Path(self.tmp.name)/'agent-check-work'/job['id']/'report.json';self.assertTrue(path.is_file())
        self.assertNotIn(FAKE_KEY,path.read_text('utf-8'));self.assertNotIn('private-thought',path.read_text('utf-8'))

    def test_evidence_packet_never_claims_completed_source_code_audit(self):
        self.server.report['safety_audit']={'method':'source_review','status':'pass','findings':[]}
        result,*_=self.review()
        self.assertEqual(result['safety_audit']['status'],'unknown')
        self.assertEqual(next(c for c in result['checks'] if c['topic']=='risk')['status'],'unknown')

    def test_api_dispatch_report_budget_history_and_frozen_settings(self):
        self.store.set_setting('agent_budget',{'daily_checks':0,'daily_tokens':0,'reservation_tokens':30000})
        with patch('prospect.agent_checks.api_evidence',return_value=self.packet):
            job=self.checks.request(self.cid,'deepseek_api')
            for _ in range(100):
                latest=next(j for j in self.checks.jobs() if j['id']==job['id'])
                if latest['status'] not in ('queued','running'):break
                time.sleep(.03)
        self.assertEqual(latest['status'],'completed');self.assertEqual(latest['method'],'provider_api')
        self.assertEqual(latest['runtime_config']['requested_model'],'deepseek-flash')
        self.assertEqual(latest['runtime_config']['observed_models'],['deepseek-flash-actual'])
        self.assertEqual(self.checks.budget()['measured_tokens'],365)
        self.assertEqual(self.checks.budget()['manual']['used_checks'],1)
        self.assertFalse(self.checks.budget()['automatic']['can_start'])
        self.assertNotIn('private-thought',_json(latest));self.assertNotIn(FAKE_KEY,_json(latest))
        self.assertTrue(self.checks.request(self.cid,'deepseek_api',dispatch=False)['reused'])
        self.provider.save(self.config|{'api_key':'','effort':'low'})
        new=self.checks.request(self.cid,'deepseek_api',dispatch=False);self.assertFalse(new['reused'])
        self.provider.save(self.config|{'api_key':'','effort':'off'})
        self.checks._api(new['id'])
        self.assertEqual(self.checks.jobs()[0]['status'],'failed')
        self.assertEqual(len([c for c in self.server.calls if c[0]=='POST']),1)

    def test_disabled_endpoint_does_not_queue_or_consume_budget(self):
        self.provider.save(self.config|{'enabled':False,'api_key':''})
        with self.assertRaises(ValueError):self.checks.request(self.cid,'deepseek_api')
        self.assertEqual(self.checks.jobs(),[]);self.assertEqual(self.checks.budget()['used_checks'],0)

    def test_invalid_settings_do_not_change_previous_configuration(self):
        saved=self.provider.config()
        for override in ({'max_tokens':True},{'max_tokens':1},{'effort':'ultra'},{'model':'sk-do-not-paste-keys'},{'api_key':'x\r\nHeader: secret'}):
            with self.subTest(override=override),self.assertRaises(ValueError):self.provider.save(self.config|override)
        self.assertEqual(self.provider.config(),saved)


class EndpointTests(unittest.TestCase):
    def test_allowed_and_disallowed_urls(self):
        for url in ('https://api.deepseek.com','https://gateway.example/v1','http://127.0.0.1:31337/v1'):
            self.assertEqual(endpoint(url+'/'),url)
        for url in ('http://example.com','https://user:secret@example.com','https://example.com?key=secret','https://example.com/chat/completions','https://example.com:wrong','file:///secret'):
            with self.subTest(url=url),self.assertRaises(ValueError):endpoint(url)
