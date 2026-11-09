"""Isolated synthetic safety/model UI; never dispatches a model or a project."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from prospect.service import Runtime,LocalServer,Handler,write_private
from prospect.agent_settings import AgentSettings
import prospect.agent_checks as checks
from test_workflows import facts_report

parser=argparse.ArgumentParser();parser.add_argument('--data-dir',required=True);parser.add_argument('--port',type=int,default=5711)
args=parser.parse_args();directory=Path(args.data_dir);directory.mkdir(parents=True,exist_ok=True)
checks.find_native=lambda host:None
server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(directory,args.port);server.runtime=rt;rt.server=server
rt.store.set_setting('sources',[]);rt.store.set_setting('agent_budget',{'daily_checks':10,'daily_tokens':500000,'reservation_tokens':30000})
rt.store.save_hardware({'os':'windows','ram_gb':1,'disk_free_gb':1,'vram_gb':0})
rt.agent_checks.settings=AgentSettings(rt.store,directory/'synthetic-home')
for name,status in [('合成项目 · 安全通过但设备不足','pass'),('合成项目 · 等待安全核验','unknown'),('合成项目 · 存在安全问题','fail')]:
    url='https://example.org/'+status
    cid=rt.store.upsert_candidate({'name':name,'url':url,'category':'node'})['id']
    if any(j['candidate_id']==cid for j in rt.agent_checks.jobs()):continue
    job=rt.agent_checks.request(cid,'codex',dispatch=False);lease=rt.agent_checks.claim('codex',job['id'],'native_cli')
    report=facts_report();report['safety_audit']['target_url']=url;report['safety_audit']['status']=status
    report['checks'][-1].update(status=status,finding='Synthetic fixture only: '+status)
    report['checks'][3].update(status='fail',finding='合成设备只有1 GB内存，低于项目要求；这不影响尝试建议。')
    rt.agent_checks.complete(job['id'],'codex',lease['lease_token'],report,usage={'input_tokens':0,'output_tokens':0})
write_private(directory/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
print(json.dumps({'pid':os.getpid(),'port':args.port,'synthetic':True}),flush=True)
try:server.serve_forever(poll_interval=.2)
finally:rt.agent_checks.shutdown();server.server_close()
