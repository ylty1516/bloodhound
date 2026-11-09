"""Prepare a separate, owned VM. Never read the other project's guest/wallet/key.

Only its unchanged public base image and hash-listed vendor runtime are reused.
This script does NOT start a VM or a miner.
"""
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prospect.service import data_directory
from prospect.mining import opener

existing=Path(r'F:\Codex_Save_Library\05_Project_Folders\opacra-sandbox-vm')
root=data_directory()/'mining-vm';root.mkdir(exist_ok=True)
runtime=root/'runtime';runtime.mkdir(exist_ok=True)
manifest=json.loads((existing/'runtime-files.json').read_text('utf-8'))
copied=[]
for item in manifest:
    relative=PurePosixPath(item['path'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid runtime path')
    source=existing/'runtime'/str(relative);target=runtime/str(relative)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=item['sha256']:raise ValueError('Existing vendor runtime has changed: '+str(relative))
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():shutil.copyfile(source,target)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Runtime copy failed')
    copied.append(item)
print('VENDOR_RUNTIME_VERIFIED',len(copied),flush=True)

image_name='ubuntu-24.04-minimal-cloudimg-amd64.img'
image_sha='406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0'
image_source='https://cloud-images.ubuntu.com/minimal/releases/noble/release-20261105/'
request=urllib.request.Request(image_source+'SHA256SUMS',headers={'User-Agent':'Prospect/0.1'})
with opener().open(request,timeout=20) as response:sums=response.read(150000).decode()
assert any(line.split()[0]==image_sha and line.split()[-1].lstrip('*')==image_name for line in sums.splitlines() if line.strip())
source=existing/'images'/image_name;image=root/image_name
assert hashlib.sha256(source.read_bytes()).hexdigest()==image_sha
if not image.exists():shutil.copyfile(source,image)
assert hashlib.sha256(image.read_bytes()).hexdigest()==image_sha
print('PUBLIC_BASE_IMAGE_VERIFIED',source.stat().st_size,flush=True)

wheel_url='https://files.pythonhosted.org/packages/7c/64/5a5912a3f3ba47dba3eb7f707e51f91926b26be4bde25fe2da483f3c4a9b/pycdlib-1.22.0-py3-none-any.whl'
wheel_sha='bfa0b3631345a14b2741fe088398b6b8dc2838442ea607fd07d027dcc67b9e94'
wheel=root/'pycdlib-1.22.0.whl'
if not wheel.exists():
    with opener().open(urllib.request.Request(wheel_url,headers={'User-Agent':'Prospect/0.1'}),timeout=20) as response:wheel.write_bytes(response.read(1000000))
assert hashlib.sha256(wheel.read_bytes()).hexdigest()==wheel_sha
deps=root/'python-deps';deps.mkdir(exist_ok=True)
with zipfile.ZipFile(wheel) as z:
    for info in z.infolist():
        path=PurePosixPath(info.filename)
        if path.is_absolute() or '..' in path.parts or info.file_size>2_000_000:raise ValueError('Unsafe dependency wheel')
        if info.is_dir():continue
        target=deps/str(path);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(info))
sys.path.insert(0,str(deps));import pycdlib

keys=root/'access';keys.mkdir(exist_ok=True)
key=keys/'prospect_ed25519'
ssh_root=Path(os.environ['SYSTEMROOT'])/'System32/OpenSSH'
if not key.exists():
    process=subprocess.run([str(ssh_root/'ssh-keygen.exe'),'-t','ed25519','-N','','-f',str(key),'-C','prospect-isolated-mining'],
                           stdin=subprocess.DEVNULL,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode:raise ValueError('Could not create the private, local VM access key')
pub=(key.with_suffix('.pub')).read_text('utf-8').strip()
user_data='#cloud-config\n'+json.dumps({'hostname':'prospect-mining','manage_etc_hosts':True,'ssh_pwauth':False,'disable_root':True,
    'users':[{'name':'prospect','shell':'/bin/bash','lock_passwd':True,'ssh_authorized_keys':[pub]}],
    'package_update':False,'package_upgrade':False,'growpart':{'mode':'auto','devices':['/']},'resize_rootfs':True})+'\n'
metadata='instance-id: prospect-owned-mining-20261108\nlocal-hostname: prospect-mining\n'
seed=root/'seed.iso'
iso=pycdlib.PyCdlib();iso.new(interchange_level=3,vol_ident='CIDATA',joliet=3,rock_ridge='1.09')
for iso_name,name,content in [('USERDATA.;1','user-data',user_data),('METADATA.;1','meta-data',metadata)]:
    raw=content.encode();iso.add_fp(io.BytesIO(raw),len(raw),iso_path='/'+iso_name,rr_name=name,joliet_path='/'+name)
iso.write(str(seed));iso.close()

linux_url='https://github.com/xmrig/xmrig/releases/download/v6.26.0/xmrig-6.26.0-linux-static-x64.tar.gz'
linux_sha='fc6f8ae5f64e4f17481f7e3be29a1c56949f216a998414188003eae1db20c9e5'
archive=root/'xmrig-6.26.0-linux-static-x64.tar.gz'
if not archive.exists():
    with opener().open(urllib.request.Request(linux_url,headers={'User-Agent':'Prospect/0.1'}),timeout=25) as response:archive.write_bytes(response.read(10_000_000))
assert hashlib.sha256(archive.read_bytes()).hexdigest()==linux_sha
with tarfile.open(archive,'r:gz') as tar:
    entries=[a for a in tar.getmembers() if a.isfile() and a.name.endswith('/xmrig')]
    assert len(entries)==1 and entries[0].size<15_000_000
    executable_sha=hashlib.sha256(tar.extractfile(entries[0]).read()).hexdigest()
manifest_out={'schema_version':1,'owner':'prospect-mining-vm-v1','base_image':str(image),'base_sha256':image_sha,'base_source':image_source,
              'runtime_files':copied,'linux_miner_url':linux_url,'linux_miner_sha256':linux_sha,'linux_executable_sha256':executable_sha,
              'seed_sha256':hashlib.sha256(seed.read_bytes()).hexdigest(),'seed_dependency_sha256':wheel_sha,
              'no_other_guest_or_keys_read':True,'mining_started':False}
(root/'preparation.json').write_text(json.dumps(manifest_out,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'prepared':True,'runtime_files':len(copied),'base_sha256':image_sha,'linux_archive_sha256':linux_sha,
                  'linux_executable_sha256':executable_sha,'seed_ready':seed.is_file(),'mining_started':False}),flush=True)
