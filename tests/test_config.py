"""Configuration layering and instance-local environment regression tests."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.status_monitor.config import ROOT, load_config


class ConfigTests(unittest.TestCase):
    def test_multiple_directories_and_private_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ('a', 'b'):
                (base / name).mkdir()
            (base / '.env').write_text('SITE_NAME=private\nSITE_URL=https://example.com\n')
            (base / 'a/first.json').write_text(json.dumps({'services': [{'name': '${SITE_NAME}', 'url': '${SITE_URL}'}]}))
            (base / 'b/second.json').write_text(json.dumps({'servers': [{'name': 'Node', 'target': 'node:9100', 'cluster': 'Other'}]}))
            path = base / 'general.json'
            path.write_text(json.dumps({'resource_dirs': [str(base/'a'), str(base/'b')]}))
            with patch.dict(os.environ, {'SITE_NAME': 'process'}):
                config = load_config(path)
            self.assertEqual(config.services[0].name, 'process')
            self.assertEqual(config.servers[0].cluster, 'Other')
            self.assertEqual(config.database, ROOT / 'data/status.db')
            self.assertNotIn('SITE_URL', os.environ)
            (base / 'b/duplicate.json').write_text((base / 'a/first.json').read_text())
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                load_config(path)

    def test_missing_secret_and_invalid_auth_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'custom.json'
            path.write_text('{"database":"${MISSING_STATUS_TEST_SECRET}"}')
            with self.assertRaisesRegex(ValueError, 'Missing environment'):
                load_config(path)
            path.write_text('{"auth":{"shizunet":{"enabled":true}}}')
            with self.assertRaisesRegex(ValueError, 'Shizunet requires'):
                load_config(path)

    def test_environment_numbers_and_disabled_auth_are_typed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base/'.env').write_text('MINIMUM=15\nAUTH_ENABLED=false\n')
            path = base/'custom.json'
            path.write_text(json.dumps({'refresh':{'minimum_seconds':'${MINIMUM}'},'auth':{'shizunet':{'enabled':'${AUTH_ENABLED}'}}}))
            config = load_config(path)
            self.assertEqual(config.refresh['minimum_seconds'],15)
            self.assertIs(config.auth['shizunet']['enabled'],False)
