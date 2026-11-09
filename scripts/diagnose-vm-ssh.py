"""Read-only probe of our own VM, comparing process environments; no miner."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prospect.service import data_directory
from prospect.execution_drivers import isolated_env
from prospect.process_limits import Job

root=data_directory().resolve()/'mining-vm'
deadline=time.monotonic()+120;args=None
while time.monotonic()<deadline:
    r=subprocess.run(['powershell.exe','-NoProfile','-Command',"Get-CimInstance Win32_Process -Filter \"Name='qemu-system-x86_64.exe'\" | Select-Object ExecutablePath,CommandLine | ConvertTo-Json -Compress"],capture_output=True,encoding='utf-8',errors='replace')
    items=json.loads(r.stdout or '[]');items=[items] if isinstance(items,dict) else items
    for item in items:
        if 'mining-vm' not in (item.get('ExecutablePath') or ''):continue
        match=re.search(r'hostfwd=tcp:127\.0\.0\.1:([0-9]+)-:22',item['CommandLine'])
        if not match:continue
        folder=max((data_directory()/'executions').glob('vm_boot_*'),key=lambda p:p.stat().st_mtime).resolve()
        args=[str(Path(os.environ['SYSTEMROOT'])/'System32/OpenSSH/ssh.exe'),'-F','NUL','-i',str(root/'access/prospect_ed25519'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+(folder/'known_hosts').as_posix(),'-o','GlobalKnownHostsFile=NUL','-o','ConnectTimeout=2','-T','-p',match.group(1),'prospect@127.0.0.1','id -un; uname -m']
        try:
            p=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=3)
            if p.returncode==0 and p.stdout.split()==[b'prospect',b'x86_64']:break
        except subprocess.TimeoutExpired:pass
    else:time.sleep(1);continue
    if args and p.returncode==0 and p.stdout.split()==[b'prospect',b'x86_64']:break
else:raise SystemExit('No responsive owned VM within 120s')
for isolated,hidden in [(False,False),(True,False),(False,True),(True,True)]:
    try:
        p=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=6,env=isolated_env(folder) if isolated else None,
                         creationflags=subprocess.CREATE_NO_WINDOW if hidden else 0)
        print(json.dumps({'isolated_env':isolated,'no_window':hidden,'rc':p.returncode,'stdout':repr(p.stdout),'stderr':p.stderr.decode('utf-8','replace')[:300]}),flush=True)
    except subprocess.TimeoutExpired:print(json.dumps({'isolated_env':isolated,'no_window':hidden,'timeout':True}),flush=True)
group=Job(20,3072)
try:
    p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    group.assign(p)
    out,err=p.communicate(timeout=8)
    print(json.dumps({'assigned_job':True,'rc':p.returncode,'stdout':repr(out),'stderr':err.decode('utf-8','replace')[:300]}),flush=True)
finally:group.terminate();group.close()
