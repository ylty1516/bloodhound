"""Isolated UI/API fixture. Local fake credentials and mock inference only."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from prospect.service import Runtime, LocalServer, Handler, write_private
from test_deepseek_provider import MockAPI
from test_agent_checks import report

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=5713)
args=parser.parse_args()
api=ThreadingHTTPServer(('127.0.0.1',0),MockAPI);api.base=f'http://127.0.0.1:{api.server_port}'
api.calls=[];api.code=200;api.redirect=False;api.report=report();api.finish_reason='stop'
threading.Thread(target=api.serve_forever,daemon=True).start()
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(args.data_dir,args.port);server.runtime=rt
write_private(args.data_dir/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
write_private(args.data_dir/'fixture.json',{'api_base':api.base,'port':args.port,'pid':os.getpid(),'mock_only':True})
print(json.dumps({'api_base':api.base,'port':args.port,'pid':os.getpid()}),flush=True)
try: server.serve_forever(poll_interval=.2)
finally: rt.agent_checks.shutdown();rt.executions.shutdown();api.shutdown();api.server_close();server.server_close()
