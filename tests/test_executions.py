import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from prospect.executions import Executions, ACTIVE, clean_log
from prospect.execution_drivers import SELF_CHECK, OPACRA, MINER, PACKAGE_SHA, PACKAGE_URL, prepare_package, validate_inputs, isolated_env
from prospect.store import Store, _json


class Plans:
    def __init__(self):
        self.plan = {"id":"p1","candidate_id":"c1","candidate_name":"Synthetic fixture", "fingerprint":"fixed",
                     "recipe":{"id":"opacra-testnet","artifact":{"url":PACKAGE_URL,"sha256":PACKAGE_SHA}},
                     "recommendation":{"status":"suggested_trial","notes":["硬件未匹配，仅作建议"],
                       "audit":{"status":"pass","version":"1.0.0","artifact_sha256":PACKAGE_SHA,"method":"source_review"}}}
    def plans(self): return [copy.deepcopy(self.plan)]


@unittest.skipUnless(os.name == 'nt', 'Windows Job Objects')
class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='prospect-execution-test-')
        self.root=Path(self.temp.name);self.store=Store(self.root/'state.db');self.plans=Plans()
        self.engine=Executions(self.store,self.plans,self.root)

    def tearDown(self):
        self.engine.shutdown()
        # Windows can report process exit just before releasing the process working directory.
        for attempt in range(20):
            try:
                self.temp.cleanup();break
            except PermissionError:
                if attempt == 19: raise
                time.sleep(.1)

    def wait(self, ident, status=None, timeout=10):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            job=self.engine.get(ident)
            if status and job['status']==status: return job
            if not status and job['status'] not in ACTIVE and job.get('receipt'): return job
            time.sleep(.05)
        self.fail(f"Task did not reach {status or 'terminal receipt'}: {self.engine.get(ident)}")

    def start(self, **options):
        quote=self.engine.preview(options=options)
        return self.engine.start(quote['id'],'test',True)

    def spec(self, body):
        script=self.root/'fixture.py';script.write_text(body,'utf-8')
        with Path(sys.executable).open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        return {'driver':'test-fixture','argv':[sys.executable,'-u',str(script)],'executable_sha256':digest}

    def test_real_process_success_limits_logs_receipt_and_durable_state(self):
        with patch('prospect.executions.build_spec',return_value={'driver':SELF_CHECK,'seconds':.2}):
            job=self.wait(self.start()['id'])
        self.assertEqual(job['status'],'completed');self.assertTrue(job['diagnostic_verified'])
        self.assertEqual(job['limits_applied']['cpu_percent'],10);self.assertTrue(job['limits_applied']['kill_on_close'])
        self.assertEqual(job['limits_applied']['memory_mb'],256)
        self.assertFalse(job['rewards_verified']);self.assertGreater(job['limits_applied']['peak_memory_mb'],0)
        lines=self.engine.logs(job['id']);self.assertTrue(any('4/4' in l['line'] for l in lines['lines']))
        self.assertTrue(any('本机自检 4/4' in l['line'] for l in lines['lines']))
        self.assertNotIn('\ufffd',_json(lines))
        self.assertEqual(self.engine.logs(job['id'],lines['cursor'])['lines'],[])
        receipt=self.engine.receipt(job['id']);self.assertEqual(receipt['status'],'completed')
        digest=hashlib.sha256((self.root/'executions'/job['id']/'receipt.json').read_bytes()).hexdigest()
        self.assertEqual(digest,job['receipt']['sha256'])
        recovered=Executions(self.store,self.plans,self.root);recovered.recover()
        self.assertEqual(recovered.get(job['id'])['status'],'completed')

    def test_duplicate_click_and_parallel_start_cannot_duplicate_processes(self):
        quote=self.engine.preview();first=self.engine.start(quote['id'],'a',True)
        again=self.engine.start(quote['id'],'different-key',True)
        self.assertTrue(again['reused']);self.assertEqual(again['id'],first['id'])
        with self.assertRaises(ValueError): self.start()
        self.engine.cancel(first['id']);self.assertEqual(self.wait(first['id'])['status'],'cancelled')

    def test_cancel_cleans_real_child_process_tree(self):
        spec=self.spec("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])\nPath('child.pid').write_text(str(p.pid))\nprint('child ready',flush=True)\ntime.sleep(120)\n")
        with patch('prospect.executions.build_spec',return_value=spec):
            job=self.start();self.wait(job['id'],'running')
            child_file=self.root/'executions'/job['id']/'child.pid'
            child_text=''
            for _ in range(100):
                if child_file.exists():
                    child_text=child_file.read_text()
                    if child_text.isdigit():break
                time.sleep(.03)
            self.assertTrue(child_text.isdigit(),'Child PID was not written')
            child=int(child_text)
            self.engine.cancel(job['id']);self.assertEqual(self.wait(job['id'])['status'],'cancelled')
        self.assertFalse(process_alive(child))

    def test_timeout_stops_real_process_and_is_not_reported_as_success(self):
        with patch('prospect.executions.build_spec',return_value=self.spec('import time\ntime.sleep(120)\n')):
            job=self.wait(self.start(duration_seconds=5)['id'])
        self.assertEqual(job['status'],'timed_out');self.assertFalse(job['rewards_verified'])

    def test_nonzero_exit_redaction_and_forged_self_check_result(self):
        spec=self.spec("print('private_key=never-save-this')\nraise SystemExit(7)\n")
        with patch('prospect.executions.build_spec',return_value=spec): job=self.wait(self.start()['id'])
        self.assertEqual(job['status'],'failed');self.assertEqual(job['exit_code'],7)
        self.assertNotIn('never-save-this',_json(self.engine.logs(job['id'])))
        spec=self.spec("print('exit zero is not verified self-check')\n")
        with patch('prospect.executions.build_spec',return_value=spec): job=self.wait(self.start()['id'])
        self.assertEqual(job['status'],'failed');self.assertNotIn('diagnostic_verified',job)

    def test_no_dispatch_for_missing_confirmation_bad_quote_or_stale_binding(self):
        quote=self.engine.preview()
        with self.assertRaises(ValueError):self.engine.start(quote['id'],'x',False)
        with self.assertRaises(ValueError):self.engine.start('absent','x',True)
        project=self.engine.preview(OPACRA,'p1',{'idle_only':False})
        self.assertTrue(project['ready'])
        self.plans.plan['fingerprint']='changed'
        with self.assertRaises(ValueError):self.engine.start(project['id'],'x',True)
        self.assertEqual(self.engine.runs(),[])

    def test_audit_hash_and_project_binding_required_hardware_advisory(self):
        self.assertTrue(self.engine.preview(OPACRA,'p1')['ready'])
        self.plans.plan['recommendation']['audit']['artifact_sha256']=''
        self.assertFalse(self.engine.preview(OPACRA,'p1')['ready'])
        self.plans.plan['recommendation']['audit']['artifact_sha256']=PACKAGE_SHA
        self.plans.plan['recipe']['id']='other-project'
        self.assertFalse(self.engine.preview(OPACRA,'p1')['ready'])

    def test_invalid_options_and_address_never_become_commands(self):
        for options in ({'command':'calc.exe'},{'cpu_percent':True},{'duration_seconds':0},{'memory_mb':999999},{'idle_only':'false'}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.engine.preview(options=options)
        for inputs in ({'public_address':'x; calc.exe'},{'public_address':'Te'+'a'*93,'extra':'x'},{'private_key':'x'}):
            with self.assertRaises(ValueError):validate_inputs(MINER,inputs)
        self.assertEqual(validate_inputs(MINER,{'public_address':'Te'+'a'*93})['public_address'],'Te'+'a'*93)

    def test_waiting_idle_cancel_and_active_use_stops_job(self):
        with patch('prospect.executions.idle_seconds',return_value=0):
            job=self.start(idle_only=True);self.wait(job['id'],'waiting_idle');self.engine.cancel(job['id'])
            self.assertEqual(self.wait(job['id'])['status'],'cancelled')
        with patch('prospect.executions.idle_seconds',side_effect=[150,0]),patch('prospect.executions.build_spec',return_value={'driver':SELF_CHECK,'seconds':12}):
            job=self.wait(self.start(idle_only=True)['id'])
        self.assertEqual(job['status'],'paused')

    def test_prepare_error_cancellation_and_limit_failure_do_not_launch_project(self):
        for error in (ValueError('bad hash'),OSError('job setup failed')):
            with patch('prospect.executions.build_spec',side_effect=error):job=self.wait(self.start()['id'])
            self.assertEqual(job['status'],'failed');self.assertNotIn('pid',job)
        with patch('prospect.executions.Job',side_effect=OSError('limits unavailable')):
            job=self.wait(self.start()['id'])
        self.assertEqual(job['status'],'failed');self.assertNotIn('pid',job)

    def test_recovery_marks_interruption_without_relaunch(self):
        job={'id':'exec_recovery','status':'running','message':'old','mode':'live'}
        with self.store._connection(write=True) as db:db.execute('INSERT INTO execution_runs VALUES(?,?)',(job['id'],_json(job)))
        self.engine.recover();job=self.engine.get(job['id'])
        self.assertEqual(job['status'],'interrupted');self.assertTrue(job['receipt']['available'])
        self.assertEqual(self.engine.workers,{})

    def test_environment_never_inherits_provider_credentials(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'not-real','WALLET_PRIVATE_KEY':'not-real','PATH':'host-path'}):
            env=isolated_env(self.root)
        self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('WALLET_PRIVATE_KEY',env)
        self.assertNotEqual(env['PATH'],'host-path');self.assertEqual(env['USERPROFILE'],str(self.root/'home'))

    def test_memory_limit_is_enforced_by_windows(self):
        spec=self.spec("blob=bytearray(350000000)\nprint('unexpected allocation')\n")
        with patch('prospect.executions.build_spec',return_value=spec):job=self.wait(self.start(memory_mb=128)['id'])
        self.assertEqual(job['status'],'failed');self.assertNotEqual(job['exit_code'],0)
        self.assertNotIn('unexpected allocation',_json(self.engine.logs(job['id'])))

    def test_abrupt_owner_crash_closes_job_and_kills_descendant(self):
        project_root=Path(__file__).resolve().parents[1]
        supervisor=self.root/'supervisor.py'
        supervisor.write_text("import sys,subprocess,time,json\nfrom pathlib import Path\n"
            +f"sys.path.insert(0,{str(project_root)!r})\n"
            +"from prospect.process_limits import Job\n"
            +"job=Job(10,256)\n"
            +"p=subprocess.Popen([sys.executable,'-u','-c',\"import sys,time;sys.stdin.readline();time.sleep(120)\"],stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)\n"
            +"job.assign(p);p.stdin.write(b'go\\n');p.stdin.flush()\nPath('owned.pid').write_text(str(p.pid))\ntime.sleep(120)\n",'utf-8')
        supervisor_process=subprocess.Popen([sys.executable,str(supervisor)],cwd=self.root,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                if (self.root/'owned.pid').exists():break
                time.sleep(.05)
            child=int((self.root/'owned.pid').read_text());self.assertTrue(process_alive(child))
            supervisor_process.kill();supervisor_process.wait(3)
            for _ in range(50):
                if not process_alive(child):break
                time.sleep(.05)
            self.assertFalse(process_alive(child))
        finally:
            if supervisor_process.poll() is None:supervisor_process.kill();supervisor_process.wait(3)

    def test_logs_are_bounded_and_secret_lines_hidden(self):
        job=self.start();self.engine.cancel(job['id']);self.wait(job['id'])
        for i in range(620):self.engine.log(job['id'],f'line {i}')
        with self.store._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM execution_logs').fetchone()[0],600)
        self.assertEqual(len(self.engine.logs(job['id'])['lines']),200)
        self.assertNotIn('sk-'+'x'*30,clean_log('token '+'sk-'+'x'*30))


def process_alive(pid):
    import ctypes
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];api.OpenProcess.restype=ctypes.c_void_p
    api.CloseHandle.argtypes=[ctypes.c_void_p];api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    handle=api.OpenProcess(0x1000,False,pid)
    if not handle:return False
    result=ctypes.c_ulong();api.GetExitCodeProcess(handle,ctypes.byref(result));api.CloseHandle(handle)
    return result.value==259


