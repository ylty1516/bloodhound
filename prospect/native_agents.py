"""Resolve installed native agents without confusing an old CLI with the desktop.

Only local executable metadata and the user's existing proxy configuration are read.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.request

_lock=threading.Lock()
_cache={'until':0,'info':None}
_claude_cache={'until':0,'info':None}
_profiles={}


def _version(path):
    try:
        result=subprocess.run([str(path),'--version'],capture_output=True,text=True,encoding='utf-8',errors='replace',
            timeout=4,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        text=result.stdout.strip()[:120];match=re.search(r'(\d+)\.(\d+)\.(\d+)',text)
        return (tuple(map(int,match.groups())) if match else (0,0,0),text)
    except (OSError,ValueError,subprocess.SubprocessError):return (0,0,0),''


def _desktop_binary():
    if os.name!='nt':return None
    try:
        command='Get-AppxPackage -Name OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1 -ExpandProperty InstallLocation'
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,
            text=True,encoding='utf-8',errors='replace',timeout=7,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        location=result.stdout.strip()
        if not location or '\n' in location:return None
        candidate=Path(location)/'app/resources/codex.exe'
        return candidate if candidate.is_file() else None
    except (OSError,subprocess.SubprocessError):return None


def codex_info():
    # UI polling must not rerun PowerShell and version probes on every request.
    with _lock:
        cached=_cache['info']
        if time.monotonic()<_cache['until'] and (not cached or Path(cached['path']).is_file()):return cached
        candidates=[];desktop=_desktop_binary()
        if desktop:candidates.append((desktop,'desktop'))
        fixed=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/OpenAI/Codex/bin/codex.exe'
        if fixed.is_file():candidates.append((fixed,'standalone'))
        found=shutil.which('codex.exe') or shutil.which('codex')
        if found and Path(found).is_file():candidates.append((Path(found),'path'))
        known=set();versions=[]
        for path,source in candidates:
            key=str(path.resolve()).casefold()
            if key in known:continue
            known.add(key);version,text=_version(path)
            versions.append({'path':str(path),'source':source,'version':text,'version_tuple':version})
        info=max(versions,key=lambda value:value['version_tuple']) if versions else None
        _cache.update(until=time.monotonic()+300,info=info)
        return info


def find_native(host):
    if host=='codex':
        info=codex_info();return info['path'] if info else None
    if host=='claude':
        # Status polling only needs presence. Version/help probes run before generation.
        fixed=Path.home()/'.local/bin/claude.exe'
        return str(fixed) if fixed.is_file() else shutil.which('claude.exe') or shutil.which('claude')
    return None


def native_present(host):
    """Cheap presence for UI polling; never wait on version/help discovery."""
    if host not in ('codex','claude'):return False
    cached=(_cache if host=='codex' else _claude_cache)['info']
    if cached and Path(cached['path']).is_file():return True
    fixed=(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/OpenAI/Codex/bin/codex.exe'
           if host=='codex' else Path.home()/'.local/bin/claude.exe')
    if fixed.is_file() or shutil.which(host+'.exe') or shutil.which(host):return True
    if host=='codex' and os.name=='nt':
        try:
            packages=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'WindowsApps'
            return any(path.is_file() for path in packages.glob('OpenAI.Codex_*/app/resources/codex.exe'))
        except OSError:pass
    return False


def claude_info():
    with _lock:
        cached=_claude_cache['info']
        if time.monotonic()<_claude_cache['until'] and (not cached or Path(cached['path']).is_file()):return cached
        candidates=[(Path.home()/'.local/bin/claude.exe','standalone')]
        found=shutil.which('claude.exe') or shutil.which('claude')
        if found:candidates.append((Path(found),'path'))
        seen=set();versions=[]
        for path,source in candidates:
            if not path.is_file():continue
            key=str(path.resolve()).casefold()
            if key in seen:continue
            seen.add(key);version,text=_version(path)
            versions.append({'path':str(path),'source':source,'version':text,'version_tuple':version})
        info=max(versions,key=lambda value:value['version_tuple']) if versions else None
        _claude_cache.update(until=time.monotonic()+300,info=info)
        return info


def native_profile(host):
    info=codex_info() if host=='codex' else claude_info() if host=='claude' else None
    if not info:return None
    key=(host,info['path'],info['version'])
    with _lock:
        cached=_profiles.get(key)
        if cached and cached['until']>time.monotonic():return cached['value']
        required=('--output-schema','--output-last-message','--json','--sandbox','--ignore-user-config') if host=='codex' else (
            '--json-schema','--output-format','--tools','--allowedTools','--strict-mcp-config','--setting-sources','--disable-slash-commands','--no-session-persistence')
        supported=None
        try:
            args=[info['path'],*(['exec'] if host=='codex' else []),'--help']
            result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=5,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode==0:supported={flag:flag in result.stdout for flag in (*required,'--effort')}
        except (OSError,ValueError,subprocess.SubprocessError):pass
        value=info|{'flags':supported,'missing_flags':[flag for flag in required if supported is not None and not supported[flag]],
                    'capabilities_verified':supported is not None}
        _profiles[key]={'until':time.monotonic()+300,'value':value}
        return value


def agent_environment():
    environment=os.environ.copy()
    if os.name=='nt':
        for scheme,proxy in urllib.request.getproxies_registry().items():
            if scheme in ('http','https') and proxy and not environment.get(scheme.upper()+'_PROXY'):
                environment[scheme.upper()+'_PROXY']=proxy
    environment['PROSPECT_INTERNAL_CHECK']='1'
    # Native CLIs keep their existing interactive login; no API credential is injected.
    for key in ('OPENAI_API_KEY','CODEX_API_KEY','ANTHROPIC_API_KEY'):
        environment.pop(key,None)
    return environment
