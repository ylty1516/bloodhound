"""Durable, explicitly started, bounded local executions; independent of model checks."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .domain import now
from .store import _json
from .process_limits import Job, idle_seconds
from .execution_drivers import SELF_CHECK, OPACRA, MINER, PACKAGE_SHA, PACKAGE_URL, driver_info, validate_inputs, build_spec, probe, isolated_env,controller_env
from .mining import Mining,DRIVER as ECONOMIC_MINER
from .vm_mining import DRIVER as VM_MINER
ECONOMIC_DRIVERS={ECONOMIC_MINER,VM_MINER}

ACTIVE = {"queued", "waiting_idle", "preparing", "running", "stopping", "verifying"}
ROOT = Path(__file__).resolve().parent


def clean_log(value):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
    text = "".join(c for c in text if c in "\t" or ord(c) >= 32)
    if re.search(r"private.?key|secret|mnemonic|seed.?phrase|password|api.?key|authorization|bearer|助记词|私钥", text, re.I):
        return "[已隐藏可能包含凭据的日志行]"
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|[a-fA-F0-9]{64})\b", "[已隐藏长凭据]", text)
    return text[:1600]


class Executions:
    def __init__(self, store, workflows, directory):
        self.store, self.workflows = store, workflows
        self.directory = Path(directory) / "executions"
        self.lock = threading.RLock()
        self.mining = Mining(store,directory)
        self.workers = {}; self.closing = False
        self.income_workers={}
        with store._connection(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS execution_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS execution_quotes (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS execution_logs (sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, at TEXT NOT NULL, line TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS execution_logs_by_run ON execution_logs(run_id,sequence);
            """)

    def recover(self):
        for job in self.runs():
            if (job.get('driver') or {}).get('id') in ECONOMIC_DRIVERS and job['status']=='completed' and not job.get('contribution_verified') and not (job.get('miner_evidence') or {}).get('accepted_shares'):
                self._patch(job['id'],status='failed',previous_status='completed',message='进程曾正常退出，但没有矿池接受份额；本轮未完成挖矿')
                self._receipt(job['id'])
            if job["status"] in ACTIVE:
                self._patch(job["id"], status="interrupted", finished_at=now(), message="服务曾中断；系统关闭原进程组。复核后可重新创建试运行。")
                self._receipt(job["id"])

    def runs(self):
        with self.store._connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM execution_runs ORDER BY rowid DESC LIMIT 100")]

    def get(self, ident):
        with self.store._connection() as db:
            row = db.execute("SELECT payload FROM execution_runs WHERE id=?", (ident,)).fetchone()
        if not row: raise ValueError("运行任务不存在")
        return json.loads(row[0])

    def _patch(self, ident, **fields):
        with self.lock, self.store._connection(write=True) as db:
            row = db.execute("SELECT payload FROM execution_runs WHERE id=?", (ident,)).fetchone()
            job = json.loads(row[0]); job.update(fields, updated_at=now())
            db.execute("UPDATE execution_runs SET payload=? WHERE id=?", (_json(job), ident))
        return job

    def log(self, ident, line):
        with self.store._connection(write=True) as db:
            db.execute("INSERT INTO execution_logs(run_id,at,line) VALUES(?,?,?)", (ident, now(), clean_log(line)))
            db.execute("DELETE FROM execution_logs WHERE run_id=? AND sequence NOT IN (SELECT sequence FROM execution_logs WHERE run_id=? ORDER BY sequence DESC LIMIT 600)", (ident, ident))

    def logs(self, ident, after=0):
        self.get(ident)
        if type(after) is not int or after < 0: raise ValueError("日志游标无效")
        with self.store._connection() as db:
            rows = db.execute("SELECT sequence,at,line FROM execution_logs WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 200", (ident, after)).fetchall()
            first = db.execute("SELECT MIN(sequence) FROM execution_logs WHERE run_id=?", (ident,)).fetchone()[0]
        return {"lines": [dict(r) for r in rows], "cursor": rows[-1][0] if rows else after,
                "truncated": bool(after and first and first > after + 1)}

    def state(self):
        return {"implemented": True, "platform_supported": os.name == "nt", "server_at": now(), "jobs": self.runs(),
                "drivers": [driver_info(d) for d in (VM_MINER, SELF_CHECK)],
                "limits": {"concurrency": 1, "daily_schedule": False, "sandbox": False}}

    def readiness(self,plan):
        blocks=[]
        def block(code,text,owner):blocks.append({'code':code,'text':text,'owner':owner})
        if os.name!='nt':block('platform','当前执行器需要 Windows','software')
        recipe=plan.get('recipe') or {};artifact=recipe.get('artifact') or {}
        audit=(plan.get('recommendation') or {}).get('audit') or {}
        if recipe.get('id')!='opacra-testnet' or artifact.get('sha256')!=PACKAGE_SHA or artifact.get('url')!=PACKAGE_URL:
            block('executor','这个项目尚无已接入的执行配方。目前支持 Opacra 测试网节点与单线程 CPU 路线。','software')
        if plan.get('recommendation',{}).get('status')!='suggested_trial':
            block('safety','先完成此项目的安全检查；硬件评分不作为尝试门槛。','agent')
        if audit.get('version','').lstrip('v')!='1.0.0' or audit.get('artifact_sha256')!=PACKAGE_SHA:
            block('program_version','安全检查尚未绑定这个 1.0.0 发布包的 SHA-256，不能用官网检查代替程序检查。','agent')
        if audit.get('method','source_review')!='source_review':
            block('audit_scope','网页入口检查不包含下载程序的安全范围。','agent')
        return {'can_configure':not blocks,'blockers':blocks}

    def _material(self, driver, plan_id, options, inputs):
        if driver in ECONOMIC_DRIVERS:
            if not isinstance(inputs,dict) or set(inputs)-{'public_address','pool_uuid','auto_payout','transport'}:
                raise ValueError('此路线自动读取币安钱包，不接受自定义地址或矿工命令')
            automatic=inputs.get('auto_payout',True)
            if type(automatic) is not bool:raise ValueError('自动结算选项无效')
            material=self.mining.material(automatic,isolated=driver==VM_MINER)
            for key in ('public_address','pool_uuid','transport'):
                if key in inputs and inputs[key]!=material['inputs'][key]:raise ValueError('钱包或矿池配置发生变化，请重新准备')
            if not isinstance(options,dict) or set(options)-{'duration_seconds','cpu_percent','memory_mb','idle_only'}:raise ValueError('资源选项无效')
            limits={'duration_seconds':900,'cpu_percent':20,'memory_mb':3072,'idle_only':False}|options
            if driver==VM_MINER and limits['memory_mb']!=3072:raise ValueError('当前隔离路线使用固定3GB进程组内存上限')
            for key,low,high in (('duration_seconds',30,900),('cpu_percent',5,25),('memory_mb',2560,4096)):
                if type(limits[key]) is not int or not low<=limits[key]<=high:raise ValueError(f'{key} 必须在 {low}–{high} 之间')
            if type(limits['idle_only']) is not bool:raise ValueError('空闲策略必须为布尔值')
            if os.name!='nt':material['blockers'].append('当前真实挖矿执行器需要 Windows')
            return material|{'limits':limits}
        info = driver_info(driver); inputs = validate_inputs(driver, inputs)
        if not isinstance(options, dict) or set(options) - {"duration_seconds", "cpu_percent", "memory_mb", "idle_only"}:
            raise ValueError("不支持这些资源选项")
        diagnostic = driver == SELF_CHECK
        defaults = {"duration_seconds": 20 if diagnostic else 60, "cpu_percent": 10 if diagnostic else 20,
                    "memory_mb": 256 if diagnostic else 2048, "idle_only": not diagnostic}
        limits = defaults | options
        for key, low, high in (("duration_seconds", 5, 900), ("cpu_percent", 1, 25), ("memory_mb", 128, 4096)):
            if type(limits[key]) is not int or not low <= limits[key] <= high: raise ValueError(f"{key} 必须在 {low}–{high} 之间")
        if type(limits["idle_only"]) is not bool: raise ValueError("空闲策略必须为布尔值")
        blockers, binding, notes = [], None, []
        if os.name != "nt": blockers.append("当前执行器需要 Windows")
        if not diagnostic:
            plan = next((p for p in self.workflows.plans() if p["id"] == plan_id), None)
            if not plan: raise ValueError("请先选择项目的准备方案")
            blockers.extend(item['text'] for item in self.readiness(plan)['blockers'] if item['code']!='platform')
            binding = {"plan_id": plan_id, "fingerprint": plan["fingerprint"], "candidate_id": plan["candidate_id"], "candidate_name": plan["candidate_name"]}
            notes = (plan.get("recommendation") or {}).get("notes", [])
        return {"driver": info, "binding": binding, "limits": limits, "inputs": inputs, "blockers": blockers,
                "notes": notes, "artifact": None if diagnostic else {"url": PACKAGE_URL, "sha256": PACKAGE_SHA},
                "scope": "本机自检，约 12 秒，无项目网络、钱包或奖励" if diagnostic else "仅测试网；下载已固定的发布包，独立目录，单次限时运行。不会创建钱包、签名、支付或切换主网。",
                "containment": "CPU 与进程组内存由 Windows 限制；工作目录每秒检查容量。不是安全沙箱，也不控制 GPU、网络流量或温度。"}

    def preview(self, driver=SELF_CHECK, plan_id=None, options=None, inputs=None):
        material = self._material(driver, plan_id, options or {}, inputs or {})
        quote = material | {"id": "quote_" + uuid.uuid4().hex, "created_at": now(), "expires_at": time.time() + 600,
                            "ready": not material["blockers"], "started": False}
        with self.store._connection(write=True) as db:
            db.execute("INSERT INTO execution_quotes VALUES(?,?)", (quote["id"], _json(quote)))
            db.execute("DELETE FROM execution_quotes WHERE id NOT IN (SELECT id FROM execution_quotes ORDER BY rowid DESC LIMIT 100)")
        return quote

    def start(self, quote_id, key, confirmed=False):
        if confirmed is not True: raise ValueError("请审阅运行范围，再点击确认启动")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key): raise ValueError("缺少有效的幂等键")
        ident = "exec_" + hashlib.sha256(str(quote_id).encode()).hexdigest()[:24]
        with self.lock:
            if self.closing: raise ValueError("服务正在停止")
            existing = next((j for j in self.runs() if j["id"] == ident), None)
            if existing: return existing | {"reused": True}
            with self.store._connection() as db:
                row = db.execute("SELECT payload FROM execution_quotes WHERE id=?", (quote_id,)).fetchone()
            if not row: raise ValueError("运行方案不存在，请重新查看运行范围")
            quote = json.loads(row[0])
            if time.time() > quote["expires_at"]: raise ValueError("运行方案已过期，请重新查看")
            fresh = self._material(quote["driver"]["id"], (quote["binding"] or {}).get("plan_id"), quote["limits"], quote["inputs"])
            if fresh["blockers"]: raise ValueError("；".join(fresh["blockers"]))
            if fresh != {k: quote[k] for k in fresh}: raise ValueError("项目或运行范围已变化，请重新审阅")
            if any(j["status"] in ACTIVE for j in self.runs()): raise ValueError("已有任务在运行，请先停止或等待完成")
            job = {"id": ident, "quote_id": quote_id, "key": key, "status": "queued", "stage": "queued", "message": "已接受，等待执行器启动",
                   "created_at": now(), "updated_at": now(), "heartbeat_at": now(), "driver": quote["driver"], "binding": quote["binding"],
                   "limits": quote["limits"], "scope": quote["scope"], "artifact": quote["artifact"], "inputs": quote["inputs"],
                   "mode": "diagnostic" if quote["driver"]["id"] == SELF_CHECK else "live", "authorization": {"confirmed_at": now(), "scope": "one_run"},
                   "contribution_verified": False, "rewards_verified": False, "elapsed_seconds": 0}
            with self.store._connection(write=True) as db:
                db.execute("INSERT INTO execution_runs VALUES(?,?)", (ident, _json(job)))
            cancelled = threading.Event()
            thread = threading.Thread(target=self._run, args=(ident, cancelled), daemon=True)
            self.workers[ident] = (thread, cancelled)
            thread.start()
            return job

    def cancel(self, ident):
        with self.lock:
            job = self.get(ident)
            if job["status"] not in ACTIVE: return job
            worker = self.workers.get(ident)
            if worker: worker[1].set()
            return self._patch(ident, status="stopping", message="正在停止整个进程组并保存回执")

    def reconcile(self, ident):
        job=self.get(ident)
        if job['driver']['id'] not in ECONOMIC_DRIVERS or not job.get('pool_before'):raise ValueError('这项运行尚无矿池收款记录')
        with self.lock:
            if ident in self.income_workers:return {'status':'checking','id':ident}
            if self.closing:raise ValueError('服务正在停止')
            def work():
                try:
                    fields=self.mining.reconcile(self.get(ident));fields['pool_verification_error']=None
                    self._patch(ident,**fields)
                    if self.get(ident)['status'] not in ACTIVE:self._receipt(ident)
                except Exception as exc:self._patch(ident,pool_verification_error=clean_log(exc))
                finally:
                    with self.lock:self.income_workers.pop(ident,None)
            thread=threading.Thread(target=work,daemon=True);self.income_workers[ident]=thread;thread.start()
        return {'status':'checking','id':ident}

    def _receipt(self, ident):
        job = self.get(ident)
        receipt = {k: v for k, v in job.items() if k != "receipt"}
        receipt["receipt_version"] = 1
        folder = self.directory / ident; folder.mkdir(parents=True, exist_ok=True)
        path = folder / "receipt.json"
        payload = _json(receipt).encode("utf-8"); path.write_bytes(payload)
        self._patch(ident, receipt={"sha256": hashlib.sha256(payload).hexdigest(), "available": True})

    def receipt(self, ident):
        job = self.get(ident)
        if not job.get("receipt"): raise ValueError("任务结束后才会生成回执")
        # Path is based on the DB id, never on an HTTP-supplied filesystem path.
        return json.loads((self.directory / job["id"] / "receipt.json").read_text("utf-8"))

    def _run(self, ident, cancelled):
        process = group = reader = None
        final_status, message, exit_code = "failed", "任务未完成", None
        job = self.get(ident); folder = self.directory / ident
        folder.mkdir(parents=True, exist_ok=True)
        started = time.monotonic(); spec = None
        try:
            if job["limits"]["idle_only"]:
                while idle_seconds() < 120:
                    self._patch(ident, status="waiting_idle", stage="waiting_idle", heartbeat_at=now(), message="等待电脑空闲满 2 分钟；可停止后重新选择运行策略")
                    if cancelled.wait(1): raise InterruptedError()
                    if time.monotonic() - started > 600: raise ValueError("等待空闲超过 10 分钟，未启动项目")
            if cancelled.is_set(): raise InterruptedError()
            self._patch(ident, status="preparing", stage="prepare", message="准备固定版本文件并验证校验值", heartbeat_at=now())
            self.log(ident, "开始准备，本次范围：" + job["scope"])
            if job["mode"] == "live" and shutil.disk_usage(folder).free < 5 * 1024 ** 3:
                raise ValueError("工作目录剩余空间不足 5 GB，无法安全保存本次文件")
            def progress(line):
                self.log(ident, line)
                self._patch(ident, heartbeat_at=now(), message=clean_log(line))
            spec = build_spec(job["driver"]["id"], folder, job["inputs"], progress, cancelled)
            if cancelled.is_set(): raise InterruptedError()
            # Recheck evidence after a possibly slow download, before any project process starts.
            fresh = self._material(job["driver"]["id"], (job["binding"] or {}).get("plan_id"), job["limits"], job["inputs"])
            if fresh["blockers"] or fresh["binding"] != job["binding"]: raise ValueError("准备期间检查资料已变化，请重新审阅运行方案")
            if job['driver']['id'] in ECONOMIC_DRIVERS:
                if job['inputs']['auto_payout']:
                    self.mining.enable_payout(job['inputs']['public_address'],job['inputs']['pool_uuid'])
                    self.log(ident,'矿池已确认自动结算；达到门槛后支付到本次核对的币安 BSC 地址。')
                self._patch(ident,pool_before=spec['pool_before'],worker=spec['worker'],
                            payment_baseline=[str(p.get('id')) for p in self.mining.payments(job['inputs']['pool_uuid'])],
                            delivery={'status':'awaiting_contribution','threshold':spec['pool_before']['threshold'],'unit':'USDT','network':'BSC'})
            group = Job(job["limits"]["cpu_percent"], job["limits"]["memory_mb"])
            process = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-u", str(ROOT / "execution_worker.py")],
                cwd=folder, env=controller_env(folder) if job['driver']['id']==VM_MINER else isolated_env(folder), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
            # Worker blocks on stdin; failure to assign means it never launches the project.
            group.assign(process)
            limits_applied = group.limits()
            if cancelled.is_set(): raise InterruptedError()
            process.stdin.write((_json(spec) + "\n").encode()); process.stdin.flush(); process.stdin.close()
            self._patch(ident, status="running", stage="run", message="进程正在运行", pid=process.pid, started_at=now(), limits_applied=limits_applied, heartbeat_at=now())
            self.log(ident, "CPU、内存和进程组退出保护已生效，进程已启动。")
            reader = threading.Thread(target=self._read_output, args=(ident, process.stdout), daemon=True); reader.start()
            run_start = time.monotonic(); last_probe = 0;last_income=0
            while process.poll() is None:
                elapsed = time.monotonic() - run_start
                if cancelled.is_set(): raise InterruptedError()
                if elapsed >= job["limits"]["duration_seconds"]:
                    final_status, message = "timed_out", "已达到本次时长上限，进程组已停止"; break
                if job["limits"]["idle_only"] and idle_seconds() < 2:
                    final_status, message = "paused", "检测到你开始使用电脑，已停止进程组；不会自行恢复"; break
                # Soft directory quota: sample allocated file sizes every second, not a filesystem sandbox.
                disk_bytes = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
                if disk_bytes > 1024 ** 3: raise ValueError("本次目录超过 1 GB 限额，已停止")
                fields = {"heartbeat_at": now(), "elapsed_seconds": round(elapsed, 1)}
                if elapsed - last_probe >= 5:
                    evidence = probe(spec); last_probe = elapsed
                    if evidence:
                        if job['driver']['id'] in ECONOMIC_DRIVERS:
                            fields['miner_evidence']=evidence
                            if evidence.get('accepted_shares',0)>0:
                                fields['contribution_verified']=True
                                fields['message']=f"矿池已接受 {evidence['accepted_shares']} 个真实份额；正在累计收益"
                        else:fields["node_evidence"] = evidence
                self._patch(ident, **fields)
                if job['driver']['id'] in ECONOMIC_DRIVERS and elapsed-last_income>=60:
                    self.reconcile(ident);last_income=elapsed
                cancelled.wait(0.5)
            else:
                exit_code = process.returncode
                final_status = "completed" if exit_code == 0 else "failed"
                message = "进程已正常结束" if exit_code == 0 else f"进程退出，退出码 {exit_code}；请查看日志"
                if job['driver']['id'] in ECONOMIC_DRIVERS and not self.get(ident).get('contribution_verified'):
                    final_status='failed';message='矿工提前结束，尚未取得矿池接受份额；本轮未完成挖矿'
            if job["mode"] == "diagnostic" and final_status == "completed":
                self._patch(ident, stage="verify", status="verifying", message="正在核验自检结果")
                result = json.loads((folder / "self-check.json").read_text("utf-8"))
                if result != {"kind": SELF_CHECK, "verified": True, "steps": 4, "rewards": None}: raise ValueError("自检结果不完整")
                self._patch(ident, diagnostic_verified=True)
                message = "本机自检通过：进程、日志、停止保护与结果交付可用"
        except InterruptedError:
            final_status, message = "cancelled", "已按请求停止，进程组已清理"
        except Exception as exc:
            final_status, message = "failed", clean_log(str(exc)) or type(exc).__name__
        finally:
            if spec and job['driver']['id'] in ECONOMIC_DRIVERS:
                evidence=probe(spec)
                if evidence:self._patch(ident,miner_evidence=evidence,contribution_verified=evidence.get('accepted_shares',0)>0)
            if group:
                try:
                    self._patch(ident, limits_applied=group.limits())
                except OSError: pass
                group.terminate(); group.close()
            if process:
                if process.poll() is None: process.kill()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: pass
                if reader: reader.join(3)
                if process.stdout: process.stdout.close()
                if process.stdin and not process.stdin.closed: process.stdin.close()
            if spec and job['driver']['id'] in ECONOMIC_DRIVERS:
                self._patch(ident,stage='verify',status='verifying',message='算力进程已停止，正在核对矿池记账')
                try:
                    fields=self.mining.reconcile(self.get(ident))
                    self._patch(ident,**fields)
                    verified=self.get(ident).get('contribution_verified',False)
                    if final_status=='timed_out' and verified:
                        final_status='completed';message='本次真实挖矿已完成，矿池接受份额已核验；钱包付款需等待达到门槛'
                    elif final_status=='timed_out':message='已按时停止；本次尚未取得矿池接受份额，不能算挖矿成功'
                except Exception as exc:self._patch(ident,pool_verification_error=clean_log(exc))
            self.log(ident, message)
            self._patch(ident, status=final_status, stage="finished", message=message, finished_at=now(), heartbeat_at=now(), exit_code=exit_code)
            self._receipt(ident)
            with self.lock: self.workers.pop(ident, None)

    def _read_output(self, ident, pipe):
        kept, dropped = 0, False
        try:
            while raw := pipe.readline(4096):
                # Bound disk writes even for a noisy/malicious process, but keep draining the pipe.
                if kept < 500:
                    line=raw.decode("utf-8", "replace").rstrip()
                    self.log(ident,line); kept += 1
                    if line.startswith('PROSPECT_VM_STAGE ') and self.get(ident)['driver']['id']==VM_MINER:
                        text=line.removeprefix('PROSPECT_VM_STAGE ')
                        starting='正在启动矿工' in text
                        self._patch(ident,stage='run' if starting else 'prepare',status='running' if starting else 'preparing',message=clean_log(text),heartbeat_at=now())
                elif not dropped:
                    self.log(ident, "日志达到本次保留上限；后续输出已省略，任务状态仍会更新。"); dropped = True
        except (OSError, ValueError): pass

    def shutdown(self):
        self.mining.shutdown()
        with self.lock:
            self.closing = True
            workers = list(self.workers.values())
            for _, cancelled in workers: cancelled.set()
        for thread, _ in workers: thread.join(15)
        for thread in list(self.income_workers.values()):thread.join(2)
