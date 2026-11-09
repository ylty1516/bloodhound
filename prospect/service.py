"""Local control service, authenticated API and durable read-only observation."""
from __future__ import annotations
import datetime as dt
import hmac
import json
import math
import os
import secrets
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .domain import assess, simulate
from .hardware import inventory
from .sources import defaults, import_legacy, now, scan
from .store import Store
from .agent_checks import AgentChecks
from .agent_context import AgentContext
from .workflows import Workflows
from .executions import Executions
from .budgets import validate_policy
from .project_view import compute_profile,launch_summary
from .launch_watch import LaunchWatch,POLICY as LAUNCH_POLICY
from .leads import LeadCatalog

ROOT = Path(__file__).resolve().parents[1]
LEGACY_DB = ROOT.parent / "data" / "radar.sqlite3"


def data_directory():
    if os.environ.get('PROSPECT_DATA'):return Path(os.environ['PROSPECT_DATA'])
    # One physical location across packaged Codex and ordinary CLI hosts.
    # The pointer contains a directory reference only, never credentials.
    pointer=ROOT/'runtime-location.json'
    if pointer.is_file():
        try:
            reference=json.loads(pointer.read_text('utf-8'));candidate=Path(reference.get('data_directory',''))
            if reference.get('schema_version')==1 and candidate.is_absolute() and candidate.is_dir():return candidate.resolve()
        except (OSError,ValueError,TypeError):pass
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'Prospect'


