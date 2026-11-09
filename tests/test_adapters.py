import io
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from adapters.bridge import MCPServer, TOOLS, call_tool, cli_argv, read_config
from adapters.manage import HERE, HOSTS, backup_configuration, build_host, build_marketplace, runtime_config, uninstall


FAKE_CLI = '''import json, os, sys
args = sys.argv[1:]
if 'tool' in args:
    index = args.index('tool')
    name, payload = args[index+1:index+3]
    if name == 'prospect_scan':
        print('controlled CLI failure', file=sys.stderr)
        raise SystemExit(7)
    print(json.dumps({'name': name, 'arguments': json.loads(payload), 'cwd': os.getcwd()}))
else:
    print(json.dumps({'ready': True}))
'''


class AdapterTests(unittest.TestCase):
    def setUp(self):
        # The desktop sandbox's redirected Windows TEMP may not permit child files.
        # Keep isolated fixtures inside this adapter's explicitly writable workspace.
        fixture_root = (HERE / ".test-tmp").resolve()
        self.assertTrue(fixture_root.is_relative_to(HERE))
        fixture_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="Prospect adapter's 中文 ", dir=fixture_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project with spaces"
        package = self.project / "prospect"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(FAKE_CLI, encoding="utf-8")
        self.config = runtime_config(sys.executable, str(self.project), str(self.root / "state"), 19876)
        self.config_path = self.root / "runtime.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def server(self):
        server = MCPServer(lambda name, args: call_tool(self.config, name, args))
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        return server

    def test_cli_uses_argument_list_and_configured_checkout(self):
        argv = cli_argv(self.config, "tool", "prospect_assess", '{"candidate_id":"two words 中文"}')
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[-1], '{"candidate_id":"two words 中文"}')
        result = call_tool(self.config, "prospect_assess", {"candidate_id": "two words 中文"})
        self.assertEqual(result["arguments"]["candidate_id"], "two words 中文")
        self.assertEqual(Path(result["cwd"]), self.project)

    def test_mcp_initialize_and_list_without_cli_call(self):
        def forbidden(*_):
            self.fail("Initialization and discovery must not call product code")
        server = MCPServer(forbidden)
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "future"}})
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(response["result"]["tools"]), len(TOOLS))
        self.assertTrue({"prospect_check_pending", "prospect_check_claim", "prospect_check_complete"}.issubset({tool["name"] for tool in response["result"]["tools"]}))
        self.assertEqual({tool["name"] for tool in TOOLS}, {tool["name"] for tool in response["result"]["tools"]})

    def test_mcp_success_and_real_cli_error(self):
        server = self.server()
        success = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "prospect_status", "arguments": {}}})
        self.assertFalse(success["result"]["isError"])
        failure = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "prospect_scan", "arguments": {}}})
        self.assertTrue(failure["result"]["isError"])
        self.assertIn("controlled CLI failure", failure["result"]["content"][0]["text"])
        self.assertNotIn("structuredContent", failure["result"])

    def test_invalid_arguments_do_not_reach_cli(self):
        server = self.server()
        for params in ({"name": "run_arbitrary_command"}, {"name": "prospect_status", "arguments": {"execute": True}},
                       {"name": "prospect_simulate", "arguments": {}}, {"name": "prospect_simulate", "arguments": {"candidate_id": 1}}):
            with self.subTest(params=params):
                response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params})
                self.assertEqual(response["error"]["code"], -32602)

    def test_candidate_pagination_validation(self):
        server = self.server()
        for args in ({"offset": -1}, {"limit": 0}, {"limit": 51}, {"offset": True}, {"limit": 1.2}):
            result = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "prospect_candidates", "arguments": args}})
            self.assertEqual(result["error"]["code"], -32602)
        result = call_tool(self.config, "prospect_candidates", {"offset": 20, "limit": 10})
        self.assertEqual(result["arguments"], {"offset": 20, "limit": 10})

    def test_marketplaces_resolve_contained_plugins(self):
        for host in ("codex", "claude"):
            record = build_marketplace(self.root / (host + "-marketplace"), host, self.config)
            catalog = json.loads(Path(record["catalog"]).read_text(encoding="utf-8"))
            source = catalog["plugins"][0]["source"]
            relative = source["path"] if isinstance(source, dict) else source
            resolved = (Path(record["root"]) / relative).resolve()
            self.assertTrue(resolved.is_relative_to(Path(record["root"])))
            self.assertEqual(resolved, Path(record["plugin"]))

    def test_notifications_and_invalid_json(self):
        server = self.server()
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        output = io.StringIO()
        server.serve(io.StringIO('bad json\n{"jsonrpc":"2.0","id":7,"method":"ping"}\n'), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"], {})

    def test_stdio_process_protocol_roundtrip(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "prospect_status"}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "prospect_scan"}},
        ]
        completed = subprocess.run([sys.executable, str(HERE / "bridge.py"), "--config", str(self.config_path)],
            input="".join(json.dumps(request) + "\n" for request in requests), capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3, 4])
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertTrue(responses[3]["result"]["isError"])

    def test_ensure_emits_no_context(self):
        completed = subprocess.run([sys.executable, str(HERE / "launch.py"), "--config", str(self.config_path), "ensure"], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")

    def test_all_four_packages_and_ownership(self):
        for host in HOSTS:
            with self.subTest(host=host):
                path = build_host(self.root / host, host, self.config)
                self.assertEqual(read_config(path / "runtime.json"), self.config | {"host":host})
                if host in ("codex", "claude"):
                    settings = json.loads((path / ".mcp.json").read_text(encoding="utf-8"))
                    self.assertEqual(settings["mcpServers"]["prospect"]["command"], sys.executable)
                if host == "deepseek":
                    self.assertEqual(json.loads((path / "COMPATIBILITY.json").read_text())["status"], "runtime_unverified")
                uninstall(path)
                self.assertFalse(path.exists())

    def test_installer_never_overwrites_and_uninstaller_preserves_edits(self):
        path = build_host(self.root / "codex", "codex", self.config)
        with self.assertRaises(FileExistsError):
            build_host(path, "codex", self.config)
        before = (path / "runtime.json").read_bytes()
        (path / "runtime.json").write_text("user edit", encoding="utf-8")
        with self.assertRaises(ValueError):
            uninstall(path)
        self.assertEqual((path / "runtime.json").read_text(), "user edit")
        (path / "runtime.json").write_bytes(before)
        (path / "keep.txt").write_text("unrelated user file")
        with self.assertRaises(ValueError):
            uninstall(path)
        self.assertTrue((path / "keep.txt").exists())

    def test_configuration_backup_never_reads_host_settings(self):
        path = build_host(self.root / "codex", "codex", self.config)
        backup = self.root / "configuration-backup"
        backup_configuration(path, backup)
        self.assertEqual((path / "runtime.json").read_bytes(), (backup / "runtime.json").read_bytes())
        self.assertFalse((backup / "bridge.py").exists())
        with self.assertRaises(ValueError):
            backup_configuration(path, backup)
        (path / "runtime.json").write_text('{"secret":"user data"}')
        with self.assertRaises(ValueError):
            backup_configuration(path, self.root / "refused-backup")
        self.assertFalse((self.root / "refused-backup").exists())

    @unittest.skipUnless(shutil.which("node"), "Node is required for syntax verification")
    def test_generated_javascript_syntax(self):
        for host in ("pi", "deepseek"):
            path = build_host(self.root / host, host, self.config)
            for filename in ("runner.mjs", "index.ts" if host == "pi" else "index.js"):
                completed = subprocess.run(["node", "--input-type=module", "--check"],
                    input=(path / filename).read_text(encoding="utf-8"), capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    @unittest.skipUnless(shutil.which("node") and (HERE / ".dsh-sdk-qa/node_modules/@deepseek-ai/dsh-tools/lib/index.js").is_file(),
                         "Optional fixed-version DSH SDK QA dependencies are not installed")
    def test_deepseek_real_sdk_loads_schemas_and_disposes_tools(self):
        sdk_root = HERE / ".dsh-sdk-qa"
        with tempfile.TemporaryDirectory(prefix="regression-", dir=sdk_root) as temporary:
            plugin = build_host(Path(temporary) / "plugin", "deepseek", self.config)
            module_url = lambda name: (sdk_root / "node_modules/@deepseek-ai" / name / "lib/index.js").as_uri()
            script = f'''
import assert from 'node:assert/strict';
import {{ Context }} from {json.dumps(module_url('cordis'))};
import SystemPrompt from {json.dumps(module_url('dsh-system-prompt'))};
import ToolRegistry from {json.dumps(module_url('dsh-tools'))};
import * as plugin from {json.dumps((plugin / 'index.js').as_uri())};
globalThis.fetch = async () => {{ throw new Error('No network in SDK regression'); }};
const ctx = new Context();
try {{
  await ctx.plugin(SystemPrompt);
  await ctx.plugin(ToolRegistry, {{mode: 'native'}});
  const owner = await ctx.plugin(plugin);
  const names = {json.dumps([tool['name'] for tool in TOOLS])};
  assert.equal(names.filter(name => ctx.tools.get(name)).length, names.length);
  assert.ok(ctx.tools.get('prospect_check_claim'));
  assert.ok(ctx.tools.get('prospect_check_complete'));
  const call = (name, args) => ctx.tools.execute({{callId: 'qa', name, arguments: args, signal: new AbortController().signal}});
  assert.equal((await call('prospect_status', {{}})).isError, false);
  assert.equal((await call('prospect_candidates', {{limit: 0}})).isError, true);
  assert.equal((await call('prospect_assess', {{candidate_id: ''}})).isError, true);
  await owner.dispose();
  assert.equal(names.filter(name => ctx.tools.get(name)).length, 0);
  assert.equal((await call('prospect_status', {{}})).isError, true);
}} finally {{ await ctx.fiber.dispose(); }}
'''
            completed = subprocess.run(["node", "--input-type=module", "-"], input=script,
                capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
    def test_windows_hook_handles_spaces_apostrophes_and_unicode(self):
        path = build_host(self.root / "hook's 中文 folder", "claude", self.config)
        hooks = json.loads((path / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        decoded = base64.b64decode(command.split()[-1]).decode("utf-16-le")
        self.assertEqual(decoded, (path / "session-start.ps1").read_text(encoding="utf-8-sig"))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "")
        uninstall(path)


if __name__ == "__main__":
    unittest.main()
