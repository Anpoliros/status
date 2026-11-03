"""Managed collectors own validated identities, independent of resource glob loading."""
import json
import tempfile
import unittest
from pathlib import Path
from backend.status_monitor.config import load_config
from backend.status_monitor.collectors import file_sd


class CollectorTests(unittest.TestCase):
    def test_managed_file_is_not_collected_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            machine = {'id':'ali-ecs-142','name':'142','target':'10.1.2.142:9100','cluster':'compute'}
            path = base/'ali.prometheus.json'
            path.write_text(json.dumps({'servers':[machine]}))
            general = base/'general.json'
            collector = {'type':'prometheus','id':'ali','url':'http://localhost:9090','job':'nodes','file':str(path)}
            general.write_text(json.dumps({'resource_dirs':[str(base/'resources')],'collectors':[collector]}))
            (base/'resources').mkdir()
            collector['file'] = str(base/'resources/ali.prometheus.json')
            Path(collector['file']).write_text(path.read_text())
            general.write_text(json.dumps({'resource_dirs':[str(base/'resources')],'collectors':[collector]}))
            config = load_config(general)
            self.assertEqual(config.servers,[])
            self.assertEqual(len(config.all_servers),1)
            self.assertEqual(file_sd(config.sources[0]),[{'targets':['10.1.2.142:9100'],'labels':{'status_id':'ali-ecs-142','status_enabled':'true'}}])
            Path(collector['file']).write_text(json.dumps({'servers':[machine,machine]}))
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                load_config(general)
