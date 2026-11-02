"""Independent Shizunet OIDC and emergency local login with server-side sessions."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import urlencode

import jwt
import requests

from .config import AppConfig

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, subject TEXT NOT NULL, name TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oidc_flows(token TEXT PRIMARY KEY, state TEXT NOT NULL, nonce TEXT NOT NULL, verifier TEXT NOT NULL, expires REAL NOT NULL);
'''


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return 'scrypt$' + salt.hex() + '$' + result.hex()


def verify_password(password, encoded):
    try:
        algorithm, salt, expected = encoded.split('$')
        if algorithm != 'scrypt' or len(password) > 1024:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


class Auth:
    def __init__(self, config: AppConfig):
        self.config = config
        self.oidc = config.auth.get('shizunet', {})
        self.pseudo = config.auth.get('pseudo_user', {})
        self.enabled = bool(self.oidc.get('enabled'))
        base = self.oidc.get('base_url') or config.auth.get('base_url', '')
        self.secure = base.startswith('https://')
        self.cookie_name = 'status_' + digest(str(config.database))[:10]
        self.discovery = None
        self.discovery_until = 0
        self.jwks = None
        self.lock = threading.Lock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def connect(self):
        self.config.state_database.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.config.state_database, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    def cookie(self, name, value, seconds):
        return f'{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={seconds}' + ('; Secure' if self.secure else '')

    def read_cookie(self, headers, name=None):
        try:
            cookies = SimpleCookie(headers.get('Cookie', ''))
            item = cookies.get(name or self.cookie_name)
            return item.value if item else ''
        except Exception:
            return ''

    def user(self, headers):
        token = self.read_cookie(headers)
        if not token:
            return None
        with self.connect() as conn:
            row = conn.execute('SELECT subject,name FROM sessions WHERE token=? AND expires>?', (digest(token),time.time())).fetchone()
        return dict(row) if row else None

    def new_session(self, subject, name):
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            conn.execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest(token),subject,name,time.time()+3*86400))
        return self.cookie(self.cookie_name, token, 3*86400)

    def logout(self, headers):
        with self.connect() as conn:
            conn.execute('DELETE FROM sessions WHERE token=?', (digest(self.read_cookie(headers)),))
        return self.cookie(self.cookie_name, '', 0)

    def local_login(self, username, password):
        valid = verify_password(password, self.pseudo.get('password_hash', ''))
        if not self.pseudo.get('enabled') or not hmac.compare_digest(username, self.pseudo.get('username','')) or not valid:
            raise ValueError('Invalid username or password')
        return self.new_session('local:pseudo', username)

    def metadata(self):
        with self.lock:
            if self.discovery_until > time.monotonic():
                return self.discovery
            issuer = self.oidc['issuer'].rstrip('/')
            response = requests.get(issuer+'/.well-known/openid-configuration', timeout=8)
            response.raise_for_status()
            metadata = response.json()
            if metadata.get('issuer') != issuer:
                raise ValueError('OIDC issuer mismatch')
            for key in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
                if not metadata.get(key, '').startswith('https://') and not issuer.startswith(('http://localhost:', 'http://127.0.0.1:')):
                    raise ValueError('OIDC requires HTTPS endpoints')
            self.discovery = metadata
            self.jwks = jwt.PyJWKClient(metadata['jwks_uri'], timeout=8)
            self.discovery_until = time.monotonic()+300
            return metadata

    def start(self):
        if not self.enabled:
            raise ValueError('Shizunet is disabled')
        metadata = self.metadata()
        token, state, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.connect() as conn:
            conn.execute('DELETE FROM oidc_flows WHERE expires<=?', (time.time(),))
            conn.execute('INSERT INTO oidc_flows VALUES (?,?,?,?,?)', (digest(token),state,nonce,verifier,time.time()+600))
        query = urlencode({'client_id':self.oidc['client_id'], 'redirect_uri':self.callback,
                           'response_type':'code', 'scope':'openid profile', 'state':state,
                           'nonce':nonce, 'code_challenge':challenge, 'code_challenge_method':'S256'})
        return metadata['authorization_endpoint']+'?'+query, self.cookie(self.cookie_name+'_flow',token,600)

    @property
    def callback(self):
        return self.oidc['base_url'].rstrip('/')+'/auth/callback'

    def finish(self, headers, query):
        if not self.enabled:
            raise ValueError('Shizunet is disabled')
        token = digest(self.read_cookie(headers,self.cookie_name+'_flow'))
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            flow = conn.execute('SELECT * FROM oidc_flows WHERE token=?', (token,)).fetchone()
            conn.execute('DELETE FROM oidc_flows WHERE token=?', (token,))
        if not flow or flow['expires']<time.time() or not hmac.compare_digest(flow['state'],query.get('state',[''])[0]):
            raise ValueError('Invalid or expired login flow')
        metadata = self.metadata()
        response = requests.post(metadata['token_endpoint'], auth=(self.oidc['client_id'],self.oidc['client_secret']),
            data={'grant_type':'authorization_code','code':query.get('code',[''])[0],
                  'redirect_uri':self.callback,'code_verifier':flow['verifier']}, timeout=8)
        response.raise_for_status()
        encoded = response.json()['id_token']
        key = self.jwks.get_signing_key_from_jwt(encoded)
        claims = jwt.decode(encoded,key.key,algorithms=['RS256'],audience=self.oidc['client_id'],
                            issuer=metadata['issuer'],options={'require':['exp','iat','iss','aud','sub','nonce']})
        if not hmac.compare_digest(claims['nonce'],flow['nonce']):
            raise ValueError('OIDC nonce mismatch')
        if isinstance(claims['aud'],list) and len(claims['aud'])>1 and claims.get('azp') != self.oidc['client_id']:
            raise ValueError('OIDC authorized party mismatch')
        return self.new_session(metadata['issuer']+'|'+claims['sub'],claims.get('name') or claims['sub'])


if __name__ == '__main__':
    import getpass
    password = getpass.getpass('Password: ')
    if not password or password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords must match and cannot be empty')
    print(password_hash(password))
