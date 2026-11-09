"""Recognize an Agent that actually started/used Prospect, without model calls.

Only process names, parent IDs and creation markers are read. A saved preference,
installed binary or the daemon's inherited environment is not a current host.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import threading
import time

HOST_LABELS = {'codex':'Codex','claude':'Claude Code','pi':'pi','deepseek':'DeepSeek Harness'}
NAMES = {'codex':'codex','claude':'claude','claude-code':'claude','pi':'pi','dsh':'deepseek','deepseek-harness':'deepseek'}


def _kernel():
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
    k.CloseHandle.argtypes=[W.HANDLE];k.CloseHandle.restype=W.BOOL
    return k


def process_started(pid):
    """Return a stable creation marker, so a reused PID cannot keep a host alive."""
    if type(pid) is not int or pid<=0:return None
    if os.name=='nt':
        k=_kernel();handle=k.OpenProcess(0x1000,False,pid)
        if not handle:return None
        try:
            values=[W.FILETIME() for _ in range(4)]
            k.GetProcessTimes.argtypes=[W.HANDLE]+[ctypes.POINTER(W.FILETIME)]*4;k.GetProcessTimes.restype=W.BOOL
            if not k.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):return None
            return str((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)
        finally:k.CloseHandle(handle)
    if Path('/proc').is_dir():
        try:
            raw=Path(f'/proc/{pid}/stat').read_text();fields=raw[raw.rindex(')')+2:].split()
            boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            return boot+':'+fields[19]
        except (OSError,ValueError,IndexError):return None
    return None


def process_tree():
    if os.name=='nt':
        class Entry(ctypes.Structure):
            _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',ctypes.c_size_t),('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('name',W.WCHAR*260)]
        k=_kernel();k.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD];k.CreateToolhelp32Snapshot.restype=W.HANDLE
        k.Process32FirstW.argtypes=k.Process32NextW.argtypes=[W.HANDLE,ctypes.POINTER(Entry)]
        k.Process32FirstW.restype=k.Process32NextW.restype=W.BOOL
        snapshot=k.CreateToolhelp32Snapshot(2,0)
        if snapshot==ctypes.c_void_p(-1).value:return {}
        result={};entry=Entry();entry.size=ctypes.sizeof(entry)
        try:
            valid=k.Process32FirstW(snapshot,ctypes.byref(entry))
            while valid:
                result[entry.pid]={'parent':entry.parent,'name':entry.name}
                valid=k.Process32NextW(snapshot,ctypes.byref(entry))
            return result
        finally:k.CloseHandle(snapshot)
    if Path('/proc').is_dir():
        result={}
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                raw=path.read_text();end=raw.rindex(')');fields=raw[end+2:].split()
                result[int(path.parent.name)]={'parent':int(fields[1]),'name':raw[raw.index('(')+1:end]}
            except (OSError,ValueError,IndexError):pass
        return result
    return {}


def caller_agent(expected=None):
    """Walk this actual invocation, never search all installed/running host apps."""
    if expected is not None and expected not in HOST_LABELS:return None
    if os.environ.get('PROSPECT_INTERNAL_CHECK')=='1':return None
    tree=process_tree();pid=os.getppid();seen=set()
    for _ in range(20):
        if pid in seen or pid not in tree:break
        seen.add(pid);item=tree[pid];name=item['name'].casefold().removesuffix('.exe')
        host=NAMES.get(name)
        # A generated adapter identifies node/bun-based hosts; a bare Node
        # process without that adapter declaration never proves a host.
        if not host and expected and name in ('node','bun','cordis'):host=expected
        if host:
            if expected and host!=expected:return None
            started=process_started(pid)
            return {'host':host,'pid':pid,'started':started} if started else None
        pid=item['parent']
    return None


class AgentContext:
    def __init__(self,store,probe=process_started,clock=time.time):
        self.store=store;self.probe=probe;self.clock=clock;self.lock=threading.RLock()

    def observe(self,value):
        if not isinstance(value,dict) or set(value)!={'host','pid','started','source'}:raise ValueError('Invalid Agent observation')
        if value['host'] not in HOST_LABELS or value['source'] not in ('startup','tool'):raise ValueError('Unknown Agent observation')
        if type(value['pid']) is not int or not isinstance(value['started'],str) or not 1<=len(value['started'])<=100:raise ValueError('Invalid Agent process')
        if self.probe(value['pid'])!=value['started']:raise ValueError('Agent 来源进程已退出，请重新连接')
        with self.lock:
            saved=self.store.get_setting('agent_context_observations',[])
            saved=[r for r in saved if not (r['host']==value['host'] and r['pid']==value['pid']) and self.probe(r['pid'])==r['started']]
            saved.append(value|{'observed_at':self.clock()})
            self.store.set_setting('agent_context_observations',saved[-32:])
            return self.view()

    def view(self):
        with self.lock:
            live=[r for r in self.store.get_setting('agent_context_observations',[]) if self.probe(r['pid'])==r['started']]
        live.sort(key=lambda r:r['observed_at'],reverse=True)
        hosts=list(dict.fromkeys(r['host'] for r in live))
        base={'mode':'recent_live_agent','running_hosts':[{'id':h,'label':HOST_LABELS[h]} for h in hosts]}
        if not live:return base|{'status':'unavailable','host':None,'label':None,'reason':'等待 Agent 启动或调用 Prospect 后自动识别'}
        if any(r['host']!=live[0]['host'] and r['observed_at']==live[0]['observed_at'] for r in live[1:]):
            return base|{'status':'ambiguous','host':None,'label':None,'reason':'多个 Agent 同时接入，等待下一次实际交互后自动选择'}
        latest=live[0]
        return base|{'status':'detected','host':latest['host'],'label':HOST_LABELS[latest['host']],'source':latest['source'],'observed_at':latest['observed_at'],'reason':'根据最近启动或调用 Prospect、且仍在运行的宿主识别'}

    def resolve(self):
        current=self.view()
        if current['status']!='detected':raise ValueError('尚未识别当前 Agent。请在正在使用的 Agent 中连接 Prospect，或展开其他检查方式。')
        return current['host']
