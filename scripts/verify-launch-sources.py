"""Read-only verification of public announcement connectors; never starts projects."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prospect.sources import fetch,parse
from prospect.launch_watch import defaults

folder=Path(__file__).resolve().parents[1]/'evidence/launch-watch-sources';folder.mkdir(exist_ok=True)
def check(source):
    row={'id':source['id'],'url':source['url']}
    try:
        status,headers,body=fetch(source,{})
        suffix='.html' if source['kind']=='launch_page' else '.json' if source['kind']=='github' else '.xml'
        (folder/(source['id']+suffix)).write_bytes(body)
        items=parse(source,body)
        row.update(status=status,sha256=hashlib.sha256(body).hexdigest(),bytes=len(body),items=len(items),
            signals=[{'name':x['name'],**x['launch_signal']} for x in items[:4]])
    except Exception as exc:row.update(error=str(exc)[:220],error_type=type(exc).__name__)
    return row
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(check,defaults()))
(folder/'verification.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False))
