"""Reviewed code owns commands. HTTP callers select a driver, never supply shell text."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import time
import urllib.request
import urllib.parse
import zipfile

from .sources import validate_public_url

SELF_CHECK = "local-self-check"
OPACRA = "opacra-testnet-node"
MINER = "opacra-testnet-cpu"
PACKAGE_URL = "https://github.com/opacra/opacra/releases/download/v1.0.0/opacra-v1.0.0-win-x64.zip"
PACKAGE_SHA = "5a7697cdb8f9084621b65b5b7d7c78c4e30e1f3cbebaa7954c93feb8369c09a9"
MAX_PACKAGE = 128 * 1024 * 1024


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        if urllib.parse.urlsplit(newurl).hostname not in {"github.com", "release-assets.githubusercontent.com"}:
            raise ValueError("发布包重定向离开已核验的 GitHub 下载域名")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def driver_info(driver):
    from .vm_mining import DRIVER as VM_DRIVER
    if driver==VM_DRIVER:return {'id':VM_DRIVER,'name':'隔离 CPU 挖矿 · USDT/BSC','network':'mainnet','version':'6.26.0','category':'pow'}
    from .mining import DRIVER
    if driver == DRIVER:
        return {"id": DRIVER,"name":"CPU 挖矿 · USDT/BSC","network":"mainnet","version":"6.26.0","category":"pow"}
    names = {SELF_CHECK: "本机执行器自检", OPACRA: "Opacra 测试网节点", MINER: "Opacra 测试网 CPU 挖矿"}
    if driver not in names: raise ValueError("没有这个项目的执行配方；不能把 Agent 文本直接当作命令运行。")
    return {"id": driver, "name": names[driver], "network": "local" if driver == SELF_CHECK else "testnet",
            "version": "1.0.0", "category": "diagnostic" if driver == SELF_CHECK else "pow" if driver == MINER else "node"}


def validate_inputs(driver, inputs):
    if not isinstance(inputs, dict): raise ValueError("运行参数必须是对象")
    if driver != MINER:
        if inputs: raise ValueError("此配方不接受额外命令或参数")
        return {}
    address = inputs.get("public_address", "")
    if set(inputs) != {"public_address"} or not isinstance(address, str) or not re.fullmatch(r"Te[1-9A-HJ-NP-Za-km-z]{93}", address):
        raise ValueError("只接受以 Te 开头的 95 字符测试网公开收款地址；不接受私钥、助记词或主网地址。")
    return {"public_address": address}


def prepare_package(folder, log, cancelled):
    """Fixed HTTPS origin and hash; bounded download, bounded ZIP, extract native files only."""
    validate_public_url(PACKAGE_URL)
    archive = folder / "release.zip"
    opener = urllib.request.build_opener(ArtifactRedirect())
    request = urllib.request.Request(PACKAGE_URL, headers={"User-Agent": "Prospect/1.0"})
    size, digest, started = 0, hashlib.sha256(), time.monotonic()
    last_progress = started
    with opener.open(request, timeout=10) as response, archive.open("wb") as target:
        while True:
            if cancelled.is_set(): raise InterruptedError("已取消下载")
            if time.monotonic() - started > 300: raise ValueError("下载超过 5 分钟，请稍后重试")
            chunk = response.read(128 * 1024)
            if not chunk: break
            size += len(chunk)
            if size > MAX_PACKAGE: raise ValueError("发布包超过 128 MB 限额")
            digest.update(chunk); target.write(chunk)
            if time.monotonic() - last_progress >= 2:
                log(f"正在下载发布包：已接收 {size // 1024} KB。")
                last_progress = time.monotonic()
    if digest.hexdigest() != PACKAGE_SHA: raise ValueError("发布包 SHA-256 不匹配，未执行文件")
    log(f"发布包校验通过：{size // 1024} KB，固定版本 1.0.0。")
    binaries = folder / "bin"; binaries.mkdir()
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) > 128 or sum(e.file_size for e in entries) > 512 * 1024 * 1024:
            raise ValueError("发布包展开后超过限制")
        names = set()
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("发布包包含不安全路径")
            name = path.name.lower()
            if entry.is_dir() or (name != "opacrad.exe" and not name.endswith(".dll")): continue
            if name in names: raise ValueError("发布包存在重复文件")
            names.add(name)
            with package.open(entry) as src, (binaries / name).open("xb") as dst:
                while chunk := src.read(128 * 1024):
                    if cancelled.is_set(): raise InterruptedError("已取消准备")
                    dst.write(chunk)
    executable = binaries / "opacrad.exe"
    if not executable.is_file(): raise ValueError("发布包没有 opacrad.exe；配方需要更新")
    return executable


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return sock.getsockname()[1]


def build_spec(driver, folder, inputs, log, cancelled, seconds=12):
    from .vm_mining import DRIVER as VM_DRIVER,build_spec as vm_spec
    if driver==VM_DRIVER:
        from .mining import pool_account,pool_transport
        account=pool_account(inputs['public_address'])
        if account['uuid']!=inputs['pool_uuid'] or pool_transport()!=inputs['transport']:raise ValueError('矿池收款或连接发生变化，请重新核对')
        spec=vm_spec(folder,inputs,log,cancelled,free_port)
        return spec|{'pool_before':account}
    from .mining import DRIVER,prepare_spec
    if driver == DRIVER:
        return prepare_spec(folder,inputs,log,cancelled,folder.parents[1]/'artifacts',free_port)
    if driver == SELF_CHECK: return {"driver": driver, "seconds": seconds}
    executable = prepare_package(folder, log, cancelled)
    rpc_port, p2p_port = free_port(), free_port()
    while rpc_port == p2p_port: p2p_port = free_port()
    argv = [str(executable), "--testnet", "--non-interactive", "--data-dir", str(folder / "chain"),
            "--log-file", str(folder / "node.log"), "--max-log-file-size", "1048576", "--max-log-files", "2",
            "--log-level", "0", "--rpc-bind-ip", "127.0.0.1", "--rpc-bind-port", str(rpc_port),
            "--restricted-rpc", "--no-zmq", "--p2p-bind-ip", "127.0.0.1", "--p2p-bind-port", str(p2p_port),
            "--no-igd", "--hide-my-port", "--out-peers", "4", "--in-peers", "0", "--max-concurrency", "1"]
    if driver == MINER: argv += ["--start-mining", inputs["public_address"], "--mining-threads", "1"]
    with executable.open("rb") as source: digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {"driver": driver, "argv": argv, "executable_sha256": digest, "rpc_port": rpc_port}


def probe(spec):
    """Node evidence only. A live process or synced node is never counted as paid mining."""
    if spec["driver"] == SELF_CHECK: return None
    from .mining import DRIVER,miner_probe
    from .vm_mining import DRIVER as VM_DRIVER
    if spec['driver'] in (DRIVER,VM_DRIVER):return miner_probe(spec)
    try:
        # Fixed loopback and read-only endpoint, no proxy and no arbitrary URL from callers.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{spec['rpc_port']}/get_info", timeout=0.6) as response:
            body = response.read(65537)
        if len(body) > 65536: return None
        data = json.loads(body)
        if data.get("nettype") != "testnet" or data.get("status") != "OK": return None
        return {"network": "testnet", "height": data.get("height"), "target_height": data.get("target_height"),
                "synchronized": data.get("synchronized") is True, "outgoing_connections": data.get("outgoing_connections_count")}
    except (OSError, ValueError): return None


def isolated_env(folder):
    # Do not pass API credentials, wallet settings or provider environment into a project.
    environment = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PROCESSOR_ARCHITECTURE"}}
    private_home = folder / "home"; private_home.mkdir(exist_ok=True)
    temporary = folder / "tmp"; temporary.mkdir(exist_ok=True)
    environment.update(HOME=str(private_home), USERPROFILE=str(private_home), APPDATA=str(private_home),
                       LOCALAPPDATA=str(private_home), TEMP=str(temporary), TMP=str(temporary), PYTHONIOENCODING="utf-8")
    environment["PATH"] = str(Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32")
    return environment


def controller_env(folder):
    """OS context for our trusted VM/SSH controller, not for guest project code.

    Windows OpenSSH silently returns255 when required account/profile variables
    are stripped. Keep only named OS fields; never inherit provider/wallet keys.
    Guest processes do not inherit this environment or share the host profile.
    """
    fields={'SYSTEMROOT','WINDIR','COMSPEC','PROCESSOR_ARCHITECTURE','SYSTEMDRIVE','USERNAME','USERDOMAIN',
            'USERDOMAIN_ROAMINGPROFILE','COMPUTERNAME','SESSIONNAME','OS','NUMBER_OF_PROCESSORS','PATHEXT',
            'USERPROFILE','APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH','PROGRAMDATA','ALLUSERSPROFILE',
            'PROGRAMFILES','PROGRAMFILES(X86)','COMMONPROGRAMFILES','COMMONPROGRAMFILES(X86)'}
    environment={k:v for k,v in os.environ.items() if k.upper() in fields}
    temp=folder/'tmp';temp.mkdir(exist_ok=True)
    environment.update(TEMP=str(temp),TMP=str(temp),PYTHONIOENCODING='utf-8')
    system=Path(os.environ.get('SYSTEMROOT','C:/Windows'))/'System32'
    environment['PATH']=str(system)+os.pathsep+str(system/'OpenSSH')
    return environment
