"""Validate optional SSH transport and render independently supervised tunnels."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class SSHTransport:
    host: str
    local_port: int


def exporter_url(target: str) -> str:
    return target if target.startswith(('http://', 'https://')) else f'http://{target}/metrics'


def ssh_destination(target: str) -> tuple[str, int]:
    parsed = urlsplit(exporter_url(target))
    if (parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or not re.fullmatch(r'[A-Za-z0-9_.:-]+', parsed.hostname)):
        raise ValueError('SSH transport requires an HTTP exporter target without credentials')
    return parsed.hostname, parsed.port or 80


def load_transport(raw, target: str, identity: str, instance: str) -> SSHTransport | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get('type') != 'ssh' or set(raw) - {'type', 'host', 'local_port'}:
        raise ValueError('Invalid SSH transport; expected type, host and optional local_port')
    host = raw.get('host')
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', host):
        raise ValueError('SSH transport requires a valid SSH host alias')
    ssh_destination(target)
    default_port = 20000 + int(hashlib.sha256(f'{instance}:{identity}'.encode()).hexdigest()[:8], 16) % 30000
    port = raw.get('local_port', default_port)
    if isinstance(port, bool) or not re.fullmatch(r'[0-9]+', str(port)) or not 1024 <= int(port) <= 65535:
        raise ValueError('SSH local_port must be an integer between 1024 and 65535')
    return SSHTransport(host, int(port))


def collection_url(target: str, transport: SSHTransport | None) -> str:
    url = exporter_url(target)
    if transport is None:
        return url
    parsed = urlsplit(url)
    return urlunsplit(parsed._replace(netloc=f'127.0.0.1:{transport.local_port}'))


# ============================== systemd rendering ==============================
def ssh_command(target: str, transport: SSHTransport) -> list[str]:
    host, port = ssh_destination(target)
    destination = f'[{host}]' if ':' in host else host
    return ['/usr/bin/ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
            '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-L', f'127.0.0.1:{transport.local_port}:{destination}:{port}', transport.host]


def render_unit(target: str, transport: SSHTransport) -> str:
    # systemd has its own escaping rules, independent of shell quoting.
    def quote(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'
    command = ' '.join(quote(arg) for arg in ssh_command(target, transport))
    return f'''# Managed by status: optional exporter SSH tunnel.
[Unit]
Description=Status exporter SSH tunnel
StartLimitIntervalSec=0

[Service]
ExecStart={command}
Restart=always
RestartSec=5
TimeoutStopSec=5
NoNewPrivileges=true

[Install]
WantedBy=default.target
'''
