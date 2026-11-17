"""HTTP integration checks for snapshot isolation, local login and bounded control."""
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

import requests
from backend.status_monitor.api import RateLimiter, StatusHandler
from backend.status_monitor.auth import Auth, password_hash
from backend.status_monitor.config import load_config
from backend.status_monitor.scheduler import init_control
from backend.status_monitor.snapshots import SnapshotStore, atomic_json


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.config = replace(load_config('configs/general.example.json'),instance_name='test-instance',database=base/'test.db',status_json=base/'snapshots/current.json',auth={
            'shizunet':{'enabled':True}, 'pseudo_user':{'enabled':True,'username':'recovery','password_hash':password_hash('secret')}})
        init_control(self.config)
        atomic_json(self.config.status_json,{'generated_at':'now','servers':[{'name':'private-node'}],'services':[]})
        atomic_json(self.config.status_json.parent/'services-60d.json',{'items':[]})
        class Handler(StatusHandler):
            config = self.config
            auth = Auth(self.config)
            snapshots = SnapshotStore()
            limiter = RateLimiter()
            static_dir = base
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = requests.Session()

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self,path,payload):
        return self.client.post(self.url+path,json=payload,headers={'Origin':self.url},timeout=3)

    def test_public_history_identifies_serving_instance_without_changing_snapshot(self):
        payload = self.client.get(self.url+'/history/services?range=60d').json()
        self.assertEqual(payload['instance'], {'name': 'test-instance'})
        snapshot = json.loads((self.config.status_json.parent/'services-60d.json').read_text())
        self.assertNotIn('instance', snapshot)

    def test_anonymous_cannot_read_private_or_fallback_snapshots(self):
        for path in ['/status','/check','/history/servers']:
            self.assertEqual(self.client.get(self.url+path).status_code,401)
            self.assertEqual(self.client.head(self.url+path).status_code,401)
        for path in ['/status.json','/status-pusr.json','/data/status.db','/configs/.env']:
            self.assertEqual(self.client.get(self.url+path).status_code,404)
        self.assertEqual(self.client.get(self.url+'/history/services').status_code,200)
        self.assertEqual(self.client.get(self.url+'/history/services?hours=999999').status_code,400)

    def test_recovery_login_control_and_logout(self):
        self.assertEqual(self.post('/auth/local',{'username':'recovery','password':'wrong'}).status_code,401)
        self.assertEqual(self.post('/auth/local',{'username':'recovery','password':'secret'}).status_code,200)
        self.assertEqual(self.client.get(self.url+'/status').status_code,200)
        response = self.post('/api/control',{'page':'a'*20,'action':'connect','seconds':5})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['accepted_seconds'],10)
        self.assertEqual(self.post('/auth/logout',{}).status_code,200)
        self.assertEqual(self.client.get(self.url+'/status').status_code,401)

    def test_mutations_require_same_origin(self):
        response = self.client.post(self.url+'/auth/local',json={'username':'recovery','password':'secret'},headers={'Origin':'https://other.example'})
        self.assertEqual(response.status_code,403)


    def test_local_only_instance_requires_login_without_shizunet(self):
        self.server.RequestHandlerClass.auth = Auth(replace(self.config,auth={
            'shizunet':{'enabled':False},
            'pseudo_user':self.config.auth['pseudo_user']}))
        session = self.client.get(self.url+'/api/session').json()
        self.assertFalse(session['shizunet'])
        self.assertTrue(session['pseudo_user'])
        self.assertFalse(session['full_access'])
        self.assertEqual(self.client.get(self.url+'/status').status_code,401)
        self.assertEqual(self.post('/api/control',{'page':'b'*20,'action':'connect','seconds':60}).status_code,401)
        self.assertEqual(self.client.get(self.url+'/history/services').status_code,200)
        self.assertEqual(self.post('/auth/local',{'username':'recovery','password':'secret'}).status_code,200)
        self.assertEqual(self.client.get(self.url+'/status').status_code,200)
        self.assertEqual(self.post('/api/control',{'page':'b'*20,'action':'connect','seconds':60}).status_code,200)
        self.assertEqual(self.post('/auth/logout',{}).status_code,200)
        self.assertEqual(self.client.get(self.url+'/status').status_code,401)
