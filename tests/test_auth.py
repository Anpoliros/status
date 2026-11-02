"""Local recovery sessions remain usable without the identity provider."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from backend.status_monitor.auth import Auth, password_hash, verify_password
from test_status import StatusTests


class AuthTests(unittest.TestCase):
    def test_local_login_and_logout_are_independent_of_oidc(self):
        fixture = StatusTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as temp:
            config = replace(fixture.config,database=Path(temp)/'test.db',auth={
                'shizunet':{'enabled':True},'pseudo_user':{'enabled':True,'username':'recovery','password_hash':password_hash('secret')}})
            auth = Auth(config)
            with self.assertRaises(ValueError):
                auth.local_login('recovery','wrong')
            cookie = auth.local_login('recovery','secret')
            headers = {'Cookie':cookie.split(';')[0]}
            self.assertEqual(auth.user(headers)['subject'],'local:pseudo')
            auth.logout(headers)
            self.assertIsNone(auth.user(headers))
        fixture.tearDown()

    def test_malformed_hash_is_rejected(self):
        self.assertFalse(verify_password('test','scrypt$broken$broken'))
