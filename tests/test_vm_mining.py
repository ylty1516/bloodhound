import json
from pathlib import Path
import tempfile
import time
import unittest
import os
from unittest.mock import patch
from prospect.vm_mining import prepared,LINUX_SHA,LINUX_EXE_SHA,BASE_SHA,DRIVER
from prospect.execution_drivers import driver_info,controller_env


class VmAdmissionTests(unittest.TestCase):
    def test_image_and_miner_pins_and_actual_boot_network_probe_are_required(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'mining-vm';root.mkdir()
            self.assertFalse(prepared(t))
            data={'owner':'prospect-mining-vm-v1','linux_miner_sha256':LINUX_SHA,'base_sha256':BASE_SHA,'linux_executable_sha256':LINUX_EXE_SHA}
            (root/'preparation.json').write_text(json.dumps(data),'utf-8')
            self.assertTrue(prepared(t,require_boot=False));self.assertFalse(prepared(t))
            boot={'verified':True,'network_probe_passed':True,'epoch':time.time()}
            (root/'boot-verification.json').write_text(json.dumps(boot),'utf-8');self.assertTrue(prepared(t))
            for change in [{'verified':False},{'network_probe_passed':False},{'epoch':time.time()-86401}]:
                (root/'boot-verification.json').write_text(json.dumps(boot|change),'utf-8');self.assertFalse(prepared(t))
            (root/'boot-verification.json').write_text(json.dumps(boot),'utf-8')
            (root/'preparation.json').write_text(json.dumps(data|{'base_sha256':'0'*64}),'utf-8');self.assertFalse(prepared(t))

    def test_vm_is_an_explicit_mainnet_cpu_driver(self):
        value=driver_info(DRIVER)
        self.assertEqual(value['network'],'mainnet');self.assertEqual(value['category'],'pow')
        self.assertIn('隔离',value['name'])

    def test_controller_preserves_windows_context_without_credentials(self):
        with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-secret','BINANCE_SECRET':'fixture-secret','USERNAME':'fixture-user'}):
            env=controller_env(Path(t))
            self.assertNotIn('fixture-secret',json.dumps(env));self.assertEqual(env['USERNAME'],'fixture-user')
            self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('BINANCE_SECRET',env)


if __name__=='__main__':unittest.main()