def write_private(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try: os.chmod(tmp, 0o600)
    except OSError: pass
    os.replace(tmp, path)


class Runtime:
    def __init__(self, directory: Path, port: int):
        self.directory, self.port = directory, port
        self.store = Store(directory / "prospect.sqlite3")
        self.agent_checks = AgentChecks(self.store, directory)
        self.agent_context = AgentContext(self.store)
        self.agent_checks.recover()
        self.workflows = Workflows(self.store, self.agent_checks)
        self.executions = Executions(self.store, self.workflows, directory)
        self.executions.recover()
        self.token = secrets.token_urlsafe(32)
        self.started_at = now()
        self.scan_lock = threading.Lock()
        self.scan_request_lock = threading.Lock()
        self.scan_thread = None
        self.scan_status = {'status':'idle'}
        self.proposal_lock = threading.RLock()
        self.control_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.session_lock = threading.Lock()
        self.sessions = {}
        self.server = None
        if self.store.get_setting("sources") is None:
            self.store.set_setting("sources", defaults())
        elif self.store.get_setting("observation", {}).get("status", "not_started") == "not_started":
            configured = self.store.get_setting("sources")
            known = {s["id"] for s in configured}
            added = [s for s in defaults() if s["id"] not in known]
            if added: self.store.set_setting("sources", configured + added)
        self.launch_watch=LaunchWatch(self.store)
        self.launch_watch.migrate()
        self.leads=LeadCatalog(self.store)
        self.leads.initialize()

    def refresh_hardware(self):
        self.store.save_hardware(inventory(ROOT))
        self.refresh_participation()

    def observation(self):
        ob = self.store.get_setting("observation", {"status": "not_started", "target_hours": 168, "cycles": 0, "successes": 0})
        elapsed = 0
        if ob.get("start_at"):
            elapsed = max(0, (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ob["start_at"])).total_seconds())
        expected = sum(math.floor(elapsed / period) + 1 for period in ob.get("source_intervals", []))
        ob = ob | {"elapsed_hours": round(elapsed / 3600, 3), "expected_checks": expected,
                   "coverage_pct": round(min(100, ob.get("successes", 0) / expected * 100), 2) if expected else 0}
        # Time alone never establishes data quality. An explicit review is still required.
        ob["ready_for_review"] = elapsed >= 168 * 3600 and ob["coverage_pct"] >= 95
        return ob

    def set_observation(self, action: str):
        with self.control_lock:
            ob = self.observation()
            if action == "start":
                if ob["status"] != "not_started": raise ValueError("Observation already exists; use resume")
                sources = [s for s in self.store.get_setting("sources", defaults()) if s.get("enabled")]
                if not sources: raise ValueError("Enable at least one source first")
                started = now()
                ob = {"status": "running", "start_at": started, "target_hours": 168, "cycles": 0, "successes": 0,
                      "target_at": (dt.datetime.fromisoformat(started) + dt.timedelta(hours=168)).isoformat(),
                      "source_plan": [{k: s[k] for k in ("id", "url", "kind", "interval_seconds")} for s in sources],
                      "source_intervals": [s["interval_seconds"] for s in sources], "timezone": "Asia/Shanghai",
                      "policy": "168h read-only source observation; offline and paused gaps remain visible in expected checks"}
                health = self.store.get_setting("source_health", {})
                for source in sources:
                    health.setdefault(source["id"], {})["next_check_epoch"] = 0
                self.store.set_setting("source_health", health)
            elif action == "pause":
                if ob["status"] != "running": raise ValueError("Observation is not running")
                ob.update(status="paused", paused_at=now())
            elif action == "resume":
                if ob["status"] != "paused": raise ValueError("Observation is not paused")
                current_sources=[{k:s[k] for k in ('id','url','kind','interval_seconds')} for s in self.store.get_setting('sources',[]) if s.get('enabled')]
                if ob.get('source_plan') is not None and ob['source_plan']!=current_sources:
                    raise ValueError('发现策略已改变，旧观察计划须单独复核，不能接续计时为同一观察')
                ob.update(status="running", resumed_at=now())
            else: raise ValueError("Unknown observation action")
            self.store.set_setting("observation", ob)
            self.store.add_event("observation_" + action, {"at": now()})
            return self.observation()

    def do_scan(self):
        if self.store.get_setting('discovery_policy',{}).get('id')=='binance-wallet-tradable-v1':
            result=self.executions.mining.refresh()
            return {'checked':0,'changed':0,'items':0,'unchanged':0,'skipped':0,'errors':0,'economic_discovery':result['status'],
                    'message':'正在核对币安钱包、真实市场和可结算路线；不再扫描未定价测试网脚本'}
        if not self.scan_lock.acquire(blocking=False):
            return {"status": "already_running", "checked": 0}
        self.scan_status={'status':'running','started_at':now()}
        try:
            # Serialize control changes while a scan is in progress, including pause.
            with self.control_lock:
                counts = scan(self.store)
                ob = self.store.get_setting("observation", {})
                if ob.get("status") == "running" and counts["checked"]:
                    ob["cycles"] = ob.get("cycles", 0) + counts["checked"]
                    ob["successes"] = ob.get("successes", 0) + counts["checked"] - counts["errors"]
                    ob["last_cycle_at"] = now()
                    self.store.set_setting("observation", ob)
                self.store.add_event("scan", counts)
                self.refresh_participation()
                self.scan_status=self.scan_status|{'status':'completed','finished_at':now(),'result':counts}
                return counts
        except Exception:
            self.scan_status=self.scan_status|{'status':'failed','finished_at':now()}
            raise
        finally:
            self.scan_lock.release()

    def request_scan(self):
        with self.scan_request_lock:
            if self.scan_lock.locked() or self.scan_thread and self.scan_thread.is_alive():return {'status':'already_running'}
            self.scan_status={'status':'queued','started_at':now()}
            self.scan_thread=threading.Thread(target=self.do_scan,daemon=True)
            self.scan_thread.start()
        return {'status':'checking','message':'正在查找未开挖公告；命中后自动加入重点待办。'}

    def loop(self):
        while not self.stop_event.wait(5):
            try:
                mining=self.executions.mining.view()
                if self.store.get_setting('discovery_policy',{}).get('id')=='binance-wallet-tradable-v1' and self.monitoring()['enabled'] and mining.get('attempt_epoch') and time.time()-mining['attempt_epoch']>1800:
                    self.executions.mining.refresh()
                if self.store.get_setting("observation", {}).get("status") == "running" or self.monitoring()["enabled"]:
                    health = self.store.get_setting("source_health", {})
                    if any(s.get("enabled") and health.get(s["id"], {}).get("next_check_epoch", 0) <= time.time()
                           for s in self.store.get_setting("sources", [])):
                        self.do_scan()
            except Exception as exc:
                self.store.add_event("scheduler_error", {"type": type(exc).__name__})

    def monitoring(self):
        return self.store.get_setting("monitoring", {"enabled":False,"mode":"rules_only"})

    def set_monitoring(self, enabled):
        if type(enabled) is not bool: raise ValueError("enabled must be boolean")
        with self.control_lock:
            value={"enabled":enabled,"mode":"rules_only","updated_at":now()}
            self.store.set_setting("monitoring",value)
            self.store.add_event("monitoring_changed",value)
        return value

    def snapshot(self):
        hardware, profile = self.store.hardware(), self.store.profile()
        plans=self.workflows.plans();jobs=self.agent_checks.jobs()
        candidates=[]
        for p in self.store.candidates():
            plan=next((item for item in plans if item['candidate_id']==p['id']),None)
            job=next((item for item in jobs if item['candidate_id']==p['id'] and item['status']=='completed' and item.get('current')),None)
            candidates.append(p|{'assessment':assess(p,hardware,profile),'compute_profile':compute_profile(p,(job or {}).get('report'),plan),
                'launch':launch_summary(p,plan,self.executions.readiness(plan) if plan and plan.get('execution_drivers') else None)})
        readiness={'ready':sum(c['launch']['status']=='ready' for c in candidates),'preparing':sum(c['launch']['status']=='preparing' for c in candidates),
            'not_integrated':sum(c['launch']['status']=='not_integrated' for c in candidates),'unsafe':sum(c['launch']['status']=='unsafe' for c in candidates)}
        health = self.store.get_setting("source_health", {})
        sources = [s | {"status": "not_checked"} | health.get(s["id"], {})
                   for s in self.store.get_setting("sources", defaults())]
        compat = ROOT / "docs" / "host-compatibility.json"
        compatibility = json.loads(compat.read_text("utf-8")) if compat.exists() else []
        policy=self.store.get_setting('discovery_policy',LAUNCH_POLICY)
        watch=self.launch_watch.view()|{'scan':self.scan_status}
        economic=self.executions.mining.candidate()
        visible=[economic|{'assessment':assess(economic,hardware,profile)}] if economic else []
        if policy.get('id')==LAUNCH_POLICY['id']:
            by_id={c['id']:c for c in candidates};visible=[]
            for item in watch['items']:
                if item['critical'] and item['candidate_id'] in by_id:
                    candidate=by_id[item['candidate_id']]
                    direction=item['compute'];label={'cpu':'CPU 优先','gpu':'GPU 其次','either':'CPU / GPU 均可 · CPU 优先','unknown':'设备待确认','asic':'ASIC 方向'}[direction]
                    visible.append(candidate|{'prelaunch':item,'compute_profile':{'priority':direction,'label':label,'basis':'launch_announcement',
                        'reason':'开挖公告中的设备方向；优先级不代表收益。','sources':[item['evidence_url']]}})
        ready_count=sum(c['launch']['can_configure'] for c in visible)
        readiness={'ready':ready_count,'preparing':0 if ready_count else 1,'not_integrated':0,'unsafe':0}
        return {"service": {"name": "Prospect", "version": __version__, "mode": "managed_execution", "pid": os.getpid(),
                            "started_at": self.started_at, "live_execution": True},
                "hardware": hardware, "profile": profile, "candidates": visible, "sources": sources,
                "discovery_archive":[c for c in candidates if c['id'] not in {v['id'] for v in visible}],"discovery_policy":policy,
                "launch_watch":watch,"lead_catalog":self.leads.page(limit=8),
                "economic_mining":self.executions.mining.view(),
                "preferences": self.store.get_setting("user_preferences", {"resource_strategy": "idle_only",
                    "priority": "do_not_disrupt", "routine_choices": "use_recommended_defaults",
                    "enforcement": "live_execution_not_implemented"}),
                "participation_requests": [],
                "scans": self.store.scans(), "runs": self.store.runs() + self.workflows.runs(), "events": self.store.events(),
                "usage": self.store.usage() | self.agent_checks.usage(), "observation": self.observation(), "host_compatibility": compatibility,
                "agent_checks": jobs, "agent_check_hosts": self.agent_checks.capabilities(), "agent_context": self.agent_context.view(),"run_readiness":readiness,
                "preparation_plans": plans, "agent_budget": self.agent_checks.budget(), "monitoring":self.monitoring(),
                "agent_settings": self.agent_settings_view(), "executions": self.executions.state()}

    def agent_settings_view(self):
        return self.agent_checks.settings.view() | {"deepseek_api": self.agent_checks.deepseek.view()}

    def refresh_participation(self):
        from .recommendations import trial_request
        with self.proposal_lock:
            latest = {}
            for plan in self.workflows.plans(): latest.setdefault(plan["candidate_id"], plan)
            proposals = [trial_request(plan) for plan in latest.values()]
            return self.store.sync_participation_requests([p for p in proposals if p])

    def decide_participation(self, ident, decision):
        with self.proposal_lock:
            self.refresh_participation()
            return self.store.decide_participation(ident, decision)

    def simulate(self, candidate_id):
        candidate = self.store.get_candidate(candidate_id)
        if not candidate: raise ValueError("Candidate not found")
        result = simulate(candidate, self.store.hardware(), self.store.profile())
        result.update(candidate_id=candidate_id, candidate_name=candidate["name"], mode="simulation", origin="user", at=now())
        return self.store.add_run(result)


