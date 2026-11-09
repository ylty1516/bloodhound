"""Synthetic CPU/GPU/readiness UI states. Model and project execution disabled."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from prospect.service import Runtime,LocalServer,Handler,write_private
from prospect.agent_context import process_started
from prospect.sources import now
from test_agent_checks import report

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=5717);args=parser.parse_args()
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(args.data_dir,args.port);server.runtime=rt
cpu=rt.store.upsert_candidate({'name':'界面验证 · CPU 测试网路线','url':'https://example.org/cpu-route','summary':'Synthetic CPU route, no real execution','category':'pow'})
cpu=rt.store.get_candidate(cpu['id'])
rt.store.upsert_candidate({'name':'界面验证 · GPU 数据线索','url':'https://example.org/gpu-hint','summary':'Synthetic GPU CUDA contribution hint','category':'node'})
web=rt.store.upsert_candidate({'name':'界面验证 · 网页任务','url':'https://example.org/browser-task','category':'tasks'})
job=rt.agent_checks.request(web['id'],'pi',dispatch=False)
if job['status']!='completed':
    claim=rt.agent_checks.claim('pi',job['id'])
    r=report();r['compute_profile']={'priority':'none','reason':'Synthetic browser task','sources':[r['sources'][0]['url']]}
    rt.agent_checks.complete(job['id'],'pi',claim['lease_token'],r)
recipe=json.loads((ROOT/'recipes/opacra-testnet-1.0.0.json').read_text('utf-8'))
plan={'id':'fixture_cpu_plan','check_id':'fixture_report','candidate_id':cpu['id'],'candidate_name':cpu['name'],'fingerprint':'f'*64,'status':'needs_information','created_at':now(),
    'recipe':recipe,'execution_drivers':['opacra-testnet-node','opacra-testnet-cpu'],'recommendation':{'status':'audit_pending','reason':'Synthetic pending program review','notes':[]},
    'summary':'Synthetic preparation state','sources':[],'fact_sync':{'status':'report_only','reason':'Synthetic fixture'},'blockers':['Synthetic program review pending'],'next_steps':[]}
def plans():
    value=copy.deepcopy(plan)
    if (args.data_dir/'ready-fixture.flag').exists():
        value['recommendation']={'status':'suggested_trial','reason':'Synthetic ready state','notes':[],'audit':{'version':'1.0.0','artifact_sha256':recipe['artifact']['sha256'],'method':'source_review'}}
        value['blockers']=[]
    return [value]
rt.workflows.plans=plans
original=rt.agent_checks.request;rt.agent_checks.request=lambda candidate_id,host='any':original(candidate_id,host,dispatch=False)
def blocked_start(**_):raise ValueError('UI fixture never runs project software')
rt.executions.start=blocked_start
rt.agent_context.observe({'host':'codex','pid':os.getpid(),'started':process_started(os.getpid()),'source':'startup'})
write_private(args.data_dir/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
try:server.serve_forever(poll_interval=.2)
finally:rt.agent_checks.shutdown();rt.executions.shutdown();server.server_close()
