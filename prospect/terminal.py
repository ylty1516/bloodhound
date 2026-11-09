"""Small keyboard dashboard; ANSI only when a real terminal supports it."""
from __future__ import annotations
import os
import shutil
import sys
import time
import unicodedata


def width(text):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 0 if unicodedata.combining(c) else 1 for c in str(text))


def fit(text, maximum):
    text = str(text).replace("\n", " ").replace("\r", " ")
    text = "".join(c for c in text if ord(c) >= 32 and ord(c) != 127)
    if width(text) <= maximum: return text + " " * (maximum - width(text))
    out = ""
    for c in text:
        if width(out + c) > maximum - 1: break
        out += c
    return out + "…" + " " * max(0, maximum - width(out) - 1)


def render(state, columns=100, color=False):
    columns = max(40, min(120, columns))
    teal, muted, reset = ("\x1b[36m", "\x1b[90m", "\x1b[0m") if color else ("", "", "")
    line = "─" * columns
    catalogue=state.get('lead_catalog',{})
    candidates = catalogue.get('items',state.get("candidates", []))
    usage, ob = state.get("usage", {}), state.get("observation", {})
    hw = state.get("hardware", {})
    text = [teal + fit("PROSPECT  /  项目观察台", columns) + reset,
            muted + fit("已公布挖掘消息 · 主网尚未开挖 · CPU 优先，GPU 其次", columns) + reset, line,
            fit(f"全部线索 {catalogue.get('total',len(candidates))}   后台模型调用 {usage.get('background_model_calls', '?')}   待研究 {usage.get('research_pending', '?')}", columns),
            fit(f"观察 {ob.get('status', 'not_started')}   {ob.get('elapsed_hours', 0):.1f} / 168 h   覆盖 {ob.get('coverage_pct', 0)}%", columns),
            fit(f"内存 {hw.get('ram_gb', '?')} GB   显存 {hw.get('vram_gb', '?')} GB   可用磁盘 {hw.get('disk_free_gb', '?')} GB", columns), line]
    todos=[x for x in state.get('launch_watch',{}).get('items',[]) if x.get('critical')]
    text.append(fit(f"★ 重点开挖待办 {len(todos)} · 原生钱包与币安兼容路线均关注",columns))
    for task in todos[:5]:
        text.append(fit(f"  {task['compute'].upper()} / {task['name']} / {task['starts_at'] or '时间待公布'}",columns))
    status_labels = {"unknown": "待核验", "listed": "已交易", "premarket": "盘前市场", "unissued": "未发行", "conflict": "证据冲突", "unlisted_supported": "范围内未开盘"}
    name_space = columns - 28
    text.append(fit("项目", name_space) + fit("发现阶段" if catalogue else "市场状态", 14) + fit("设备方向" if catalogue else "本机适配", 14))
    if not candidates: text.append(fit("暂无线索。按 s 扫描配置中的公开来源。", columns))
    for candidate in candidates[:8]:
        state_label = status_labels.get(candidate.get("classification"), "待核验")
        match = candidate.get('launch',{}).get('label') or {"unknown": "证据不足", "compatible": "条件符合", "incompatible": "不符合"}.get(candidate.get("assessment", {}).get("status"), "证据不足")
        if candidate.get('lead_info'):
            state_label=candidate['lead_info']['stage_label'];match=candidate.get('compute_profile',{}).get('label','设备待确认')
        text.append(fit(candidate.get("name", ""), name_space) + fit(state_label, 14) + fit(match, 14))
    if catalogue:text.append(fit('保留依据与完整分页：CLI工具 prospect_candidates；网页“全部线索”',columns))
    jobs=[j for j in state.get('executions',{}).get('jobs',[]) if j.get('driver',{}).get('id','').startswith('unmineable-usdt-bsc-')]
    if jobs:
        job=jobs[0];proof=job.get('miner_evidence') or {};delivery=job.get('delivery') or {}
        text += [line,fit('本轮真实挖矿 / '+job.get('message',''),columns),
                 fit(f"接受份额 {proof.get('accepted_shares',0)}   算力 {proof.get('hashrate_hs','—')} H/s",columns),
                 fit(f"矿池记账 {job.get('pool_credit_delta','待核对')} USDT / BSC   钱包{'已核验到账' if delivery.get('onchain_verified') else '尚未到账'}",columns)]
    text += [line, fit("r 刷新   s 核对项目   q 退出    网页 http://127.0.0.1:18766/", columns),
             muted + fit("退出面板不停止服务；停止请运行 python -m prospect stop", columns) + reset]
    return "\n".join(text)


def dashboard(read_state, scan, watch=False):
    interactive = sys.stdout.isatty() and sys.stdin.isatty()
    color = interactive and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    if os.name == "nt" and color:
        import ctypes
        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 4)
        else: color = False
    if not watch or not interactive:
        print(render(read_state(), shutil.get_terminal_size((100, 30)).columns, color))
        return
    try:
        while True:
            print("\x1b[2J\x1b[H" + render(read_state(), shutil.get_terminal_size((100, 30)).columns, color), end="", flush=True)
            until = time.monotonic() + 5
            while time.monotonic() < until:
                key = ""
                if os.name == "nt":
                    import msvcrt
                    if msvcrt.kbhit(): key = msvcrt.getwch().lower()
                else:
                    import select
                    if select.select([sys.stdin], [], [], 0)[0]: key = sys.stdin.readline().strip().lower()
                if key == "q": return
                if key == "s": scan(); break
                if key == "r": break
                time.sleep(0.1)
    except KeyboardInterrupt:
        return
    finally:
        print("\x1b[0m\n" if color else "\n", end="")
