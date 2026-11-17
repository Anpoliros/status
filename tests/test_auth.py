"""Local recovery sessions remain usable without the identity provider."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from backend.status_monitor.auth import Auth, password_hash, verify_password
import test_status


class AuthTests(unittest.TestCase):
    def test_local_login_and_logout_are_independent_of_oidc(self):
        fixture = test_status.StatusTests()
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


class SigningKeyTransportTests(unittest.TestCase):
    def test_keys_use_requests_and_populate_cache(self):
        from unittest.mock import patch, Mock
        from backend.status_monitor.auth import RequestsJWKClient
        payload = {'keys': [{'kty': 'oct', 'k': 'c2VjcmV0', 'kid': 'test'}]}
        response = Mock()
        response.json.return_value = payload
        with patch('backend.status_monitor.auth.requests.get', return_value=response) as get:
            client = RequestsJWKClient('https://issuer.example/jwks')
            self.assertEqual(client.fetch_data(), payload)
            self.assertEqual(client.jwk_set_cache.get().keys[0].key_id, 'test')
            get.assert_called_once_with('https://issuer.example/jwks', headers={'Accept': 'application/json'}, timeout=30)
            response.raise_for_status.assert_called_once()

    def test_network_failure_is_closed_and_clears_cache(self):
        from unittest.mock import patch
        import requests
        import jwt
        from backend.status_monitor.auth import RequestsJWKClient
        client = RequestsJWKClient('https://issuer.example/jwks')
        client.jwk_set_cache.put({'keys': [{'kty': 'oct', 'k': 'c2VjcmV0'}]})
        with patch('backend.status_monitor.auth.requests.get', side_effect=requests.ConnectionError()):
            with self.assertRaises(jwt.PyJWKClientConnectionError):
                client.fetch_data()
        self.assertIsNone(client.jwk_set_cache.get())