class ArtifactTests(unittest.TestCase):
    def package(self, members):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            for name,value in members.items():z.writestr(name,value)
        return buf.getvalue()

    def prepare(self, payload):
        digest=hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temp,patch('prospect.execution_drivers.PACKAGE_SHA',digest),patch('prospect.execution_drivers.validate_public_url'),patch('prospect.execution_drivers.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(payload)
            path=prepare_package(Path(temp),lambda _:None,threading.Event())
            return path.read_bytes()

    def test_verified_zip_extracts_fixed_native_entry(self):
        self.assertEqual(self.prepare(self.package({'release/opacrad.exe':b'benign static fixture','wallet.exe':b'never-extract'})),b'benign static fixture')

    def test_zip_traversal_duplicate_and_missing_entry_rejected(self):
        for names in ({'../opacrad.exe':b'x'},{'a/opacrad.exe':b'x','b/opacrad.exe':b'y'},{'wallet.exe':b'x'},{'c:/opacrad.exe':b'x'}):
            with self.subTest(names=names),self.assertRaises(ValueError):self.prepare(self.package(names))

    def test_hash_mismatch_never_extracts_or_runs(self):
        with tempfile.TemporaryDirectory() as temp,patch('prospect.execution_drivers.validate_public_url'),patch('prospect.execution_drivers.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(self.package({'opacrad.exe':b'x'}))
            with self.assertRaises(ValueError):prepare_package(Path(temp),lambda _:None,threading.Event())
            self.assertFalse((Path(temp)/'bin').exists())
