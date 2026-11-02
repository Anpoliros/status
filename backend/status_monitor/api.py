"""Serve cached snapshots, authenticated sessions and bounded refresh requests."""
from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .auth import Auth
from .config import load_config
from .snapshots import SnapshotStore


class RateLimiter:
    """Bound request rate and the number of remembered clients."""
    def __init__(self):
        self.clients = {}
        self.lock = threading.Lock()

    def allow(self, key, limit):
        now = time.monotonic()
        with self.lock:
            if len(self.clients) >= 4096:
                self.clients = {k:v for k,v in self.clients.items() if v and v[-1]>now-60}
                if key not in self.clients and len(self.clients)>=4096:
                    return False
            queue = self.clients.setdefault(key,deque())
            while queue and queue[0]<=now-60:
                queue.popleft()
            if len(queue)>=limit:
                return False
            queue.append(now)
            return True


class StatusHandler(BaseHTTPRequestHandler):
    # ============================== HTTP boundary ==============================
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self.route_get()
        except FileNotFoundError:
            self._json({'error':'Initial collection is still running'},503)
        except (ValueError, KeyError):
            self._json({'error':'Invalid request or login flow'},400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            print(f'GET {urlparse(self.path).path}: {type(error).__name__}')
            self._json({'error':'Service temporarily unavailable'},503)

    def identity(self):
        user = self.auth.user(self.headers)
        address = self.client_address[0]
        if address in ('127.0.0.1','::1'):
            address = self.headers.get('X-Forwarded-For',address).split(',')[-1].strip()
        return user, user['subject'] if user else address

    def route_get(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if path == '/healthz':
            ready = self.config.status_json.exists()
            self._json({'ok':ready},200 if ready else 503)
            return
        if not self.limiter.allow(('read',self.client_address[0]),600):
            self._json({'error':'Too many requests'},429,{'Retry-After':'60'})
            return
        if path == '/auth/start':
            if self.command == 'HEAD':
                self._json({},405)
                return
            try:
                location, cookie = self.auth.start()
                self.redirect(location, cookie)
            except Exception:
                self.redirect('/?login_error=unavailable')
            return
        if path == '/auth/callback':
            try:
                cookie = self.auth.finish(self.headers,query)
                self.redirect('/',cookie)
            except Exception:
                self.redirect('/?login_error=failed')
            return
        user, identity = self.identity()
        if not self.limiter.allow(('user',identity),240):
            self._json({'error':'Too many requests'},429,{'Retry-After':'60'})
            return
        full = not self.auth.enabled or user is not None
        if path == '/api/session':
            self._json({'user':user,'full_access':full,'shizunet':self.auth.enabled,
                        'pseudo_user':bool(self.auth.pseudo.get('enabled')), 'refresh':self.config.refresh})
            return
        public_history = path == '/history/services'
        if path in ('/status','/check','/history/servers') and not full:
            self._json({'error':'Login required'},401)
            return
        if path in ('/status','/check'):
            payload = self.snapshots.read(self.config.status_json)
            if path == '/check':
                unavailable = [x['name'] for x in payload['services'] if x['status']!='up']
                unavailable += [x['name'] for x in payload['servers'] if x['status']=='critical']
                payload = {'overall_status':'healthy' if not unavailable else 'alert' if len(unavailable)>=3 else 'attention','unavailable':unavailable}
            self._json(payload)
        elif public_history or path == '/history/servers':
            period = query.get('range',['60d'])[0]
            if 'hours' in query:
                period = {'48':'48h','1440':'60d'}.get(query['hours'][0])
            if period not in ('48h','60d'):
                self._json({'error':'Supported history ranges: 48h, 60d'},400)
                return
            kind = 'services' if public_history else 'servers'
            self._json(self.snapshots.read(self.config.status_json.parent/f'{kind}-{period}.json'))
        elif path.startswith(('/api/','/auth/','/history/')) or path.endswith('.json'):
            self._json({'error':'Not found'},404)
        else:
            self._static(path)

    def do_POST(self):
        try:
            # Same-origin JSON requests protect login, logout and scheduling mutations.
            origin = self.headers.get('Origin','')
            if not origin or urlparse(origin).netloc != self.headers.get('Host'):
                self._json({'error':'Origin mismatch'},403)
                return
            length = int(self.headers.get('Content-Length','0'))
            if length<1 or length>8192 or self.headers.get_content_type()!='application/json':
                self._json({'error':'Expected a small JSON request'},400)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):
                raise ValueError('Expected object')
            path = urlparse(self.path).path
            user, identity = self.identity()
            if not self.limiter.allow(('write',identity),90):
                self._json({'error':'Too many requests'},429,{'Retry-After':'60'})
                return
            if path == '/auth/local':
                if not self.limiter.allow(('login',identity),8) or not self.limiter.allow(('all-login',),60):
                    self._json({'error':'Too many login attempts'},429,{'Retry-After':'60'})
                    return
                try:
                    cookie = self.auth.local_login(str(payload.get('username','')),str(payload.get('password','')))
                    self._json({'ok':True},headers={'Set-Cookie':cookie})
                except ValueError:
                    self._json({'error':'Invalid username or password'},401)
            elif path == '/auth/logout':
                self._json({'ok':True},headers={'Set-Cookie':self.auth.logout(self.headers)})
            elif path == '/api/control':
                if self.auth.enabled and not user:
                    self._json({'error':'Login required'},401)
                    return
                from .scheduler import control_request
                self._json(control_request(self.config,identity,payload))
            else:
                self._json({'error':'Not found'},404)
        except (ValueError, TypeError, KeyError):
            self._json({'error':'Invalid request'},400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            print(f'POST {urlparse(self.path).path}: {type(error).__name__}')
            self._json({'error':'Service temporarily unavailable'},503)

    # ============================== Response helpers ==============================
    def log_message(self, fmt, *args):
        # Never log authorization codes, cookies, credentials or query strings.
        print(f'{self.client_address[0]} {self.command} {urlparse(self.path).path}')

    def _json(self,payload,status=200,headers=None):
        body = json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        for key,value in (headers or {}).items():
            self.send_header(key,value)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        if self.command!='HEAD':
            self.wfile.write(body)

    def redirect(self,location,cookie=None):
        self.send_response(303)
        self.send_header('Location',location)
        self.send_header('Cache-Control','no-store')
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length','0')
        self.end_headers()

    def _static(self,request_path):
        root = self.static_dir.resolve()
        candidate = (root/(request_path.lstrip('/') or 'index.html')).resolve()
        if root not in candidate.parents or (candidate.suffix and candidate.suffix not in ('.html','.js','.css','.svg','.png','.ico','.woff2')):
            self._json({'error':'Not found'},404)
            return
        if not candidate.is_file():
            if candidate.suffix:
                self._json({'error':'Not found'},404)
                return
            candidate = root/'index.html'
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream')
        self.send_header('Cache-Control','public, max-age=31536000, immutable' if candidate.parent.name=='assets' else 'no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        if self.command!='HEAD':
            self.wfile.write(body)


def run_server(config,host,port,static_dir='dist'):
    StatusHandler.config = config
    StatusHandler.auth = Auth(config)
    StatusHandler.snapshots = SnapshotStore()
    StatusHandler.limiter = RateLimiter()
    StatusHandler.static_dir = Path(static_dir)
    from .scheduler import init_control
    init_control(config)
    server = ThreadingHTTPServer((host,port),StatusHandler)
    print(f'Status API listening on {host}:{port}')
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description='Serve status snapshots and account sessions.')
    parser.add_argument('--config',default='configs/general.json')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=18080)
    parser.add_argument('--static-dir',default='dist')
    args = parser.parse_args()
    run_server(load_config(args.config),args.host,args.port,args.static_dir)


if __name__ == '__main__':
    main()
