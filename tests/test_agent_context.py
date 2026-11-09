import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prospect.agent_context import AgentContext,caller_agent,process_started
from prospect.store import Store


class CallerTests(unittest.TestCase):
    def detect(self,tree,expected=None):
        with patch('prospect.agent_context.process_tree',return_value=tree),patch('prospect.agent_context.os.getppid',return_value=10),patch('prospect.agent_context.process_started',return_value='start'),patch.dict(os.environ,{'PROSPECT_INTERNAL_CHECK':''}):
            return caller_agent(expected)

    def test_actual_codex_ancestor_not_other_running_hosts(self):
        tree={10:{'name':'pwsh.exe','parent':20},20:{'name':'codex.exe','parent':1},30:{'name':'claude.exe','parent':1}}
        self.assertEqual(self.detect(tree)['host'],'codex')
        self.assertIsNone(self.detect({10:{'name':'pwsh.exe','parent':1},20:tree[20]}))

    def test_all_adapter_declared_node_hosts_and_no_bare_node_guess(self):
        tree={10:{'name':'python.exe','parent':20},20:{'name':'node.exe','parent':1}}
        for host in ('codex','claude','pi','deepseek'):
            with self.subTest(host=host):self.assertEqual(self.detect(tree,host)['host'],host)
        self.assertIsNone(self.detect(tree))
        self.assertIsNone(self.detect(tree,'deepseek_api'))

    def test_mismatched_host_and_parent_cycles_do_not_guess(self):
        self.assertIsNone(self.detect({10:{'name':'codex.exe','parent':1}},'claude'))
        self.assertIsNone(self.detect({10:{'name':'python.exe','parent':20},20:{'name':'pwsh.exe','parent':10}}))

    def test_background_checks_never_register_as_current_user_agent(self):
        with patch.dict(os.environ,{'PROSPECT_INTERNAL_CHECK':'1'}),patch('prospect.agent_context.process_tree') as tree:
            self.assertIsNone(caller_agent('codex'));tree.assert_not_called()

    def test_real_creation_marker_and_missing_pid(self):
        self.assertTrue(process_started(os.getpid()))
        self.assertIsNone(process_started(0));self.assertIsNone(process_started(-1))


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db')
        self.alive={10:'a',20:'b'};self.now=100
        self.context=AgentContext(self.store,probe=lambda pid:self.alive.get(pid),clock=lambda:self.now)

    def tearDown(self):self.tmp.cleanup()
    def observe(self,host='codex',pid=10,started='a',source='tool'):
        return self.context.observe({'host':host,'pid':pid,'started':started,'source':source})

    def test_preferences_and_installed_cli_do_not_prove_current_agent(self):
        self.store.set_setting('agent_models',{'default_host':'codex'})
        self.assertEqual(self.context.view()['status'],'unavailable')
        with self.assertRaises(ValueError):self.context.resolve()

    def test_latest_live_interaction_switches_host_and_survives_restart(self):
        self.observe();self.now+=1;self.observe('claude',20,'b','startup')
        self.assertEqual(self.context.resolve(),'claude')
        restored=AgentContext(self.store,probe=lambda pid:self.alive.get(pid))
        self.assertEqual(restored.resolve(),'claude')
        self.now+=1;self.observe('codex')
        self.assertEqual(self.context.resolve(),'codex')
        self.assertEqual({h['id'] for h in self.context.view()['running_hosts']},{'codex','claude'})

    def test_exit_and_reused_pid_invalidate_host_without_model_calls(self):
        self.observe();self.alive[10]='new-process'
        self.assertEqual(self.context.view()['status'],'unavailable')
        with self.assertRaises(ValueError):self.observe()

    def test_exactly_simultaneous_different_hosts_stay_ambiguous(self):
        self.observe();self.observe('pi',20,'b')
        self.assertEqual(self.context.view()['status'],'ambiguous')
        with self.assertRaises(ValueError):self.context.resolve()

    def test_public_view_hides_process_identity_and_invalid_observations_rejected(self):
        public=self.observe();self.assertNotIn('pid',public);self.assertNotIn('started',public)
        for change in ({'host':'deepseek_api'},{'source':'browser'},{'pid':True},{'started':None}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.context.observe({'host':'codex','pid':10,'started':'a','source':'tool'}|change)
