"""Isolated UI fixture: real local IPC, synthetic progress, no model or project execution."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from prospect.service import Runtime,LocalServer,Handler,write_private
from prospect.cli import request
import prospect.agent_checks as checks
from test_agent_checks import report

parser=argparse.ArgumentParser();parser.add_argument('action',choices=['serve','claim','searching','reading','writing','finish']);parser.add_argument('--data-dir',required=True);parser.add_argument('--port',type=int,default=5710)
args=parser.parse_args();directory=Path(args.data_dir);directory.mkdir(parents=True,exist_ok=True)
if args.action=='serve':
    checks.find_native=lambda host:None
    server=LocalServer(('127.0.0.1',args.port),Handler);rt=Runtime(directory,args.port);server.runtime=rt;rt.server=server
    rt.store.set_setting('sources',[]);rt.store.set_setting('agent_budget',{'daily_checks':10,'daily_tokens':500000,'reservation_tokens':30000})
    rt.store.save_hardware({'os':'windows','ram_gb':16,'disk_free_gb':100,'vram_gb':6})
    cid=rt.store.upsert_candidate({'name':'进度交互验证 · 合成项目','url':'https://example.org/progress-qa','category':'node'})['id']
    job=rt.agent_checks.request(cid,'pi',dispatch=False)
    write_private(directory/'fixture.json',{'id':job['id']})
    write_private(directory/'control.json',{'port':args.port,'token':rt.token,'pid':os.getpid()})
    print(json.dumps({'pid':os.getpid(),'port':args.port,'job_id':job['id'],'synthetic':True}),flush=True)
    try:server.serve_forever(poll_interval=.2)
    finally:rt.agent_checks.shutdown();server.server_close()
else:
    fixture=json.loads((directory/'fixture.json').read_text('utf-8'));body={'id':fixture['id'],'host':'pi'}
    if args.action=='claim':
        response=request(directory,args.port,'/api/checks/claim',body);fixture['lease_token']=response['lease_token'];write_private(directory/'fixture.json',fixture)
    else:
        body['lease_token']=fixture['lease_token']
        if args.action=='finish': body['report']=report();response=request(directory,args.port,'/api/checks/complete',body)
        else:body['stage']=args.action;response=request(directory,args.port,'/api/checks/progress',body)
    print(json.dumps({k:response.get(k) for k in ('id','status','stage')},ensure_ascii=True))
