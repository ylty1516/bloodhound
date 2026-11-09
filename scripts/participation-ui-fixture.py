"""Isolated synthetic participation UI; every model request goes to a local mock."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from prospect.service import Runtime, LocalServer, Handler, write_private
import prospect.agent_checks as checks
from prospect.deepseek_provider import DEFAULT
from test_deepseek_provider import MockAPI, FAKE_KEY
from test_agent_checks import report

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=5714);args=parser.parse_args()
class SlowMock(MockAPI):
    def do_POST(self):time.sleep(4);super().do_POST()
api=ThreadingHTTPServer(('127.0.0.1',0),SlowMock);api.base=f'http://127.0.0.1:{api.server_port}'
api.calls=[];api.code=200;api.redirect=False;api.report=report();api.finish_reason='stop'
threading.Thread(target=api.serve_forever,daemon=True).start()
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(args.data_dir,args.port);server.runtime=rt
checks.api_evidence=lambda context,cancelled:[{'url':'https://example.org/official-rules','text':'Synthetic public evidence, no real project.'}]
rt.store.upsert_candidate({'name':'界面验证项目 · 不参与真实项目','url':'https://example.org/project','category':'tasks'})
rt.agent_checks.deepseek.save(DEFAULT|{'base_url':api.base,'api_key':FAKE_KEY,'enabled':True})
policy=rt.agent_checks.settings.policy();policy['default_host']='deepseek_api';rt.agent_checks.settings.save(policy)
rt.store.set_setting('agent_budget',{'daily_checks':10,'daily_tokens':600000,'reservation_tokens':30000})
write_private(args.data_dir/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
try:server.serve_forever(poll_interval=.2)
finally:rt.agent_checks.shutdown();rt.executions.shutdown();api.shutdown();api.server_close();server.server_close()
