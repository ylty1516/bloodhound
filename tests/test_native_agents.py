import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from prospect import native_agents


class NativeAgentTests(unittest.TestCase):
    def setUp(self):
        native_agents._cache.update(until=0,info=None);native_agents._claude_cache.update(until=0,info=None);native_agents._profiles.clear()
    def tearDown(self):
        native_agents._cache.update(until=0,info=None);native_agents._claude_cache.update(until=0,info=None);native_agents._profiles.clear()

    def test_newer_desktop_binary_wins_and_ui_reads_use_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop=Path(tmp)/'desktop.exe';standalone=Path(tmp)/'old.exe';desktop.touch();standalone.touch()
            def version(path):return ((0,167,0),'codex-cli 0.167.0') if path==desktop else ((0,154,0),'codex-cli 0.154.0')
            with patch.dict(os.environ,{'LOCALAPPDATA':tmp}),patch.object(native_agents,'_desktop_binary',return_value=desktop) as lookup,patch('prospect.native_agents.shutil.which',return_value=str(standalone)),patch.object(native_agents,'_version',side_effect=version):
                self.assertEqual(native_agents.find_native('codex'),str(desktop))
                self.assertEqual(native_agents.find_native('codex'),str(desktop));lookup.assert_called_once()

    def test_newer_standalone_still_wins_over_older_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop=Path(tmp)/'desktop.exe';standalone=Path(tmp)/'new.exe';desktop.touch();standalone.touch()
            def version(path):return ((0,167,0),'0.167.0') if path==desktop else ((0,168,0),'0.168.0')
            with patch.dict(os.environ,{'LOCALAPPDATA':tmp}),patch.object(native_agents,'_desktop_binary',return_value=desktop),patch('prospect.native_agents.shutil.which',return_value=str(standalone)),patch.object(native_agents,'_version',side_effect=version):
                self.assertEqual(native_agents.find_native('codex'),str(standalone))

    def test_proxy_is_inherited_without_overriding_explicit_settings_or_injecting_keys(self):
        with patch.dict(os.environ,{'HTTPS_PROXY':'http://explicit.example:8000','OPENAI_API_KEY':'secret'},clear=True),patch('prospect.native_agents.urllib.request.getproxies_registry',return_value={'http':'http://127.0.0.1:7890','https':'http://127.0.0.1:7890'}):
            value=native_agents.agent_environment()
            self.assertEqual(value['HTTPS_PROXY'],'http://explicit.example:8000');self.assertNotIn('OPENAI_API_KEY',value)
            if os.name=='nt':self.assertEqual(value['HTTP_PROXY'],'http://127.0.0.1:7890')
            self.assertEqual(value['PROSPECT_INTERNAL_CHECK'],'1')

    def test_claude_version_selection_does_not_lock_to_old_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);fixed=home/'.local/bin/claude.exe';fixed.parent.mkdir(parents=True);fixed.touch()
            newer=home/'new-claude.exe';newer.touch()
            def version(path):return ((2,1,218),'2.1.218') if path==newer else ((2,1,10),'2.1.10')
            with patch('prospect.native_agents.Path.home',return_value=home),patch('prospect.native_agents.shutil.which',return_value=str(newer)),patch.object(native_agents,'_version',side_effect=version):
                self.assertEqual(native_agents.claude_info()['path'],str(newer))

    def test_help_preflight_checks_capabilities_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'claude.exe';binary.touch();info={'path':str(binary),'source':'standalone','version':'2.1','version_tuple':(2,1,0)}
            with patch.object(native_agents,'claude_info',return_value=info),patch('prospect.native_agents.subprocess.run',return_value=types.SimpleNamespace(returncode=0,stdout='--output-format --tools')) as command:
                profile=native_agents.native_profile('claude')
                self.assertIn('--json-schema',profile['missing_flags']);self.assertEqual(command.call_args.args[0],[str(binary),'--help'])
                native_agents.native_profile('claude');command.assert_called_once()

    def test_cold_status_presence_never_starts_metadata_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);codex=home/'Programs/OpenAI/Codex/bin/codex.exe';codex.parent.mkdir(parents=True);codex.touch()
            claude=home/'.local/bin/claude.exe';claude.parent.mkdir(parents=True);claude.touch()
            with patch.dict(os.environ,{'LOCALAPPDATA':tmp}),patch('prospect.native_agents.Path.home',return_value=home),patch('prospect.native_agents.subprocess.run') as process:
                self.assertTrue(native_agents.native_present('codex'));self.assertTrue(native_agents.native_present('claude'))
                self.assertFalse(native_agents.native_present('pi'));process.assert_not_called()
