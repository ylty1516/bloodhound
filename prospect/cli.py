"""Machine-readable native interface shared by all host adapters."""
from __future__ import annotations
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .service import ROOT, data_directory, serve


def control(directory):
    try: return json.loads((directory / "control.json").read_text("utf-8"))
    except (OSError, ValueError): return None


def request(directory, port, path="/api/state", data=None, timeout=50):
    credential = control(directory)
    if not credential or credential.get("port") != port: raise RuntimeError("Service is not running for this data directory")
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=payload,
                                 headers={"Authorization": "Bearer " + credential["token"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response: return json.load(response)
    except urllib.error.HTTPError as exc:
        try: message = json.load(exc).get("error", f"HTTP {exc.code}")
        except (ValueError, AttributeError): message = f"HTTP {exc.code}"
        raise RuntimeError(message) from None


def ensure(directory, port, timeout=8):
    existing = control(directory)
    if existing and existing.get("port") != port:
        try:
            request(directory, existing["port"], "/api/ready", timeout=0.5)
        except (OSError, RuntimeError, ValueError):
            pass
        else:
            raise RuntimeError(f"This data directory is already served on port {existing['port']}")
    # Windows may spend a full socket timeout on a refused loopback connection.
    # A short TCP probe avoids paying the HTTP timeout on each cold-start client.
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.05):
            listening = True
    except OSError:
        listening = False
    if listening:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as r:
                health = json.load(r)
            if health.get("app") != "Prospect": raise RuntimeError("Port occupied by another application")
            # Verify the private credential, not only a process's claimed app name.
            request(directory, port, "/api/ready", timeout=0.5)
            return {"running": True, "started": False, "port": port, "pid": health["pid"]}
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
    directory.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "prospect", "--data-dir", str(directory), "--port", str(port), "serve"]
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    with open(directory / "service.log", "ab") as log:
        subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = request(directory, port, "/api/ready", timeout=min(0.5, max(0.05, deadline - time.monotonic())))
            return {"running": True, "started": True, "port": port, "pid": state["pid"]}
        except (OSError, RuntimeError, ValueError):
            time.sleep(0.1)
    raise RuntimeError("Service did not become ready; inspect service.log")


def observe_agent(directory,port,expected=None,source="tool"):
    from .agent_context import caller_agent
    try:
        caller=caller_agent(expected)
        if caller:request(directory,port,"/api/agent-context/observe",caller|{"source":source},timeout=2)
    except (OSError,ValueError,RuntimeError):
        pass  # Detection must never prevent the requested tool or an older daemon.


