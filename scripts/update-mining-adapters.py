"""Update only hash-verified Prospect-owned bridge/tools; do not edit host trust or hooks."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adapters.bridge import TOOLS
from prospect.service import data_directory

root=Path(__file__).resolve().parents[1]
targets=[Path.home()/'.codex/plugins/cache/prospect-local-codex/prospect/0.1.0',
         Path.home()/'.claude/plugins/cache/prospect-local-claude/prospect/0.1.0',
         Path.home()/'.pi/agent/extensions/prospect',
         root/'adapters/marketplaces/codex/plugins/prospect',root/'adapters/marketplaces/claude/plugins/prospect']
backup=data_directory()/'backups'/('mining-adapters-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S'))
changes=[]
for target in targets:
    marker=target/'.prospect-owned.json'
    owned=json.loads(marker.read_text('utf-8'))
    assert owned['owner']=='prospect-adapter-v1'
    for name in ['bridge.py','tools.json','runtime.json']:
        assert name in owned['files']
        assert hashlib.sha256((target/name).read_bytes()).hexdigest()==owned['files'][name],f'Locally changed file: {target/name}'
    changes.append((target,owned))
for index,(target,owned) in enumerate(changes):
    destination=backup/str(index);destination.mkdir(parents=True)
    for name in ['bridge.py','tools.json','runtime.json','.prospect-owned.json']:shutil.copy2(target/name,destination/name)
    (target/'bridge.py').write_bytes((root/'adapters/bridge.py').read_bytes())
    (target/'tools.json').write_text(json.dumps(TOOLS,ensure_ascii=False,indent=2),'utf-8')
    config=json.loads((target/'runtime.json').read_text('utf-8'));config['data_dir']=str(data_directory().resolve())
    (target/'runtime.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf-8')
    for name in ['bridge.py','tools.json','runtime.json']:owned['files'][name]=hashlib.sha256((target/name).read_bytes()).hexdigest()
    (target/'.prospect-owned.json').write_text(json.dumps(owned,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'updated_locations':len(changes),'tool_count':len(TOOLS),'host_trust_changed':False,'backup_created':backup.is_dir()}))
