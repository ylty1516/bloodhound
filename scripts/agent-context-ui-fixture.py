"""Isolated automatic-host UI validation; queued checks never invoke a model."""
import argparse
import os
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from prospect.service import Runtime,LocalServer,Handler,write_private
from prospect.agent_context import process_started

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=5715);args=parser.parse_args()
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(args.data_dir,args.port);server.runtime=rt
rt.store.upsert_candidate({'name':'自动识别验证项目 · 无真实执行','url':'https://example.org/agent-context-qa','category':'tasks'})
rt.agent_context.observe({'host':'codex','pid':os.getpid(),'started':process_started(os.getpid()),'source':'startup'})
policy=rt.agent_checks.settings.policy();policy['default_host']='deepseek_api';rt.agent_checks.settings.save(policy)
original=rt.agent_checks.request
rt.agent_checks.request=lambda candidate_id,host='any':original(candidate_id,host,dispatch=False)
rt.store.set_setting('agent_budget',{'daily_checks':10,'daily_tokens':600000,'reservation_tokens':30000})
write_private(args.data_dir/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
try:server.serve_forever(poll_interval=.2)
finally:rt.agent_checks.shutdown();rt.executions.shutdown();server.server_close()
