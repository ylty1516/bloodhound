"""Isolated browser fixture. Synthetic reports, no model or project execution."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from prospect.service import Runtime, LocalServer, Handler, write_private
from prospect.workflows import Workflows, ACTIONS
from test_workflows import facts_report

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',required=True);parser.add_argument('--port',type=int,required=True)
args=parser.parse_args();directory=Path(args.data_dir);directory.mkdir(parents=True,exist_ok=True)
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(directory,args.port);server.runtime=rt;rt.server=server
rt.store.set_setting('sources',[])
rt.store.save_hardware({'os':'windows','ram_gb':16,'disk_free_gb':100,'vram_gb':6})
rt.store.save_profile({'daily_hours':2,'available_minutes':20,'skill_level':'beginner','max_daily_cost':2})
cid=rt.store.upsert_candidate({'name':'QA 模拟路线 · 非真实项目','url':'https://example.org/project','category':'pow'})['id']
job=rt.agent_checks.request(cid,'pi',dispatch=False);claim=rt.agent_checks.claim('pi',job['id'])
rt.agent_checks.complete(job['id'],'pi',claim['lease_token'],facts_report())
recipe=json.loads((ROOT/'recipes/opacra-testnet-1.0.0.json').read_text('utf-8'))
recipe.update(id='fixture',candidate_url='https://example.org/project',candidate_identity='https://example.org/project',name='QA 合成配方',evidence=['https://example.org/official-rules'],limitations=['合成测试数据，无外部执行。'],delivery='模拟回执')
recipe['artifact']={'url':'https://example.org/fixture.zip','sha256':'0'*64,'version':'1.0.0','locally_verified':True}
recipe['steps']=[{'action':a,'description':'模拟步骤 '+a,'verification':'只验证流程，不代表外部执行'} for a in ACTIONS]
rt.workflows=Workflows(rt.store,rt.agent_checks,[recipe])
write_private(directory/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
print(json.dumps({'port':args.port,'pid':os.getpid(),'plan_id':rt.workflows.plans()[0]['id'],'synthetic':True}),flush=True)
try: server.serve_forever(poll_interval=.2)
finally: rt.agent_checks.shutdown();server.server_close()
