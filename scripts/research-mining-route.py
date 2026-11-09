"""Public-source evidence only. Downloads never execute during research."""
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prospect.service import data_directory

out = Path('evidence/mining-route-research')
out.mkdir(exist_ok=True)
cache = data_directory() / 'artifacts'
cache.mkdir(exist_ok=True)

def get(url, limit=25_000_000):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies_registry()))
    with opener.open(urllib.request.Request(url, headers={'User-Agent':'Prospect/0.1 public route verification'}), timeout=30) as r:
        data=r.read(limit+1)
    if len(data)>limit: raise ValueError('Response too large')
    return data

release=json.loads(get('https://api.github.com/repos/xmrig/xmrig/releases/tags/v6.26.0'))
asset=next(a for a in release['assets'] if a['name']=='xmrig-6.26.0-windows-x64.zip')
package=cache/asset['name']
if not package.exists(): package.write_bytes(get(asset['browser_download_url']))
digest=hashlib.sha256(package.read_bytes()).hexdigest()
assert 'sha256:'+digest==asset['digest'], 'Release digest mismatch'
sums=get('https://github.com/xmrig/xmrig/releases/download/v6.26.0/SHA256SUMS').decode()
assert any(line.split()[0]==digest and line.split()[-1].lstrip('*')==asset['name'] for line in sums.splitlines() if line.strip()), 'Publisher sums mismatch'
(out/'release.json').write_text(json.dumps(release, indent=2),'utf-8')
(out/'SHA256SUMS').write_text(sums,'utf-8')
with zipfile.ZipFile(package) as z: print('PACKAGE',digest, z.namelist())

paths=['src/core/config/Config_default.h','src/backend/cpu/CpuConfig.cpp','src/crypto/rx/RxConfig.cpp',
       'src/base/net/stratum/Pool.cpp','src/base/net/stratum/Client.cpp','src/net/strategies/DonateStrategy.cpp',
       'src/base/net/http/HttpServer.cpp','src/core/config/Config.cpp','src/config.json']
for name in paths:
    try:
        raw=get('https://raw.githubusercontent.com/xmrig/xmrig/v6.26.0/'+name, 800000)
        path=out/Path(name).name;path.write_bytes(raw)
        print('SOURCE',name,len(raw))
    except Exception as e: print('SOURCE_ERROR',name,str(e))

html=get('https://unmineable.com/coins/USDT').decode()
(out/'coin-page.html').write_text(html,'utf-8')
scripts=re.findall(r'<script[^>]+src="([^"]+)"',html)
print('SCRIPTS',scripts)
for i,url in enumerate(scripts[:8]):
    if url.startswith('/'):url='https://unmineable.com'+url
    if not url.startswith(('https://unmineable.com/','https://www.unmineable.com/')):continue
    try:
        raw=get(url,8000000).decode()
        (out/f'pool-{i}.js').write_text(raw,'utf-8')
        for match in re.finditer(r'api\.unmin[ae]?able[^\s\x22\x27`<>]{0,180}|/v[134]/(?:address|stats|payments|coin)[^\s\x22\x27`<>]{0,100}',raw):
            print('POOL_API',match.group(0)[:200])
    except Exception as e:print('SCRIPT_ERROR',str(e))
print('DOWNLOAD_ONLY_COMPLETE')
