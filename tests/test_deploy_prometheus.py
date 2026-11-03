"""Deployment must leave the active inventory intact on validation or race errors."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from backend.status_monitor.config import ROOT
from backend.status_monitor.deploy_prometheus import REMOTE


class DeploymentTests(unittest.TestCase):
    def test_concurrent_change_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'targets.json';target.write_text('current')
            payload = {'operation':'install','target':str(target),'expected':'old','content':'[]'}
            result = subprocess.run([sys.executable,'-c',REMOTE],input=json.dumps(payload),text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(target.read_text(),'current')

    def test_invalid_target_fails_real_promtool_without_replacing_inventory(self):
        tool = ROOT/'data/tools/promtool-ali-150'
        if not tool.exists():
            self.skipTest('Matching production promtool is not installed locally')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); target=base/'targets.json';target.write_text('[]\n')
            config=base/'prometheus.yml';config.write_text('scrape_configs: []\n')
            payload={'operation':'install','target':str(target),'expected':'[]\n',
                     'content':json.dumps([{'targets':['http://invalid:9100'],'labels':{'status_id':'x'}}]),
                     'job':'nodes','promtool':str(tool),'config_file':str(config)}
            result=subprocess.run([sys.executable,'-c',REMOTE],input=json.dumps(payload),text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(target.read_text(),'[]\n')
            self.assertEqual(list(base.glob('.status-staged-*')),[])
