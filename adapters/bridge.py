"""Dependency-free MCP stdio bridge; all product actions go through its CLI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE_BYTES = 1024 * 1024


def _schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name":"prospect_launch_watch","description":"Read priority mining-launch todos: announced but not yet open, CPU first and GPU second. Wallet compatibility and trading value are annotations, not gates. Show newly discovered important IDs to the user; never start mining from a todo.","inputSchema":_schema()},
    {"name":"prospect_launch_report","description":"Record an actually researched mining-launch announcement and automatically create/update its priority todo. candidate_id must exist. signal uses the mining_launch report schema: announced/status/starts_at/compute/network/wallet/evidence_url/evidence_note/evidence_kind; never guess dates or submit execution commands.","inputSchema":_schema({"candidate_id":{"type":"string"},"signal":{"type":"object"}},("candidate_id","signal"))},
    {"name":"prospect_wallet_connect","description":"Open official Binance Agentic Wallet sign-in only after explicit user confirmation. Returns real login progress via prospect_mining_status; show the exact official URL and pairing code, let the user approve in Binance App. Never asks for a seed/key and never signs/trades/sends funds. Do not connect on startup or when a verified receive address is sufficient.","inputSchema":_schema({"confirmed":{"type":"boolean"}},("confirmed",))},
    {"name":"prospect_mining_status","description":"Read the reviewed CPU-to-USDT/BSC route, receiving-wallet proof, live tradability, preparation stage and payout threshold. No mining, wallet signatures or model calls.","inputSchema":_schema()},
    {"name":"prospect_mining_prepare","description":"Prepare the real economic mining route using official read-only wallet/market/pool checks. Asynchronous: returns the actual current stage. Does not install or mine. Unknown wallet or tradability evidence excludes the project.","inputSchema":_schema()},
    {"name":"prospect_mining_reconcile","description":"Recheck pool credit and verify on-chain BSC USDT receipt for an existing mining run. Read-only; never requests a payout or signs. A pool balance is not wallet delivery.","inputSchema":_schema({"id":{"type":"string"}},("id",))},
    {"name":"prospect_check_progress","description":"Report an actual check stage using your lease; call only when work changes, never simulate progress. Stages: starting, connected, searching, reading, comparing, writing, retrying, validating. No raw thoughts or secrets.","inputSchema":_schema({"id":{"type":"string","minLength":1},"host":{"type":"string","minLength":1},"lease_token":{"type":"string","minLength":1},"stage":{"type":"string","minLength":1}},("id","host","lease_token","stage"))},
    {"name": "prospect_status", "description": "Read Prospect service status and measured usage.", "inputSchema": _schema()},
    {"name": "prospect_candidates", "description": "Page through ALL stored leads, including historical/unreviewed records. lead_info explains evidence-based stage and retention/exclusion reasons; unknown is never worthless. Filters: q, stage(all/unverified/upcoming/open/excluded), category(all/pow/node/tasks), compute(all/cpu/gpu/either/none/unknown/asic). Priority todos are separate; this never authorizes execution.", "inputSchema": _schema({"offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50},"q":{"type":"string"},"stage":{"type":"string"},"category":{"type":"string"},"compute":{"type":"string"}})},
    {"name": "prospect_scan", "description": "Refresh allowed public sources; never mine, install, sign or pay.", "inputSchema": _schema()},
    {"name": "prospect_assess", "description": "Assess one candidate against the local hardware and preferences.", "inputSchema": _schema({"candidate_id": {"type": "string", "minLength": 1}}, ("candidate_id",))},
    {"name": "prospect_simulate", "description": "Record an explicitly simulated workflow; no real participation or rewards.", "inputSchema": _schema({"candidate_id": {"type": "string", "minLength": 1}}, ("candidate_id",))},
    {"name": "prospect_research_pending", "description": "Read pending research without calling a model.", "inputSchema": _schema()},
    {"name": "prospect_research_resolve", "description": "Store an evidence-reviewed result; cannot approve project execution.", "inputSchema": _schema({"id": {"type": "string", "minLength": 1}, "result": {"type": "object"}}, ("id", "result"))},
    {"name": "prospect_check_pending", "description": "Read user-requested Agent check queue. All four hosts can claim one task; do not run or install project code.", "inputSchema": _schema()},
    {"name": "prospect_check_request", "description": "Request a read-only Agent review of one project. Host can be any, codex, claude, pi or deepseek; native CLI dispatch uses the host's model allowance. Deduplicates current checks.", "inputSchema": _schema({"candidate_id": {"type": "string", "minLength": 1}, "host": {"type": "string", "minLength": 1}}, ("candidate_id",))},
    {"name": "prospect_check_claim", "description": "Atomically claim an Agent check as codex/claude/pi/deepseek. Returns limited project/device context, read-only research instructions, report schema and a private lease_token. Never show the token to the user. Use native read-only search, then complete with evidence or error; no installations/signatures/payments.", "inputSchema": _schema({"host": {"type": "string", "minLength": 1}, "id": {"type": "string", "minLength": 1}}, ("host",))},
    {"name":"prospect_check_validate","description":"Validate a draft report using the SAME claimed id/host/lease_token before submission. If needs_correction is returned, fix only the report and resubmit; do not repeat research or change models. Validation does not accept facts or authorize execution.","inputSchema":_schema({"id":{"type":"string"},"host":{"type":"string"},"lease_token":{"type":"string"},"report":{"type":"object"},"usage":{"type":"object"}},("id","host","lease_token","report"))},
    {"name": "prospect_check_complete", "description": "Submit a cited Agent report or bounded error for a claimed task. Must match host and lease_token. If needs_correction is returned, revise the report using the claim schema and resubmit with the SAME lease; no repeated research or model switch. Stale inputs invalidate the report; this never authorizes execution.", "inputSchema": _schema({"id": {"type": "string", "minLength": 1}, "host": {"type": "string", "minLength": 1}, "lease_token": {"type": "string", "minLength": 1}, "report": {"type": "object"}, "usage":{"type":"object"}, "error": {"type": "string", "minLength": 1}}, ("id", "host", "lease_token"))},
    {"name": "prospect_check_cancel", "description": "Cancel one Agent check; a cancelled result cannot later be submitted.", "inputSchema": _schema({"id": {"type": "string", "minLength": 1}}, ("id",))},
    {"name": "prospect_plans", "description": "Read preparation plans generated from Agent reports. Supply plan_id for a full plan, pinned recipe and remaining conditions; no execution is authorized.", "inputSchema": _schema({"plan_id": {"type":"string", "minLength":1}})},
    {"name": "prospect_plan_simulate", "description": "Rehearse a versioned plan with mock project steps. No downloads, mining, wallets, rewards or other external effects. Reuse key for idempotency; resume_id resumes an interrupted simulation only.", "inputSchema": _schema({"plan_id":{"type":"string","minLength":1},"key":{"type":"string","minLength":1},"resume_id":{"type":"string","minLength":1}},("plan_id","key"))},
    {"name": "prospect_monitoring", "description": "Enable or pause persistent public-source discovery using configured source intervals. Rules only, zero model calls; does not start formal observation or mining.", "inputSchema": _schema({"enabled":{"type":"boolean"}},("enabled",))},
    {"name":"prospect_executions","description":"Read actual execution status, heartbeat, process limits and result availability. Separate from Agent reviews and simulations.","inputSchema":_schema()},
    {"name":"prospect_execution_preview","description":"Prepare a reviewable one-run scope without starting processes. Show scope, limits and blockers to the user. Fixed drivers only; never accept arbitrary shell commands.","inputSchema":_schema({"driver":{"type":"string"},"plan_id":{"type":"string"},"options":{"type":"object"},"inputs":{"type":"object"}},("driver",))},
    {"name":"prospect_execution_start","description":"Start one reviewed scope only after the user has authorized this concrete project, resource limits and one-run scope. Do not infer permission from a passed review or participation interest. Reuse quote_id and key when retrying. Does not authorize daily schedules, wallet creation, signatures or payments.","inputSchema":_schema({"quote_id":{"type":"string"},"key":{"type":"string"},"confirmed":{"type":"boolean"}},("quote_id","key","confirmed"))},
    {"name":"prospect_execution_cancel","description":"Stop an execution and its process tree; read status until cleanup is complete.","inputSchema":_schema({"id":{"type":"string"}},("id",))},
    {"name":"prospect_execution_logs","description":"Read bounded, redacted execution logs using a sequence cursor. Returns at most 200 lines; reuse cursor to avoid repeating context.","inputSchema":_schema({"id":{"type":"string"},"after":{"type":"integer","minimum":0}},("id",))},
    {"name":"prospect_execution_receipt","description":"Read the final execution receipt. Process exit, diagnostic verification, node evidence and mining rewards are separate facts.","inputSchema":_schema({"id":{"type":"string"}},("id",))},
]


def validate_tool(name: str, arguments: dict) -> None:
    tool = next((tool for tool in TOOLS if tool["name"] == name), None)
    if tool is None:
        raise ValueError("Unknown Prospect tool")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    schema = tool["inputSchema"]
    if set(arguments) - set(schema["properties"]):
        raise ValueError("Unexpected tool argument")
    for key in schema["required"]:
        if key not in arguments:
            raise ValueError(f"Missing argument: {key}")
    for key, value in arguments.items():
        kind = schema["properties"][key]["type"]
        if kind == "string" and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{key} must be a nonempty string")
        if kind == "object" and not isinstance(value, dict):
            raise ValueError(f"{key} must be an object")
        if kind == "boolean" and type(value) is not bool:
            raise ValueError(f"{key} must be boolean")
        if kind == "integer":
            field = schema["properties"][key]
            if type(value) is not int or value < field.get("minimum", value) or value > field.get("maximum", value):
                raise ValueError(f"{key} must be an integer in the allowed range")


def read_config(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) - {"schema_version", "python", "project_root", "data_dir", "port", "host"}:
        raise ValueError("Adapter configuration accepts only local runtime settings")
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported adapter configuration")
    if config.get("host") is not None and config["host"] not in ("codex","claude","pi","deepseek"):
        raise ValueError("Unknown adapter host")
    for name in ("python", "project_root"):
        if not isinstance(config.get(name), str) or not Path(config[name]).is_absolute():
            raise ValueError(f"{name} must be an absolute path")
    if not Path(config["python"]).is_file():
        raise ValueError("Configured Python interpreter is unavailable")
    if not (Path(config["project_root"]) / "prospect" / "__main__.py").is_file():
        raise ValueError("Prospect CLI is unavailable at configured project_root")
    port = config.get("port", 18766)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return config


def cli_argv(config: dict, *arguments: str) -> list[str]:
    argv = [config["python"], "-m", "prospect"]
    if config.get("data_dir"):
        argv += ["--data-dir", config["data_dir"]]
    argv += ["--port", str(config.get("port", 18766))]
    if config.get("host"): argv += ["--agent-host",config["host"]]
    argv += arguments
    return argv


def invoke(config: dict, *arguments: str, timeout: float = 30) -> dict:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    # The configured checkout, rather than an unrelated current directory, owns the CLI.
    environment["PYTHONPATH"] = config["project_root"]
    completed = subprocess.run(
        cli_argv(config, *arguments), cwd=config["project_root"], env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-1600:]
        raise RuntimeError(f"Prospect CLI failed ({completed.returncode}): {detail}")
    if len(completed.stdout.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise RuntimeError("Prospect result exceeds adapter size limit")
    if not completed.stdout.strip():
        return {}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Prospect CLI returned invalid JSON") from exc
    if not isinstance(result, dict):
        return {"result": result}
    if result.get("error"):
        raise RuntimeError(str(result["error"])[:1600])
    return result


def call_tool(config: dict, name: str, arguments: dict) -> dict:
    validate_tool(name, arguments)
    return invoke(config, "tool", name, json.dumps(arguments, ensure_ascii=False), timeout=60)


class MCPServer:
    def __init__(self, tool_runner: Callable[[str, dict], dict]):
        self.tool_runner = tool_runner
        self.initialized = False

    @staticmethod
    def error(request_id, code: int, message: str):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return self.error(request.get("id") if isinstance(request, dict) else None, -32600, "Invalid request")
        if "id" not in request:
            return None  # Notifications never receive responses or execute product tools.
        request_id = request["id"]
        method = request["method"]
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "params must be an object")
        if method == "initialize":
            version = params.get("protocolVersion")
            if version not in PROTOCOL_VERSIONS:
                version = PROTOCOL_VERSIONS[0]
            self.initialized = True
            result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "prospect-local", "version": "0.1.0"}}
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return self.error(request_id, -32002, "Initialize the server first")
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments", {})
            try:
                validate_tool(name, arguments)
            except ValueError as exc:
                return self.error(request_id, -32602, str(exc))
            try:
                value = self.tool_runner(name, arguments)
                result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                          "structuredContent": value, "isError": False}
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                result = {"content": [{"type": "text", "text": str(exc)[:2000]}], "isError": True}
        else:
            return self.error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def serve(self, reader, writer):
        while True:
            line = reader.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                break
            if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                while line and not line.endswith("\n"):
                    line = reader.readline(MAX_MESSAGE_BYTES + 1)
                response = self.error(None, -32600, "Message exceeds size limit")
            else:
                try:
                    response = self.handle(json.loads(line))
                except (ValueError, UnicodeError):
                    response = self.error(None, -32700, "Parse error")
            if response is not None:
                writer.write(json.dumps(response, ensure_ascii=False) + "\n")
                writer.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        if config.get("host"):
            try: invoke(config,"ensure",timeout=5)
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError): pass
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        MCPServer(lambda name, arguments: call_tool(config, name, arguments)).serve(sys.stdin, sys.stdout)
    except (OSError, ValueError) as exc:
        print(f"Prospect MCP configuration error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
