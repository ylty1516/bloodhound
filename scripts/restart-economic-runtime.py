"""One-time safe migration to the user's explicitly requested economic-only scope."""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prospect.cli import request,ensure
from prospect.service import data_directory
from prospect.store import Store
from prospect.executions import ACTIVE

root=data_directory();port=18766
state=request(root,port,'/api/state')
if any(j['status'] in ('queued','running') for j in state['agent_checks']):raise SystemExit('Agent check still active; not restarting')
if any(j['status'] in ACTIVE for j in state['executions']['jobs']):raise SystemExit('Execution still active; not restarting')
backup=root/'backups'/('economic-scope-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
backup.parent.mkdir(exist_ok=True)
with sqlite3.connect(root/'prospect.sqlite3') as source,sqlite3.connect(backup) as target:source.backup(target)
request(root,port,'/api/shutdown',{})
for i in range(100):
    try:request(root,port,'/api/ready');time.sleep(.1)
    except Exception:break
else:raise SystemExit('Old service has not stopped')
store=Store(root/'prospect.sqlite3')
sources=store.get_setting('sources',[])
store.set_setting('legacy_sources_before_economic_scope',sources)
store.set_setting('sources',[s|{'enabled':False,'note':'历史观察来源；当前只寻找币安钱包可收款且已可交易的路线'} for s in sources])
ob=store.get_setting('observation',{})
if ob.get('status')=='running':
    store.set_setting('observation',ob|{'status':'paused','paused_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'scope_replaced_by':'binance-wallet-tradable-v1','scope_change_reason':'User replaced unlisted/testnet discovery with wallet-compatible, tradable economic mining. Original 168h acceptance remains incomplete.'})
store.set_setting('discovery_policy',{'id':'binance-wallet-tradable-v1','exclude_unknowns':True,'exclude_unpriced_testnet_points':True})
ensure(root,port)
request(root,port,'/api/mining/refresh',{})
s=request(root,port,'/api/state')
print(json.dumps({'pid':s['service']['pid'],'backup_created':backup.is_file(),'archived_candidates':len(s['discovery_archive']),
                  'legacy_sources_enabled':sum(bool(x['enabled']) for x in s['sources']),
                  'observation_status':s['observation']['status'],'mining':s['economic_mining']['status']},ensure_ascii=False))
