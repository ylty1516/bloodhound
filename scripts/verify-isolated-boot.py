"""Bounded OS/SSH preflight only; never starts a miner or alters another VM."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prospect.service import data_directory
from prospect.vm_mining import build_spec
from prospect.execution_drivers import free_port,controller_env
from prospect.process_limits import Job

folder=data_directory()/'executions'/('vm_boot_'+dt.datetime.now().strftime('%Y%m%d%H%M%S'))
folder.mkdir(parents=True)
spec=build_spec(folder,{},print,threading.Event(),free_port,prepare_only=True)
group=Job(20,3072);process=None
try:
    process=subprocess.Popen([sys.executable,'-I','-X','utf8','-u',str(Path('prospect/execution_worker.py').resolve())],
        cwd=folder,env=controller_env(folder),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
    group.assign(process)
    process.stdin.write((json.dumps(spec)+'\n').encode());process.stdin.flush();process.stdin.close()
    started=time.monotonic()
    def read():
        for line in iter(process.stdout.readline,b''):
            print(line.decode('utf-8','replace').rstrip(),flush=True)
    reader=threading.Thread(target=read,daemon=True);reader.start()
    while process.poll() is None:
        if time.monotonic()-started>200:raise TimeoutError('OS boot preflight exceeded 200 seconds')
        time.sleep(.5)
    reader.join(2)
    print(json.dumps({'boot_exit_code':process.returncode,'elapsed_seconds':round(time.monotonic()-started,1),
                      'limits':group.limits(),'mining_started':False}))
    if process.returncode:raise SystemExit(1)
finally:
    group.terminate();group.close()
    if process:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        if process.stdout:process.stdout.close()
