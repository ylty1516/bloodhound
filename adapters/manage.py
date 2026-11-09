"""Prepare reviewable adapters; installation never edits host settings."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

try:
    from .bridge import TOOLS
except ImportError:
    from bridge import TOOLS

HERE = Path(__file__).resolve().parent
HOSTS = ("codex", "claude", "pi", "deepseek")
OWNER = "prospect-adapter-v1"
MARKER = ".prospect-owned.json"

RUNNER = '''import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const configPath = fileURLToPath(new URL('./runtime.json', import.meta.url));
const launcher = fileURLToPath(new URL('./launch.py', import.meta.url));
const config = JSON.parse(readFileSync(configPath, 'utf8'));
export const tools = JSON.parse(readFileSync(new URL('./tools.json', import.meta.url), 'utf8'));
export function run(args, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('Prospect request cancelled')); return; }
    const child = spawn(config.python, [launcher, '--config', configPath, ...args], {
      cwd: config.project_root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUTF8: '1' }
    });
    let stdout = '', stderr = '', settled = false;
    const finish = (error, value) => {
      if (settled) return; settled = true;
      clearTimeout(timer); signal?.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(value);
    };
    const abort = () => { child.kill(); finish(new Error('Prospect request cancelled')); };
    const timer = setTimeout(() => { child.kill(); finish(new Error('Prospect request timed out')); }, args[0] === 'ensure' ? 6000 : 65000);
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', data => {
      stdout += data;
      if (Buffer.byteLength(stdout) > 1048576) { child.kill(); finish(new Error('Prospect result is too large')); }
    });
    child.stderr.on('data', data => { stderr = (stderr + data).slice(-2000); });
    child.on('error', error => finish(error));
    child.on('close', code => {
      if (code !== 0) { finish(new Error(stderr || `Prospect exited with code ${code}`)); return; }
      try { finish(null, stdout.trim() ? JSON.parse(stdout) : {}); }
      catch { finish(new Error('Prospect returned invalid JSON')); }
    });
  });
}
'''

PI_EXTENSION = '''import { run, tools } from './runner.mjs';
export default function (pi) {
  pi.on('session_start', (_event, ctx) => {
    // Return immediately. The CLI owns daemon locking and lifetime.
    void run(['ensure']).catch(() => {
      if (ctx.hasUI) ctx.ui.setStatus('prospect', 'Prospect unavailable; use doctor');
    });
  });
  for (const tool of tools) {
    pi.registerTool({
      name: tool.name, label: tool.name, description: tool.description,
      parameters: tool.inputSchema,
      async execute(_id, args, signal) {
        const value = await run(['tool', tool.name, JSON.stringify(args)], signal);
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: value };
      }
    });
  }
}
'''

DSH_PLUGIN = '''import { defineTool } from '@deepseek-ai/dsh-tools';
import { run, tools } from './runner.mjs';
export const name = 'prospect';
export const inject = ['tools'];
function parameterSchema(value, required) {
  // DSH's author schema is narrower than JSON Schema. The original bounds
  // remain in tools.json and the Python bridge enforces them before any CLI action.
  const { minimum, maximum, minLength, required: requiredKeys, ...schema } = value;
  const constraints = Object.entries({ minimum, maximum, minLength }).filter(([, bound]) => bound !== undefined);
  if (constraints.length) schema.description = [schema.description, ...constraints.map(([key, bound]) => `${key}: ${bound}`)].filter(Boolean).join('; ');
  if (required) schema.required = true;
  if (schema.type === 'object') {
    schema.additionalProperties ??= true;
    if (schema.properties) schema.properties = Object.fromEntries(Object.entries(schema.properties).map(([key, item]) =>
      [key, parameterSchema(item, requiredKeys?.includes(key))]));
  }
  if (schema.items) schema.items = parameterSchema(schema.items, false);
  return schema;
}
export function apply(ctx) {
  const lifetime = new AbortController();
  ctx.effect(() => () => lifetime.abort());
  const definitions = tools.map(tool => {
    const parameters = Object.fromEntries(Object.entries(tool.inputSchema.properties).map(([key, value]) =>
      [key, parameterSchema(value, tool.inputSchema.required.includes(key))]));
    return defineTool({
      name: tool.name, description: tool.description, parameters,
      output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
      async execute(args) { return JSON.stringify(await run(['tool', tool.name, JSON.stringify(args)], lifetime.signal)); }
    });
  });
  for (const definition of definitions) ctx.tools.register(definition);
  void run(['ensure'], lifetime.signal).catch(() => console.error('Prospect unavailable; use doctor'));
}
'''


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_host(destination: Path, host: str, config: dict) -> Path:
    if host not in HOSTS:
        raise ValueError("Unknown host")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("Destination already exists; existing files are never overwritten")
    destination.mkdir(parents=True)
    write_json(destination / "runtime.json", config | {"host":host})
    write_json(destination / "tools.json", TOOLS)
    for filename in ("bridge.py", "launch.py"):
        shutil.copy2(HERE / filename, destination / filename)
    (destination / "runner.mjs").write_text(RUNNER, encoding="utf-8")
    runtime_path = destination / "runtime.json"
    launcher = destination / "launch.py"
    hook_script = destination / "session-start.ps1"
    hook_source = (
        "$ErrorActionPreference = 'Stop'\n"
        f"& {ps_literal(config['python'])} {ps_literal(str(launcher))} --config {ps_literal(str(runtime_path))} ensure\n"
        "exit $LASTEXITCODE\n")
    hook_script.write_text(hook_source, encoding="utf-8-sig")
    if os.name == "nt":
        # A direct shell command, with no execution-policy change. The exact readable
        # source is retained beside it so the hook can be reviewed before trusting.
        # Encoding avoids nested Bash/PowerShell quoting and preserves Unicode paths.
        encoded = base64.b64encode(hook_source.encode("utf-16-le")).decode("ascii")
        command = "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand " + encoded
    else:
        command = shlex.join([config["python"], str(launcher), "--config", str(runtime_path), "ensure"])
    if host in ("codex", "claude"):
        write_json(destination / f".{host}-plugin" / "plugin.json",
                   {"name": "prospect", "version": "0.1.0", "description": "Local opportunity evidence and simulation tools."})
        write_json(destination / "hooks" / "hooks.json", {"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": command, "timeout": 6}
        ]}]}})
        write_json(destination / ".mcp.json", {"mcpServers": {"prospect": {
            "command": config["python"], "args": [str(destination / "bridge.py"), "--config", str(runtime_path)]
        }}})
    elif host == "pi":
        (destination / "index.ts").write_text(PI_EXTENSION, encoding="utf-8")
        write_json(destination / "package.json", {"name": "prospect-pi", "version": "0.1.0", "type": "module", "pi": {"extensions": ["./index.ts"]}})
    else:
        (destination / "index.js").write_text(DSH_PLUGIN, encoding="utf-8")
        write_json(destination / "package.json", {"name": "dsh-prospect", "version": "0.1.0", "type": "module",
                   "main": "index.js", "files": ["index.js", "runner.mjs", "tools.json", "runtime.json", "bridge.py", "launch.py", "cordis.patch.yml"],
                   "peerDependencies": {"@deepseek-ai/dsh-tools": "*"}, "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}})
        (destination / "cordis.patch.yml").write_text("- insert:\n    - id: prospect\n      name: dsh-prospect\n", encoding="utf-8")
        write_json(destination / "COMPATIBILITY.json", {"status": "runtime_unverified", "reason": "DSH runtime is unavailable in the audited environment; no supported release range has been verified."})
    files = {}
    for path in destination.rglob("*"):
        if path.is_file():
            files[path.relative_to(destination).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    directories = sorted(p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_dir())
    write_json(destination / MARKER, {"owner": OWNER, "host": host, "directory": str(destination), "files": files, "directories": directories})
    return destination


def uninstall(destination: Path) -> None:
    """Only remove this adapter's exact, unchanged generated directory."""
    if destination.is_symlink() or getattr(destination, "is_junction", lambda: False)():
        raise ValueError("Refusing to uninstall through a symlink")
    destination = destination.resolve()
    marker = destination / MARKER
    if not marker.is_file():
        raise ValueError("No Prospect ownership marker; nothing was removed")
    record = json.loads(marker.read_text(encoding="utf-8"))
    if record.get("owner") != OWNER or record.get("directory") != str(destination):
        raise ValueError("Ownership mismatch; nothing was removed")
    expected = record.get("files")
    if not isinstance(expected, dict):
        raise ValueError("Invalid ownership record")
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    if actual != set(expected) | {MARKER}:
        raise ValueError("Files were added or removed; preserve them before uninstalling")
    directories = [p for p in destination.rglob("*") if p.is_dir()]
    if sorted(p.relative_to(destination).as_posix() for p in directories) != record.get("directories"):
        raise ValueError("Directories were added or removed; nothing was removed")
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in directories):
        raise ValueError("Refusing to uninstall a directory containing links")
    for relative, digest in expected.items():
        target = destination / relative
        if target.is_symlink() or not target.resolve().is_relative_to(destination):
            raise ValueError("Unsafe path in ownership record")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Modified file preserved: {relative}")
    # Every deletion remains under this verified owned directory; no shell command is composed.
    for relative in expected:
        (destination / relative).unlink()
    marker.unlink()
    for folder in sorted((p for p in destination.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        folder.rmdir()
    destination.rmdir()


def backup_configuration(destination: Path, output: Path) -> None:
    """Back up only unchanged generated non-secret configuration, never host settings."""
    destination, output = destination.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(destination):
        raise ValueError("Backup destination must be a new directory outside the adapter")
    record = json.loads((destination / MARKER).read_text(encoding="utf-8"))
    if record.get("owner") != OWNER or record.get("directory") != str(destination):
        raise ValueError("Ownership mismatch")
    snapshots = {}
    for relative, digest in record["files"].items():
        if not (relative.endswith(".json") or relative == "cordis.patch.yml"):
            continue
        source = destination / relative
        if source.is_symlink() or not source.resolve().is_relative_to(destination):
            raise ValueError("Unsafe configuration path")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Modified configurations require review; backup was not written")
        snapshots[relative] = content
    output.mkdir(parents=True)
    for relative, content in snapshots.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    write_json(output / "backup-metadata.json", {"source": str(destination), "host": record["host"],
                                               "scope": "unchanged generated configuration only"})


def runtime_config(python: str | None, project_root: str | None, data_dir: str | None, port: int):
    interpreter = Path(python or sys.executable).resolve()
    root = Path(project_root).resolve() if project_root else HERE.parent
    if not interpreter.is_file():
        raise ValueError("Python interpreter does not exist")
    if not (root / "prospect").is_dir():
        raise ValueError("project_root must contain the prospect package")
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return {"schema_version": 1, "python": str(interpreter), "project_root": str(root),
            "data_dir": str(Path(data_dir).resolve()) if data_dir else None, "port": port}


def build_marketplace(destination: Path, host: str, config: dict):
    destination = destination.resolve()
    if host not in ("codex", "claude"):
        raise ValueError("A marketplace is supported only for Codex and Claude")
    if destination.exists():
        raise FileExistsError("Marketplace destination exists; refusing to overwrite")
    plugin = build_host(destination / "plugins" / "prospect", host, config)
    name = "prospect-local-" + host
    if host == "codex":
        catalog = {"name": name, "interface": {"displayName": "Prospect Local"}, "plugins": [{
            "name": "prospect", "source": {"source": "local", "path": "./plugins/prospect"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"
        }]}
        catalog_path = destination / ".agents" / "plugins" / "marketplace.json"
    else:
        catalog = {"name": name, "owner": {"name": "Prospect local project"}, "plugins": [{
            "name": "prospect", "source": "./plugins/prospect", "description": "Local opportunity evidence and simulation tools."
        }]}
        catalog_path = destination / ".claude-plugin" / "marketplace.json"
    write_json(catalog_path, catalog)
    return {"marketplace": name, "root": str(destination), "catalog": str(catalog_path), "plugin": str(plugin), "registered": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "install", "marketplace"):
        command = sub.add_parser(action)
        command.add_argument("--destination", required=True)
        command.add_argument("--host", choices=("codex", "claude") if action == "marketplace" else HOSTS, required=action in ("install", "marketplace"))
        command.add_argument("--python")
        command.add_argument("--project-root")
        command.add_argument("--data-dir")
        command.add_argument("--port", type=int, default=18766)
    remove = sub.add_parser("uninstall")
    remove.add_argument("--destination", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--destination", required=True)
    backup.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        target = Path(args.destination)
        if args.action == "uninstall":
            uninstall(target)
            result = {"removed": str(target.resolve()), "host_registration_changed": False}
        elif args.action == "backup":
            backup_configuration(target, Path(args.output))
            result = {"backup": str(Path(args.output).resolve()), "host_settings_read": False}
        else:
            config = runtime_config(args.python, args.project_root, args.data_dir, args.port)
            if args.action == "marketplace":
                print(json.dumps(build_marketplace(target, args.host, config), ensure_ascii=False))
                return 0
            hosts = (args.host,) if args.host else HOSTS
            # Preflight the complete request before creating any package.
            targets = [target if args.host else target / host for host in hosts]
            if any(path.exists() for path in targets):
                raise FileExistsError("Destination exists; no overwrite is permitted")
            paths = [str(build_host(path, host, config)) for path, host in zip(targets, hosts)]
            result = {"prepared": paths, "host_registration_changed": False, "activation": "pending_host_review"}
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError) as exc:
        print(f"Prospect adapter packaging: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
