"""Owned, disposable QEMU guest. No shared host folders, clipboard or unrestricted guest egress."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

DRIVER='unmineable-usdt-bsc-vm-cpu'
LINUX_URL='https://github.com/xmrig/xmrig/releases/download/v6.26.0/xmrig-6.26.0-linux-static-x64.tar.gz'
LINUX_SHA='fc6f8ae5f64e4f17481f7e3be29a1c56949f216a998414188003eae1db20c9e5'
LINUX_EXE_SHA='b20f39fc00d242e706b6c30367ad811c676e0575050a4ec2f30104b696944b49'
BASE_SHA='406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0'


def vm_root(directory):return Path(directory)/'mining-vm'


def prepared(directory, require_boot=True):
    root=vm_root(directory)
    try:
        data=json.loads((root/'preparation.json').read_text('utf-8'))
        if data.get('owner')!='prospect-mining-vm-v1' or data.get('linux_miner_sha256')!=LINUX_SHA or data.get('base_sha256')!=BASE_SHA or data.get('linux_executable_sha256')!=LINUX_EXE_SHA:return False
        if require_boot:
            boot=json.loads((root/'boot-verification.json').read_text('utf-8'))
            if boot.get('verified') is not True or boot.get('network_probe_passed') is not True or not 0<=time.time()-boot.get('epoch',0)<=86400:return False
        return True
    except (OSError,ValueError,TypeError):return False


def build_spec(folder,inputs,log,cancelled,free_port,prepare_only=False):
    folder=folder.resolve()
    root=folder.parents[1]/'mining-vm'
    if not prepared(folder.parents[1],require_boot=not prepare_only):raise ValueError('独立虚拟机尚未完成基础准备与启动核验')
    data=json.loads((root/'preparation.json').read_text('utf-8'))
    binaries=root/'runtime/ucrt64/bin'
    qemu=binaries/'qemu-system-x86_64.exe';image_tool=binaries/'qemu-img.exe'
    pins={item['path']:item['sha256'] for item in data['runtime_files']}
    # Check every runtime file actually loaded from bin; foreign vendor files
    # cannot be selected by an HTTP caller or an untrusted project report.
    for path in binaries.iterdir():
        if path.is_file() and path.suffix.lower() in ('.exe','.dll'):
            relative='ucrt64/bin/'+path.name
            if relative not in pins or hashlib.sha256(path.read_bytes()).hexdigest()!=pins[relative]:raise ValueError('虚拟机运行文件校验失败')
        if cancelled.is_set():raise InterruptedError()
    image=root/'ubuntu-24.04-minimal-cloudimg-amd64.img'
    if hashlib.sha256(image.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('Ubuntu 基础镜像校验失败')
    if hashlib.sha256((root/'seed.iso').read_bytes()).hexdigest()!=data['seed_sha256']:raise ValueError('虚拟机初始化配置校验失败')
    archive=root/'xmrig-6.26.0-linux-static-x64.tar.gz'
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=LINUX_SHA:raise ValueError('Linux 矿工发布包校验失败')
    overlay=folder/'disk.qcow2'
    environment=os.environ.copy();environment['PATH']=str(binaries)+os.pathsep+str(Path(os.environ['SYSTEMROOT'])/'System32')
    result=subprocess.run([str(image_tool),'create','-f','qcow2','-F','qcow2','-b',str(image),str(overlay)],env=environment,
                          capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise ValueError('无法创建本次独立虚拟磁盘')
    ssh_port,api_port=free_port(),free_port()
    while ssh_port==api_port:api_port=free_port()
    log('基础镜像与 Linux 矿工校验完成；本次使用独立虚拟磁盘，不共享主机目录。')
    return {'driver':DRIVER,'prepare_only':prepare_only,'root':str(root),'folder':str(folder),'qemu':str(qemu),
            'qemu_sha256':pins['ucrt64/bin/qemu-system-x86_64.exe'],'ssh_port':ssh_port,'rpc_port':api_port,
            'api_token':secrets.token_hex(24),'inputs':inputs,'worker':'prospect'+folder.name[-10:],
            'qemu_argv':[str(qemu),'-accel','whpx','-machine','pc','-cpu','qemu64,+aes','-m','2816','-smp','2',
                         '-nodefaults','-display','none','-monitor','none','-serial','file:'+(folder/'serial.log').as_posix(),
                         '-L',str(root/'runtime/ucrt64/share/qemu'),'-drive','file='+overlay.as_posix()+',format=qcow2,if=virtio',
                         '-drive','file='+(root/'seed.iso').as_posix()+',media=cdrom,readonly=on',
                         '-netdev',f'user,id=n0,restrict=on,hostfwd=tcp:127.0.0.1:{ssh_port}-:22',
                         '-device','virtio-net-pci,netdev=n0','-rtc','base=utc,clock=host','-no-reboot']}


def run_worker(spec):
    """Called only after execution_worker is assigned to the Windows resource Job."""
    import select
    import socket
    import socketserver
    import threading
    from .mining import pool_socket
    root,folder=Path(spec['root']),Path(spec['folder'])
    qemu=tunnel=miner=server=None
    def stage(text):print('PROSPECT_VM_STAGE '+text,flush=True)
    ssh=Path(os.environ['SYSTEMROOT'])/'System32/OpenSSH/ssh.exe'
    scp=ssh.with_name('scp.exe')
    options=['-F','NUL','-i',str(root/'access/prospect_ed25519'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
             '-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+(folder/'known_hosts').as_posix(),
             '-o','GlobalKnownHostsFile=NUL','-o','ConnectionAttempts=1','-o','ConnectTimeout=2']
    base=[str(ssh),*options,'-T','-p',str(spec['ssh_port']),'prospect@127.0.0.1']
    def call(command,body=None,timeout=10):
        extra={'input':body} if body is not None else {'stdin':subprocess.DEVNULL}
        result=subprocess.run([*base,command],capture_output=True,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW,**extra)
        return result
    class Gateway(socketserver.BaseRequestHandler):
        def handle(self):
            upstream=None
            try:
                upstream=pool_socket(spec['inputs']['transport']);self.request.setblocking(False);upstream.setblocking(False)
                while True:
                    ready,_,_=select.select([self.request,upstream],[],[],1)
                    for source in ready:
                        data=source.recv(65536)
                        if not data:return
                        target=upstream if source is self.request else self.request
                        target.setblocking(True);target.sendall(data);target.setblocking(False)
            except OSError:pass
            finally:
                if upstream:upstream.close()
    class GatewayServer(socketserver.ThreadingTCPServer):daemon_threads=True;allow_reuse_address=False
    try:
        executable=Path(spec['qemu'])
        if hashlib.sha256(executable.read_bytes()).hexdigest()!=spec['qemu_sha256']:raise ValueError('虚拟机启动前校验失败')
        environment=os.environ.copy();environment['PATH']=str(executable.parent)+os.pathsep+environment.get('PATH','')
        stage('正在启动独立 Ubuntu 环境；尚未启动矿工')
        with (folder/'qemu.log').open('wb') as output:
            qemu=subprocess.Popen(spec['qemu_argv'],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                                  env=environment,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        deadline=time.monotonic()+180;last_notice=time.monotonic()
        while True:
            if qemu.poll() is not None:raise ValueError('虚拟机提前退出，退出码 '+str(qemu.returncode))
            if time.monotonic()>deadline:raise ValueError('虚拟机启动超过3分钟，已停止')
            try:
                result=call('id -un; uname -m',timeout=6)
                (folder/'ssh-last-error.txt').write_bytes(result.stderr[:8000])
                (folder/'ssh-last-output.txt').write_bytes(result.stdout[:8000])
                if result.returncode==0 and result.stdout.split()==[b'prospect',b'x86_64']:break
            except subprocess.TimeoutExpired:pass
            if time.monotonic()-last_notice>10:
                stage('独立环境正在启动，等待已配置的登录服务');last_notice=time.monotonic()
            time.sleep(1)
        stage('独立环境已就绪；登录账户与架构已核验')
        network_probe=b'import socket\ns=socket.socket();s.settimeout(1)\nassert s.connect_ex(("1.1.1.1",443)) != 0\nprint("egress-blocked")\n'
        result=call('python3 -',network_probe,timeout=5)
        if result.returncode or result.stdout.strip()!=b'egress-blocked':raise ValueError('独立环境的外部网络限制未通过实测')
        if spec.get('prepare_only'):
            (root/'boot-verification.json').write_text(json.dumps({'verified':True,'epoch':time.time(),'guest_arch':'x86_64',
                'mining_started':False,'shared_folders':False,'restricted_guest_network':True,'network_probe_passed':True}),'utf-8')
            return 0
        stage('正在将已校验的 Linux 矿工交给独立环境')
        copied=call('cat > /home/prospect/miner.tar.gz',(root/'xmrig-6.26.0-linux-static-x64.tar.gz').read_bytes(),timeout=30)
        if copied.returncode:raise ValueError('矿工文件传入独立环境失败')
        result=call('tar -xzf /home/prospect/miner.tar.gz -C /home/prospect && sha256sum /home/prospect/xmrig-6.26.0/xmrig')
        if result.returncode or not result.stdout.decode('utf-8','replace').startswith(LINUX_EXE_SHA+' '):raise ValueError('独立环境中的矿工哈希核验失败')
        server=GatewayServer(('127.0.0.1',0),Gateway)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        forward=[str(ssh),*options,'-N','-T','-p',str(spec['ssh_port']),'-o','ExitOnForwardFailure=yes',
                 '-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',
                 '-R',f'127.0.0.1:19999:127.0.0.1:{server.server_address[1]}',
                 '-L',f'127.0.0.1:{spec["rpc_port"]}:127.0.0.1:18080','prospect@127.0.0.1']
        tunnel=subprocess.Popen(forward,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        config={'autosave':False,'background':False,'colors':False,'title':False,'watch':False,
                'http':{'enabled':True,'host':'127.0.0.1','port':18080,'access-token':spec['api_token'],'restricted':True},
                'randomx':{'init':1,'mode':'fast','1gb-pages':False,'rdmsr':False,'wrmsr':False,'numa':False},
                'cpu':{'enabled':True,'huge-pages':False,'priority':0,'yield':True,'rx':[-1,-1]},
                'opencl':{'enabled':False},'cuda':{'enabled':False},'donate-level':1,'donate-over-proxy':0,
                'pools':[{'algo':'rx/0','url':'127.0.0.1:19999','user':'USDT:'+spec['inputs']['public_address']+'.'+spec['worker'],
                          'pass':'x','keepalive':True,'tls':True,'tls-fingerprint':spec['inputs']['transport']['certificate_sha256']}],
                'print-time':10,'health-print-time':30}
        result=call('cat > /home/prospect/miner.json',json.dumps(config).encode())
        if result.returncode:raise ValueError('独立环境的矿工配置未写入')
        stage('环境和矿工均已核验，正在启动矿工并连接矿池')
        miner=subprocess.Popen([*base,'exec /home/prospect/xmrig-6.26.0/xmrig --config=/home/prospect/miner.json'],
                               stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        while miner.poll() is None:
            if qemu.poll() is not None or tunnel.poll() is not None:raise ValueError('独立环境或矿池通道已断开')
            time.sleep(.25)
        return miner.returncode
    finally:
        for process in (miner,tunnel,qemu):
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        if server:server.shutdown();server.server_close()
