"""Four generated bridges against an isolated HTTP runtime, with synthetic reports.

No model calls, source scans, mining, wallet use or canonical database writes.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prospect.agent_checks import HOSTS,TOPICS,REPORT_SCHEMA_ID
from prospect.service import Handler,LocalServer,Runtime


def draft():
    url='https://example.org/official-rules'
    return {'verdict':'needs_info','summary':'Synthetic protocol fixture, not a project review.',
        'identity':'Synthetic fixture','checks':[{'topic':topic,'status':'unknown','finding':'Fixture only','sources':[url]} for topic in TOPICS],
        'sources':[{'url':url,'title':'Synthetic source','note':'Fixture only'}],
        'missing_information':['Real project evidence'],'next_steps':['Do not execute this fixture']}


def main():
    results=[]
    with tempfile.TemporaryDirectory(prefix='prospect-agent-protocol-') as temp:
        directory=Path(temp)
        server=LocalServer(('127.0.0.1',0),Handler)
        rt=Runtime(directory,server.server_port);server.runtime=rt
        (directory/'control.json').write_text(json.dumps({'port':server.server_port,'pid':os.getpid(),'token':rt.token}),'utf-8')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            candidate=rt.store.upsert_candidate({'name':'Synthetic fixture','url':'https://example.org/project','category':'pow'})
            for host in HOSTS:
                folder=ROOT/'adapters/prepared-v12'/host
                spec=importlib.util.spec_from_file_location('qa_bridge_'+host,folder/'bridge.py')
                bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
                config=bridge.read_config(folder/'runtime.json')|{'data_dir':str(directory),'port':server.server_port}
                job=rt.agent_checks.request(candidate['id'],host,dispatch=False)
                call=lambda name,args:bridge.call_tool(config,name,args)
                claim=call('prospect_check_claim',{'id':job['id'],'host':host})
                assert claim['report_schema_id']==REPORT_SCHEMA_ID
                lease={'id':job['id'],'host':host,'lease_token':claim['lease_token']}
                invalid=draft();invalid['project_facts']={'identity_matches_candidate':True,'official_url':'https://example.org/project',
                    'facts':[{'field':'participation','value':'not_started','sources':[invalid['sources'][0]['url']],
                              'kind':'official','scope':'mainnet','note':'Synthetic invalid enum'}]}
                correction=call('prospect_check_validate',lease|{'report':invalid,'usage':{'input_tokens':100,'output_tokens':20}})
                assert correction['status']=='needs_correction'
                assert call('prospect_check_complete',lease|{'report':invalid})['status']=='needs_correction'
                staged=directory/'agent-check-work'/job['id']/'report.json'
                assert staged.is_file() and rt.agent_checks.jobs()[0]['status']=='running'
                valid=call('prospect_check_validate',lease|{'report':draft()})
                assert valid['status']=='valid'
                complete=call('prospect_check_complete',lease|{'report':draft()})
                assert complete['status']=='completed' and complete['usage']=={'input_tokens':100,'output_tokens':20}
                assert not staged.exists()
                results.append({'host':host,'tool_count':len(bridge.TOOLS),'report_schema_id':REPORT_SCHEMA_ID,
                    'invalid_validate':'needs_correction','invalid_legacy_complete':'needs_correction',
                    'same_lease_correction':'completed','known_usage_retained':True,'private_staged_report_removed_on_success':True,
                    'observed_models':complete['runtime_config']['observed_models']})
            usage=rt.agent_checks.usage()
            assert usage['agent_check_input_tokens']==400 and usage['agent_check_output_tokens']==80
            assert rt.executions.runs()==[]
        finally:
            rt.agent_checks.shutdown();rt.executions.shutdown()
            server.shutdown();server.server_close();thread.join(3)
    result={'scope':'Isolated generated bridge -> CLI -> HTTP protocol; synthetic reports, not native model acceptance',
        'model_calls':0,'mining_started':False,'canonical_data_changed':False,'hosts':results,'usage':usage}
    (ROOT/'evidence/all-agent-bridge-correction.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
