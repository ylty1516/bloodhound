"""Read native CLI events while running; never retain raw transcripts or reasoning."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

STAGES = {
    "starting": "正在启动 Agent", "connected": "Agent 已启动，正在等待模型响应",
    "searching": "正在搜索公开资料", "reading": "正在读取资料",
    "comparing": "正在核对条件与证据", "writing": "正在整理检查报告",
    "retrying": "Agent 正在重试网络请求", "validating": "正在校验报告并保存方案",
}


def activity(host, event):
    """Map allowlisted metadata to fixed labels. No query, text, URL or thinking leaks."""
    kind = event.get("type")
    if host == "codex":
        if kind in ("thread.started", "turn.started"): return "connected"
        if kind=='error' and (event.get('will_retry') or any(word in str(event.get('message','')).lower() for word in ('reconnecting','retrying'))):return 'retrying'
        item = event.get("item") or {}
        if kind in ("item.started", "item.updated", "item.completed") and isinstance(item, dict):
            if item.get("type") == "web_search":
                action = item.get("action") or {}
                return "reading" if isinstance(action,dict) and action.get("type") in ("open_page", "find_in_page") else "searching"
            if item.get("type") == "agent_message": return "writing"
            if item.get("type") == "reasoning": return "comparing"
        if kind == "turn.completed": return "validating"
    else:
        if kind == "system":
            if event.get("subtype") == "init": return "connected"
            if event.get("subtype") == "api_retry": return "retrying"
        if kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content", []) if isinstance(message,dict) else []:
                if not isinstance(block,dict): continue
                if block.get("type") == "tool_use":
                    if block.get("name") == "WebSearch": return "searching"
                    if block.get("name") == "WebFetch": return "reading"
                if block.get("type") == "text": return "writing"
        if kind == "result": return "validating"
    return None


def native_error(event):
    """Read only error envelopes; transcripts and reasoning never become diagnostics."""
    if event.get('type') in ('error','turn.failed'):
        value=event.get('error') or event.get('message')
    elif isinstance(event.get('item'),dict) and event['item'].get('type')=='error':
        value=event['item'].get('message') or event['item'].get('text')
    else:return ''
    if isinstance(value,dict):value=json.dumps({k:value[k] for k in ('code','message') if k in value},ensure_ascii=False)
    return value[:2048] if isinstance(value,str) else ''


def consume(process, prompt, on_event, on_heartbeat, timeout):
    """Drain both pipes concurrently, bounded in memory, with independent liveness pulses."""
    events = queue.Queue(maxsize=128)
    stopped = threading.Event()
    diagnostics = []

    def send(value):
        while not stopped.is_set():
            try: events.put(value, timeout=.2); return
            except queue.Full: pass

    def read_stdout():
        try:
            while not stopped.is_set():
                line = process.stdout.readline(524289)
                if not line: break
                if len(line) > 524288:
                    while line and not line.endswith("\n"): line = process.stdout.readline(524289)
                    continue
                send(line)
        except (OSError, ValueError): pass
        finally: send(None)

    def read_stderr():
        try:
            while not stopped.is_set():
                part = process.stderr.read(2048)
                if not part: break
                diagnostics[:] = [("".join(diagnostics) + part)[-8192:]]
        except (OSError, ValueError): pass

    def write_prompt():
        try: process.stdin.write(prompt); process.stdin.close()
        except (OSError, ValueError): pass

    workers = [threading.Thread(target=fn, daemon=True) for fn in (read_stdout,read_stderr,write_prompt)]
    for worker in workers: worker.start()
    deadline, pulse, eof = time.monotonic()+timeout, 0, False
    try:
        while not eof or process.poll() is None:
            if time.monotonic() >= deadline: raise subprocess.TimeoutExpired(process.args, timeout)
            if time.monotonic() >= pulse:
                on_heartbeat(process.poll() is None); pulse=time.monotonic()+5
            try: line=events.get(timeout=.2)
            except queue.Empty: continue
            if line is None: eof=True; continue
            try: event=json.loads(line)
            except ValueError: continue
            if isinstance(event,dict): on_event(event)
        process.wait(timeout=max(.1,deadline-time.monotonic()))
    finally:
        stopped.set()
        if process.poll() is None: process.kill()
        for worker in workers: worker.join(timeout=1)
        for pipe in (process.stdin, process.stdout, process.stderr):
            try: pipe.close()
            except (OSError, ValueError): pass
    return "".join(diagnostics)