class Handler(BaseHTTPRequestHandler):
    server_version = "Prospect"

    @property
    def runtime(self): return self.server.runtime

    @property
    def cookie_name(self): return f"prospect_session_{self.server.server_port}"

    def log_message(self, fmt, *args):
        # Avoid storing tokens, browser paths or user-controlled bodies in access logs.
        return

    def trusted_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def origin_ok(self):
        origin = self.headers.get("Origin")
        return origin in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")

    def native_auth(self):
        provided = self.headers.get("Authorization", "")
        return hmac.compare_digest(provided, "Bearer " + self.runtime.token)

    def authorized(self, mutation=False):
        if not self.trusted_host(): return False
        if self.headers.get("Origin") and not self.origin_ok(): return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site": return False
        if self.native_auth(): return True
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get("Cookie", ""))
        except Exception: return False
        session = cookie.get(self.cookie_name)
        if not session: return False
        with self.runtime.session_lock:
            valid = self.runtime.sessions.get(session.value, 0) > time.time()
        return valid and (not mutation or self.origin_ok())

    def reply(self, payload, status=200, cookie=None, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") if not isinstance(payload, bytes) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.trusted_host(): return self.reply({"error": "Invalid host"}, 403)
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health": return self.reply({"app": "Prospect", "version": __version__, "pid": os.getpid()})
        if path.startswith("/api/"):
            if not self.authorized(): return self.reply({"error": "Local session required"}, 403)
            if path == "/api/ready": return self.reply({"app": "Prospect", "version": __version__, "pid": os.getpid()})
            if path == "/api/state": return self.reply(self.runtime.snapshot())
            if path == '/api/launch-watch':return self.reply(self.runtime.launch_watch.view()|{'scan':self.runtime.scan_status})
            if path in ('/api/leads','/api/leads/detail'):
                try:
                    query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,keep_blank_values=True)
                    if any(len(values)!=1 for values in query.values()):raise ValueError('筛选参数不能重复')
                    params={key:values[0] for key,values in query.items()}
                    if path.endswith('/detail'):
                        if set(params)!={'id'}:raise ValueError('需要线索ID')
                        return self.reply(self.runtime.leads.detail(params['id']))
                    if set(params)-{'offset','limit','q','stage','category','compute'}:raise ValueError('未知筛选参数')
                    for key in ('offset','limit'):
                        if key in params:params[key]=int(params[key])
                    return self.reply(self.runtime.leads.page(**params))
                except (ValueError,TypeError):return self.reply({'error':'线索ID、分页或筛选条件无效'},400)
            if path == "/api/research":
                jobs=self.runtime.store.research_jobs()
                if self.runtime.store.get_setting('discovery_policy',{}).get('id')=='binance-wallet-tradable-v1':
                    candidate=self.runtime.executions.mining.candidate()
                    jobs=[j for j in jobs if j['status']!='pending' or candidate and j['candidate_id']==candidate['id']]
                else:
                    allowed={x['candidate_id'] for x in self.runtime.launch_watch.view()['items'] if x['critical']}
                    jobs=[j for j in jobs if j['status']!='pending' or j['candidate_id'] in allowed]
                return self.reply(jobs)
            if path == "/api/agent-settings": return self.reply(self.runtime.agent_settings_view())
            if path == "/api/agent-context": return self.reply(self.runtime.agent_context.view())
            if path == "/api/executions": return self.reply(self.runtime.executions.state())
            if path in ("/api/executions/logs", "/api/executions/receipt"):
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    ident = query.get("id", [""])[0]
                    result = self.runtime.executions.logs(ident, int(query.get("after", ["0"])[0])) if path.endswith("logs") else self.runtime.executions.receipt(ident)
                    return self.reply(result)
                except (ValueError, TypeError): return self.reply({"error": "运行任务或日志游标无效"}, 400)
            if path == "/api/checks": return self.reply({"jobs": self.runtime.agent_checks.jobs(), "hosts": self.runtime.agent_checks.capabilities(), "agent_context": self.runtime.agent_context.view(), "budget":self.runtime.agent_checks.budget(), "server_at":now()})
            if path == '/api/mining':return self.reply(self.runtime.executions.mining.view())
            return self.reply({"error": "Unknown route"}, 404)
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/executions.js": ("executions.js", "text/javascript; charset=utf-8"),
                  "/participation.js": ("participation.js", "text/javascript; charset=utf-8"),
                  "/mining.js": ("mining.js", "text/javascript; charset=utf-8"),
                  "/launch-watch.js": ("launch-watch.js", "text/javascript; charset=utf-8"),
                  "/leads.js": ("leads.js", "text/javascript; charset=utf-8"),
                  "/leads.css": ("leads.css", "text/css; charset=utf-8"),
                  "/launch-watch.css": ("launch-watch.css", "text/css; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        if path not in assets: return self.reply({"error": "Not found"}, 404)
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or (self.headers.get("Origin") and not self.origin_ok()):
            return self.reply({"error": "Open the local app directly"}, 403)
        filename, mime = assets[path]
        asset = ROOT / "web" / filename
        if not asset.exists(): return self.reply({"error": "UI asset missing"}, 503)
        cookie = None
        if path == "/":
            session = secrets.token_urlsafe(32)
            with self.runtime.session_lock:
                self.runtime.sessions = {k: v for k, v in self.runtime.sessions.items() if v > time.time()}
                if len(self.runtime.sessions) >= 100: self.runtime.sessions.pop(next(iter(self.runtime.sessions)))
                self.runtime.sessions[session] = time.time() + 86400
            cookie = f"{self.cookie_name}={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400"
        return self.reply(asset.read_bytes(), cookie=cookie, content_type=mime)

    def do_POST(self):
        if not self.authorized(mutation=True):
            # Unread rejected bytes can turn a valid 403 into a TCP reset on Windows.
            # Drain only a bounded body, without parsing or performing its operation.
            try:
                rejected_length = int(self.headers.get("Content-Length", "0"))
                if 0 < rejected_length <= 262144:
                    self.connection.settimeout(1)
                    self.rfile.read(rejected_length)
            except (ValueError, OSError):
                pass
            return self.reply({"error": "Unauthorized or invalid origin"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 262144: raise ValueError("Request too large")
            if self.headers.get_content_type() != "application/json": raise ValueError("JSON content type required")
            payload = json.loads(self.rfile.read(length) or b"{}", parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
            if not isinstance(payload, dict): raise ValueError("Expected object")
            rt = self.runtime
            if self.path == "/api/scan":
                result=rt.request_scan() if rt.store.get_setting('discovery_policy',{}).get('id')==LAUNCH_POLICY['id'] else rt.do_scan()
            elif self.path == '/api/launch-watch/decision':result=rt.launch_watch.decide(payload.get('id'),payload.get('status'))
            elif self.path == '/api/launch-watch/report':
                if not self.native_auth():return self.reply({'error':'Only local Agent adapters can submit launch evidence'},403)
                result=rt.launch_watch.observe(payload.get('candidate_id'),payload.get('signal'))
            elif self.path == "/api/profile":
                rt.store.save_profile(payload)
                result = rt.store.profile()
            elif self.path == "/api/simulate": result = rt.simulate(str(payload.get("candidate_id", "")))
            elif self.path == "/api/agent-settings":
                rt.agent_checks.settings.save(payload); result = rt.agent_settings_view()
            elif self.path == "/api/agent-context/observe":
                if not self.native_auth(): return self.reply({"error":"Agent observations require the native adapter"},403)
                result = rt.agent_context.observe(payload)
            elif self.path == "/api/agent-settings/deepseek": result = rt.agent_checks.deepseek.save(payload)
            elif self.path == "/api/agent-settings/deepseek/test":
                if payload: raise ValueError("连接测试使用已保存的设置")
                result = rt.agent_checks.deepseek.test()
            elif self.path == "/api/executions/preview":
                if set(payload) - {"driver", "plan_id", "options", "inputs"}: raise ValueError("不支持这些运行参数")
                result = rt.executions.preview(**payload)
            elif self.path == '/api/mining/refresh':
                if payload:raise ValueError('挖矿准备不接受自定义命令或钱包参数')
                result=rt.executions.mining.refresh()
            elif self.path == '/api/mining/reconcile':
                if set(payload)!={'id'}:raise ValueError('请选择需要核对收益的运行')
                result=rt.executions.reconcile(payload['id'])
            elif self.path == '/api/wallet/connect':
                if set(payload)!={'confirmed'}:raise ValueError('连接钱包需要明确确认')
                result=rt.executions.mining.wallet_connection.start(payload['confirmed'])
            elif self.path == "/api/executions/start":
                if set(payload) != {"quote_id", "key", "confirmed"}: raise ValueError("启动需要已审阅的方案与一次运行确认")
                result = rt.executions.start(**payload)
            elif self.path == "/api/executions/cancel": result = rt.executions.cancel(payload.get("id"))
            elif self.path == "/api/checks/request":
                host=payload.get("host","any")
                if host=="current":host=rt.agent_context.resolve()
                result = rt.agent_checks.request(payload.get("candidate_id"),host)
            elif self.path == "/api/checks/cancel": result = rt.agent_checks.cancel(payload.get("id"))
            elif self.path == "/api/monitoring": result = rt.set_monitoring(payload.get("enabled"))
            elif self.path == "/api/budget":
                rt.store.set_setting("agent_budget",validate_policy(payload))
                result=rt.agent_checks.budget()
            elif self.path == "/api/plans/simulate":
                if payload.get("fault_step") and not self.native_auth(): return self.reply({"error":"Only local adapters may inject test failures"},403)
                result=rt.workflows.run(payload.get("plan_id"),payload.get("key"),payload.get("fault_step"),payload.get("resume_id"))
            elif self.path == "/api/plans/cancel": result=rt.workflows.cancel(payload.get("id"))
            elif self.path == "/api/checks/claim":
                if not self.native_auth(): return self.reply({"error": "Only local Agent adapters can claim checks"}, 403)
                result = rt.agent_checks.claim(payload.get("host"), payload.get("id"))
            elif self.path == "/api/checks/complete":
                if not self.native_auth(): return self.reply({"error": "Only local Agent adapters can submit reports"}, 403)
                if not payload.get('error'):
                    validation=rt.agent_checks.validate_submission(payload.get('id'),payload.get('host'),payload.get('lease_token'),payload.get('report'),payload.get('usage'))
                    if validation['status']=='needs_correction':return self.reply(validation)
                result = rt.agent_checks.complete(payload.get("id"), payload.get("host"), payload.get("lease_token"), payload.get("report"), payload.get("error"),payload.get('usage'))
                rt.refresh_participation()
            elif self.path=='/api/checks/validate':
                if not self.native_auth():return self.reply({'error':'Only local Agent adapters can validate reports'},403)
                result=rt.agent_checks.validate_submission(payload.get('id'),payload.get('host'),payload.get('lease_token'),payload.get('report'),payload.get('usage'))
            elif self.path == "/api/checks/progress":
                if not self.native_auth(): return self.reply({"error": "Only local Agent adapters can report progress"},403)
                result=rt.agent_checks.progress(payload.get("id"),payload.get("host"),payload.get("lease_token"),payload.get("stage"))
            elif self.path == "/api/import":
                if payload.get("path"): raise ValueError("Only the fixed legacy database can be imported")
                result = import_legacy(rt.store, LEGACY_DB)
            elif self.path == "/api/hardware":
                rt.refresh_hardware()
                result = rt.store.hardware()
            elif self.path == "/api/observation": result = rt.set_observation(payload.get("action"))
            elif self.path == "/api/research/resolve":
                if not self.native_auth(): return self.reply({"error":"Only local Agent adapters can submit research evidence"},403)
                result = rt.store.resolve_research(payload.get("id"), payload.get("result"))
                result = result | {"participation_requests": [p for p in rt.refresh_participation() if p["status"] == "pending"][:3],
                                   "next_action": "Present pending participation plans to the user. No execution is authorized."}
            elif self.path == "/api/participation/decision": result = rt.decide_participation(payload.get("id"), payload.get("decision"))
            elif self.path == "/api/sources":
                if type(payload.get("enabled")) is not bool: raise ValueError("enabled must be boolean")
                with rt.control_lock:
                    observation=rt.observation()
                    if observation['status']=='running':
                        raise ValueError("七日只读观察正在运行。请先在总览暂停观察，再调整来源。")
                    sources = rt.store.get_setting("sources", defaults())
                    matched = [s for s in sources if s["id"] == payload.get("id")]
                    if not matched: raise ValueError("Unknown source")
                    matched[0]["enabled"] = payload["enabled"]
                    rt.store.set_setting("sources", sources)
                result = matched[0]
            elif self.path == "/api/shutdown":
                if not self.native_auth(): return self.reply({"error": "Use the local CLI to stop the service"}, 403)
                result = {"stopping": True}
                rt.stop_event.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else: return self.reply({"error": "Unknown route"}, 404)
            if self.path == "/api/profile": rt.refresh_participation()
            return self.reply(result)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return self.reply({"error": str(exc)[:300]}, 400)
        except Exception as exc:
            self.runtime.store.add_event("api_error", {"type": type(exc).__name__})
            return self.reply({"error": "Internal error; check local diagnostic events"}, 500)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class DirectoryLock:
    """Process-lifetime advisory lock; different ports cannot share execution state."""
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.handle = open(Path(directory) / "service.lock", "a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("Another Prospect service owns this data directory") from None

    def close(self):
        if self.handle.closed: return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def serve(directory: Path, port: int):
    directory_lock = DirectoryLock(directory)
    server = runtime = None
    control = directory / "control.json"
    try:
        server = LocalServer(("127.0.0.1", port), Handler)
        runtime = Runtime(directory, server.server_port)
        server.runtime = runtime
        runtime.server = server
        # Control token stays in the user's private runtime directory.
        write_private(control, {"app": "Prospect", "pid": os.getpid(), "port": server.server_port,
                                "token": runtime.token, "started_at": runtime.started_at})
        if not runtime.store.hardware():
            threading.Thread(target=runtime.refresh_hardware, daemon=True).start()
        scheduler = threading.Thread(target=runtime.loop, daemon=True)
        scheduler.start()
        print(f"Prospect http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever(poll_interval=0.3)
    finally:
        if runtime:
            runtime.stop_event.set()
            runtime.agent_checks.shutdown()
            runtime.executions.shutdown()
        if server: server.server_close()
        try:
            current = json.loads(control.read_text("utf-8"))
            if current.get("pid") == os.getpid(): control.unlink()
        except (OSError, ValueError): pass
        directory_lock.close()
