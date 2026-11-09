"""Isolated zero-automatic-budget UI fixture; no model execution."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from prospect.service import Runtime,LocalServer,Handler,write_private
from prospect.agent_context import process_started

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=5716);args=parser.parse_args()
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(args.data_dir,args.port);server.runtime=rt
candidate=rt.store.upsert_candidate({'name':'手动重试验证项目 · 无真实执行','url':'https://example.org/manual-budget-qa','category':'tasks'})
rt.store.set_setting('agent_budget',{'daily_checks':0,'daily_tokens':0,'reservation_tokens':30000})
rt.agent_context.observe({'host':'codex','pid':os.getpid(),'started':process_started(os.getpid()),'source':'startup'})
for _ in range(2):
    job=rt.agent_checks.request(candidate['id'],'codex',dispatch=False)
    claim=rt.agent_checks.claim('codex',job['id'])
    rt.agent_checks.complete(job['id'],'codex',claim['lease_token'],None,error='界面验证的受控失败，没有调用模型')
original=rt.agent_checks.request
rt.agent_checks.request=lambda candidate_id,host='any':original(candidate_id,host,dispatch=False)
write_private(args.data_dir/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
try:server.serve_forever(poll_interval=.2)
finally:rt.agent_checks.shutdown();rt.executions.shutdown();server.server_close()
