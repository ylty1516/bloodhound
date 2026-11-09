import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prospect.service import data_directory


class SharedRuntimeLocationTests(unittest.TestCase):
    def test_packaged_and_cli_hosts_use_same_canonical_reference(self):
        with tempfile.TemporaryDirectory() as t:
            project=Path(t);shared=project/'shared';shared.mkdir()
            (project/'runtime-location.json').write_text(json.dumps({'schema_version':1,'data_directory':str(shared)}),'utf-8')
            with patch('prospect.service.ROOT',project),patch.dict(os.environ,{'PROSPECT_DATA':'','LOCALAPPDATA':str(project/'different-app-profile')}):
                self.assertEqual(data_directory(),shared.resolve())

    def test_explicit_directory_always_overrides_machine_reference(self):
        with tempfile.TemporaryDirectory() as t:
            explicit=Path(t)/'explicit'
            with patch.dict(os.environ,{'PROSPECT_DATA':str(explicit)}):self.assertEqual(data_directory(),explicit)


if __name__=='__main__':unittest.main()
