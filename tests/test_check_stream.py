import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from prospect.check_stream import activity, consume, native_error
from prospect.agent_checks import AgentChecks, HOSTS
from prospect.store import Store


class NativeStreamTests(unittest.TestCase):
    def test_failed_turn_error_is_read_but_reasoning_is_never_a_diagnostic(self):
        self.assertIn('model_not_found',native_error({'type':'turn.failed','error':{'code':'model_not_found','message':'unavailable','private':'secret'}}))
        self.assertNotIn('secret',native_error({'type':'turn.failed','error':{'code':'model_not_found','private':'secret'}}))
        self.assertEqual(native_error({'type':'item.completed','item':{'type':'reasoning','text':'private reasoning'}}),'')
        self.assertEqual(activity('codex',{'type':'error','message':'Reconnecting... 1/5','will_retry':True}),'retrying')

    def spawn(self, code):
        return subprocess.Popen([sys.executable,"-u","-c",code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")

    def test_events_arrive_before_exit_and_stderr_cannot_deadlock(self):
        child=self.spawn("import sys,time; sys.stdin.read(); print('{\"type\":\"turn.started\"}',flush=True); sys.stderr.write('x'*150000); sys.stderr.flush(); time.sleep(.3); print('{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":1,\"output_tokens\":2}}',flush=True)")
        observed=[];pulses=[]
        def receive(event): observed.append((event,child.poll()))
        tail=consume(child,"readonly",receive,pulses.append,5)
        self.assertEqual(observed[0][0]["type"],"turn.started")
        self.assertIsNone(observed[0][1])
        self.assertEqual(observed[-1][0]["usage"]["output_tokens"],2)
        self.assertLessEqual(len(tail),8192);self.assertIn(True,pulses);self.assertEqual(child.returncode,0)

    def test_timeout_kills_child_without_faking_completion(self):
        child=self.spawn("import time; time.sleep(10)")
        events=[]
        with self.assertRaises(subprocess.TimeoutExpired): consume(child,"",events.append,lambda _:None,.15)
        child.wait(timeout=3)
        self.assertNotEqual(child.returncode,0);self.assertEqual(events,[])

    def test_cancel_can_interrupt_stream(self):
        child=self.spawn("import time; print('{\"type\":\"turn.started\"}',flush=True); time.sleep(10)")
        consume(child,"",lambda _:child.kill(),lambda _:None,3)
        self.assertNotEqual(child.returncode,0)

    def test_activity_contains_only_allowlisted_metadata(self):
        secret="secret raw reasoning or untrusted instruction"
        self.assertEqual(activity("codex",{"type":"item.completed","item":{"type":"reasoning","text":secret}}),"comparing")
        self.assertEqual(activity("codex",{"type":"item.started","item":{"type":"web_search","action":{"type":"open_page","url":secret}}}),"reading")
        self.assertEqual(activity("claude",{"type":"assistant","message":{"content":[{"type":"tool_use","name":"WebSearch","input":secret}]}}),"searching")
        self.assertEqual(activity("claude",{"type":"system","subtype":"api_retry","error":secret}),"retrying")
        self.assertIsNone(activity("codex",{"type":"unknown","text":secret}))


class HostProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/"store.sqlite3")
        self.store.save_hardware({"os":"windows","ram_gb":16,"disk_free_gb":100,"vram_gb":6})
        self.checks=AgentChecks(self.store,Path(self.tmp.name))
        self.cid=self.store.upsert_candidate({"name":"Progress fixture","url":"https://example.org/progress","category":"node"})["id"]
        self.store.set_setting("agent_budget",{"daily_checks":10,"daily_tokens":1000000,"reservation_tokens":30000})
    def tearDown(self): self.tmp.cleanup()

    def test_four_hosts_report_real_stages_with_leases_and_no_model(self):
        for host in HOSTS:
            job=self.checks.request(self.cid,host,dispatch=False);claim=self.checks.claim(host,job["id"])
            update=self.checks.progress(job["id"],host,claim["lease_token"],"searching")
            self.assertEqual(update["activity"][-1]["stage"],"searching")
            self.assertIsNone(update["process_alive"])
            self.assertNotIn(claim["lease_token"],json.dumps(update))
            self.checks.cancel(job["id"])
            with self.assertRaises(ValueError): self.checks.progress(job["id"],host,claim["lease_token"],"writing")

    def test_wrong_lease_and_freeform_progress_rejected(self):
        job=self.checks.request(self.cid,"pi",dispatch=False);claim=self.checks.claim("pi",job["id"])
        for host,token,stage in [("codex",claim["lease_token"],"searching"),("pi","wrong","reading"),("pi",claim["lease_token"],"fake 100 percent"),("pi",claim["lease_token"],[])]:
            with self.assertRaises(ValueError): self.checks.progress(job["id"],host,token,stage)

    def test_heartbeat_is_not_agent_progress_and_history_is_bounded(self):
        job=self.checks.request(self.cid,"pi",dispatch=False);self.checks.claim("pi",job["id"])
        self.checks._activity(job["id"],alive=True)
        public=self.checks.jobs()[0]
        self.assertIsNone(public.get("last_activity_at"));self.assertIn("heartbeat_at",public)
        for i in range(65): self.checks._activity(job["id"],"searching" if i%2 else "reading")
        self.assertEqual(len(self.checks.jobs()[0]["activity"]),60)
        self.assertIsNotNone(self.checks.jobs()[0]["last_activity_at"])

    def test_native_codex_and_claude_stream_to_saved_report_with_real_pipes(self):
        from test_agent_checks import report
        real_spawn=subprocess.Popen
        policy=self.checks.settings.policy()
        policy['hosts']['codex']={'model':'gpt-fixture','effort':'high'}
        policy['hosts']['claude']={'model':'claude-fixture','effort':'medium'}
        self.checks.settings.save(policy)
        for host in ("codex","claude"):
            job=self.checks.request(self.cid,host,dispatch=False)
            observed=[]
            original_activity=self.checks._activity
            def capture(ident,stage=None,alive=None):
                original_activity(ident,stage,alive)
                if stage=="searching": observed.append(self.checks.jobs()[0]["status"])
            def spawn(argv,**kwargs):
                value=report()
                self.assertEqual(argv[argv.index('--model')+1],policy['hosts'][host]['model'])
                if host=="codex":
                    self.assertIn('model_reasoning_effort="high"',argv)
                    self.assertNotIn('model_reasoning_effort="low"',argv)
                    output=argv[argv.index("--output-last-message")+1]
                    lines=[{"type":"turn.started","model":"gpt-fixture"},{"type":"item.started","item":{"type":"web_search","query":"not persisted"}},{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":2}}]
                    script=f"from pathlib import Path;Path({output!r}).write_text({json.dumps(value)!r},encoding='utf-8');"
                else:
                    self.assertIn("stream-json",argv);self.assertIn("--verbose",argv)
                    self.assertEqual(argv[argv.index('--effort')+1],'medium')
                    self.assertEqual(kwargs['env']['CLAUDE_CODE_EFFORT_LEVEL'],'medium')
                    lines=[{"type":"system","subtype":"init","model":"claude-fixture"},{"type":"assistant","message":{"content":[{"type":"tool_use","name":"WebSearch","input":"not persisted"}]}},{"type":"result","structured_output":value,"usage":{"input_tokens":3,"output_tokens":2}}]
                    script=""
                script+="import sys,time;sys.stdin.read();"
                script+=";".join(f"print({json.dumps(event)!r},flush=True);time.sleep(.04)" for event in lines)
                return real_spawn([sys.executable,"-u","-c",script],**kwargs)
            with patch("prospect.agent_checks.find_native",return_value=sys.executable),patch('prospect.agent_checks.native_profile',return_value={}),patch("prospect.agent_checks.subprocess.Popen",side_effect=spawn),patch.object(self.checks,"_activity",side_effect=capture):
                self.checks._native(job["id"],host)
            result=next(j for j in self.checks.jobs() if j["id"]==job["id"])
            self.assertEqual(result["status"],"completed")
            self.assertEqual(result["stage"],"completed")
            self.assertEqual(result["usage"]["input_tokens"],3)
            self.assertEqual(result['runtime_config']['observed_models'],[policy['hosts'][host]['model']])
            self.assertEqual(observed,["running"])
            self.assertNotIn("not persisted",json.dumps(result))
            self.assertNotIn(job["id"],self.checks.processes)