def tool(directory, port, name, arguments, agent_host=None):
    ensure(directory, port)
    observe_agent(directory,port,agent_host)
    if name == "prospect_scan": return request(directory, port, "/api/scan", {})
    if name == "prospect_simulate": return request(directory, port, "/api/simulate", arguments)
    if name == "prospect_research_pending": return [j for j in request(directory, port, "/api/research") if j.get("status") == "pending"][:5]
    if name == "prospect_research_resolve": return request(directory, port, "/api/research/resolve", arguments)
    if name == "prospect_check_pending":
        result = request(directory, port, "/api/checks")
        return {"jobs": [{k: j.get(k) for k in ("id", "candidate_name", "requested_host", "status", "current")} for j in result["jobs"] if j["status"] == "queued"][:5],
                "instructions": "Claim with your host id (codex/claude/pi/deepseek), research using read-only sources, then complete using the lease token and report schema. Do not execute project software."}
    for action in ("request", "claim", "validate", "complete", "cancel", "progress"):
        if name == "prospect_check_" + action: return request(directory, port, "/api/checks/" + action, arguments)
    if name == "prospect_plan_simulate": return request(directory, port, "/api/plans/simulate", arguments)
    if name == "prospect_monitoring": return request(directory, port, "/api/monitoring", arguments)
    if name == "prospect_executions": return request(directory, port, "/api/executions")
    if name == 'prospect_launch_watch':return request(directory,port,'/api/launch-watch')
    if name == 'prospect_launch_report':return request(directory,port,'/api/launch-watch/report',arguments)
    if name == 'prospect_mining_status':return request(directory,port,'/api/mining')
    if name == 'prospect_mining_prepare':return request(directory,port,'/api/mining/refresh',{})
    if name == 'prospect_mining_reconcile':return request(directory,port,'/api/mining/reconcile',arguments)
    if name == 'prospect_wallet_connect':return request(directory,port,'/api/wallet/connect',arguments)
    if name=='prospect_candidates':
        from urllib.parse import urlencode
        allowed={'offset','limit','q','stage','category','compute'}
        if set(arguments)-allowed:raise ValueError('Unknown candidate filter')
        for key in ('offset','limit'):
            if key in arguments and type(arguments[key]) is not int:raise ValueError('Pagination values must be integers')
        result=request(directory,port,'/api/leads?'+urlencode(arguments))
        result['items']=[{key:item.get(key) for key in ('id','name','category','classification','url','compute_profile','lead_info','prelaunch')}
            |{'assessment':{'status':item['assessment']['status'],'missing':item['assessment']['missing']}} for item in result['items']]
        return result
    if name=='prospect_assess':
        from urllib.parse import urlencode
        return request(directory,port,'/api/leads/detail?'+urlencode({'id':arguments.get('candidate_id','')}))
    for action in ("preview", "start", "cancel"):
        if name == "prospect_execution_" + action: return request(directory, port, "/api/executions/" + action, arguments)
    if name in ("prospect_execution_logs", "prospect_execution_receipt"):
        from urllib.parse import urlencode
        return request(directory, port, "/api/executions/" + name.removeprefix("prospect_execution_") + "?" + urlencode(arguments))
    state = request(directory, port)
    if name == "prospect_plans":
        items=state.get("preparation_plans",[])
        if arguments.get("plan_id"): return next((p for p in items if p["id"]==arguments["plan_id"]),None)
        return [{k:p[k] for k in ("id","candidate_name","status","blockers","execution_authorized")} for p in items[:5]]
    if name == "prospect_status":
        return {"service": state["service"], "candidate_count": len(state["candidates"]),
                "run_count": sum(r.get("origin") != "validation" for r in state["runs"]),
                "validation_run_count": sum(r.get("origin") == "validation" for r in state["runs"]),
                "participation_requests": [{k: p.get(k) for k in ("id", "candidate_name", "reasons", "blockers", "readiness")} for p in state.get("participation_requests", []) if p["status"] == "pending"][:3],
                "discovery_policy":state.get('discovery_policy'),
                "all_lead_count":state.get('lead_catalog',{}).get('total',len(state['candidates'])),
                "lead_stages":state.get('lead_catalog',{}).get('counts',{}),
                "priority_todos":[{k:x.get(k) for k in ('id','candidate_id','name','compute','phase','starts_at','todo_status','evidence_url','evidence_kind')} for x in state.get('launch_watch',{}).get('items',[]) if x.get('critical')][:10],
                "action_required": "Prioritize new announced-but-not-started mining tasks: CPU first, GPU second. Present new important todo IDs once; no Binance/trading gate. A task never authorizes mining.",
                "agent_check_queue": [{k: j.get(k) for k in ("id", "candidate_name", "requested_host", "status")} for j in state.get("agent_checks", []) if j["status"] in ("queued", "running")][:3],
                "usage": state["usage"], "observation": state["observation"], "monitoring":state.get("monitoring"), "agent_budget":state.get("agent_budget"),
                "preparation_plans":[{k:p[k] for k in ("id","candidate_name","status")} for p in state.get("preparation_plans",[])[:3]],
                "executions": state.get("executions"), "agent_context":state.get("agent_context"),
                "note": "Discovery and checks never start projects. Reviewed execution scopes can be explicitly started once."}
    raise ValueError("Unknown Prospect tool")


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def main():
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Prospect local opportunity operations")
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--port", type=int, default=int(os.environ.get("PROSPECT_PORT", "18766")))
    parser.add_argument("--agent-host",choices=("codex","claude","pi","deepseek"),default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    for c in ("serve", "ensure", "status", "scan", "hardware", "import-legacy", "candidates", "research", "ui", "stop", "doctor"):
        sub.add_parser(c)
    sim = sub.add_parser("simulate"); sim.add_argument("candidate_id")
    dashboard_cmd = sub.add_parser("dashboard"); dashboard_cmd.add_argument("--watch", action="store_true")
    profile = sub.add_parser("profile"); profile.add_argument("json")
    ob = sub.add_parser("observe"); ob.add_argument("action", choices=("start", "pause", "resume"))
    native = sub.add_parser("tool"); native.add_argument("name"); native.add_argument("json", nargs="?", default="{}")
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535: parser.error("Use an unprivileged port between 1024 and 65535")
    try:
        if args.command == "serve": return serve(args.data_dir, args.port)
        if args.command == "ensure":
            result=ensure(args.data_dir,args.port)
            if args.agent_host:observe_agent(args.data_dir,args.port,args.agent_host,"startup")
            return emit(result)
        if args.command == "stop": return emit(request(args.data_dir, args.port, "/api/shutdown", {}))
        if args.command == "tool": return emit(tool(args.data_dir, args.port, args.name, json.loads(args.json),args.agent_host))
        ensure(args.data_dir, args.port)
        if args.command == "dashboard":
            from .terminal import dashboard
            return dashboard(lambda: request(args.data_dir, args.port), lambda: request(args.data_dir, args.port, "/api/scan", {}), args.watch)
        if args.command == "ui":
            webbrowser.open(f"http://127.0.0.1:{args.port}/")
            return emit({"url": f"http://127.0.0.1:{args.port}/"})
        routes = {"scan": ("/api/scan", {}), "hardware": ("/api/hardware", {}), "import-legacy": ("/api/import", {}),
                  "simulate": ("/api/simulate", {"candidate_id": getattr(args, "candidate_id", "")}),
                  "observe": ("/api/observation", {"action": getattr(args, "action", "")})}
        if args.command == "profile": return emit(request(args.data_dir, args.port, "/api/profile", json.loads(args.json)))
        if args.command in routes:
            path, body = routes[args.command]
            return emit(request(args.data_dir, args.port, path, body))
        if args.command == "research": return emit(request(args.data_dir, args.port, "/api/research"))
        state = request(args.data_dir, args.port)
        if args.command == "candidates": return emit(state["candidates"])
        if args.command == "doctor":
            return emit({"service": state["service"], "hardware": state["hardware"], "hosts": state["host_compatibility"],
                         "source_health": state["sources"], "data_directory": str(args.data_dir)})
        return emit(state)
    except (OSError, ValueError, RuntimeError) as exc:
        emit({"error": str(exc)[:500]})
        raise SystemExit(1)
