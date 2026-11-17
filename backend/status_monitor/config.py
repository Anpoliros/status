"""Load repository-relative configuration, resource groups, and instance secrets."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ssh_transport import SSHTransport, load_transport
from .collectors import PrometheusConfig, load_collectors

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    url: str
    cluster: str = 'Default'
    id: str = ''
    order: int = 0
    metrics: dict | None = None


@dataclass(frozen=True)
class ServerConfig:
    name: str
    target: str
    cluster: str = 'Default'
    id: str = ''
    order: int = 0
    transport: SSHTransport | None = None


@dataclass(frozen=True)
class AppConfig:
    database: Path
    status_json: Path
    service_interval_seconds: int
    server_interval_seconds: int
    failure_threshold: int
    request_timeout_seconds: float
    history_hours: int
    services: list[ServiceConfig]
    servers: list[ServerConfig]
    prometheus: PrometheusConfig | None = None
    sources: list[PrometheusConfig] = field(default_factory=list)
    auth: dict = field(default_factory=dict)
    refresh: dict = field(default_factory=dict)
    instance_name: str = ''

    @property
    def all_servers(self):
        return self.servers + [server for source in self.sources for server in source.servers]

    @property
    def state_database(self) -> Path:
        return self.database.with_suffix('.control.db')


def repository_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _expand(value: Any, environment: dict) -> Any:
    if isinstance(value, str):
        def replace(match):
            key = match[1]
            if key not in environment or environment[key] is None:
                raise ValueError(f'Missing environment variable: {key}')
            return environment[key]
        return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', replace, value)
    if isinstance(value, list):
        return [_expand(item, environment) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, environment) for key, item in value.items()}
    return value


def _identity(kind: str, endpoint: str) -> str:
    return f'{kind}-{hashlib.sha256(endpoint.encode()).hexdigest()[:16]}'


def load_config(path: str | Path = 'configs/general.json') -> AppConfig:
    from dotenv import dotenv_values
    config_path = repository_path(path)
    environment = {**dotenv_values(config_path.parent / '.env', interpolate=False), **os.environ}
    raw = _expand(json.loads(config_path.read_text()), environment)
    resources = [raw]
    # Legacy files remain readable for an orderly migration.
    if 'resource_dirs' in raw or config_path.name == 'general.json':
        for directory in raw.get('resource_dirs', ['configs/resources']):
            directory = repository_path(directory)
            if not directory.is_dir():
                raise ValueError(f'Resource directory does not exist: {directory}')
            for resource_path in sorted(directory.glob('*.json')):
                if resource_path.name.endswith('.prometheus.json'):
                    continue
                resources.append(_expand(json.loads(resource_path.read_text()), environment))
    services, servers, sources = [], [], []
    ids, endpoints, tunnel_ports = set(), set(), set()
    for resource in resources:
        for kind, target_list, endpoint_key in [('service', services, 'url'), ('server', servers, 'target')]:
            for item in resource.get('services' if kind == 'service' else 'servers', []):
                if isinstance(item, str):
                    item = {'name': item, endpoint_key: item}
                endpoint = str(item[endpoint_key])
                if kind == 'service' and not endpoint.startswith(('http://', 'https://')):
                    endpoint = 'https://' + endpoint
                identity = str(item.get('id') or _identity(kind, endpoint))
                if identity in ids or (kind, endpoint) in endpoints:
                    raise ValueError(f'Duplicate resource: {identity}')
                ids.add(identity)
                endpoints.add((kind, endpoint))
                options = {}
                if kind == 'service' and item.get('metrics'):
                    metrics = item['metrics']
                    if not isinstance(metrics, dict) or set(metrics) - {'port'}:
                        raise ValueError('Service metrics supports a local port only')
                    port = metrics.get('port')
                    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                        raise ValueError('Invalid service metrics port')
                    options['metrics'] = {'port': port}
                if 'transport' in item:
                    if kind != 'server' or not item.get('id'):
                        raise ValueError('SSH transport requires a server with an explicit stable id')
                    transport = load_transport(item['transport'], endpoint, identity, str(config_path.resolve()))
                    if transport:
                        if transport.local_port in tunnel_ports:
                            raise ValueError(f'Duplicate SSH local port: {transport.local_port}')
                        tunnel_ports.add(transport.local_port)
                    options['transport'] = transport
                target_list.append((ServiceConfig if kind == 'service' else ServerConfig)(
                    str(item.get('name') or endpoint), endpoint, str(item.get('cluster') or 'Default'), identity, int(item.get('order', 0)), **options))
        definitions = resource.get('prometheus', [])
        if isinstance(definitions, dict):
            definitions = [definitions]
        sources.extend(PrometheusConfig(**item) for item in definitions)
    sources.extend(load_collectors(raw.get('collectors', []), environment,
                   lambda value: json.loads(repository_path(value).read_text())))
    for source in sources:
        for server in source.servers:
            if server.id in ids or ('server', server.target) in endpoints:
                raise ValueError(f'Duplicate resource: {server.id}')
            ids.add(server.id)
            endpoints.add(('server', server.target))
    refresh = {'minimum_seconds': 10, 'idle_seconds': 300, 'lease_seconds': 75,
               'presets': [10, 20, 60], **raw.get('refresh', {})}
    def integer(value, name):
        if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
            raise ValueError(f'Invalid integer: {name}')
        return int(value)

    for key in ('minimum_seconds', 'idle_seconds', 'lease_seconds'):
        refresh[key] = integer(refresh[key], f'refresh.{key}')
        if refresh[key] <= 0:
            raise ValueError(f'Invalid refresh.{key}')
    if refresh['idle_seconds'] < refresh['minimum_seconds'] or refresh['lease_seconds'] < 45:
        raise ValueError('Idle interval must respect minimum; lease must be at least 45 seconds')
    refresh['presets'] = [integer(value, 'refresh.presets') for value in refresh['presets']]
    if len(refresh['presets']) != 3 or any(not 0 < value <= 86400 for value in refresh['presets']):
        raise ValueError('Exactly three refresh presets between 1 and 86400 are required')
    instance = raw.get('instance', {})
    if not isinstance(instance, dict) or set(instance) - {'name'}:
        raise ValueError('instance supports a public name only')
    instance_name = instance.get('name', '')
    if not isinstance(instance_name, str) or len(instance_name) > 80:
        raise ValueError('instance.name must be a string of at most 80 characters')
    instance_name = instance_name.strip()
    auth = raw.get('auth', {})
    for section in ('shizunet', 'pseudo_user'):
        options = auth.setdefault(section, {})
        enabled = options.get('enabled', False)
        if isinstance(enabled, str) and enabled.lower() in ('true', 'false'):
            enabled = enabled.lower() == 'true'
        if not isinstance(enabled, bool):
            raise ValueError(f'auth.{section}.enabled must be true or false')
        options['enabled'] = enabled
    snapshot_path = repository_path(environment.get('STATUS_JSON') or raw.get('status_json', 'data/snapshots/current.json')).resolve()
    if any(public == snapshot_path or public in snapshot_path.parents for public in (ROOT/'dist', ROOT/'public', ROOT/'frontend/public')):
        raise ValueError('Snapshots must be outside public frontend directories')
    oidc = auth.get('shizunet', {})
    if oidc.get('enabled') and any(not oidc.get(k) for k in ('issuer', 'client_id', 'client_secret', 'base_url')):
        raise ValueError('Enabled Shizunet requires issuer, client_id, client_secret and base_url')
    pseudo = auth.get('pseudo_user', {})
    if pseudo.get('enabled') and (not pseudo.get('username') or not pseudo.get('password_hash')):
        raise ValueError('Enabled pseudo user requires username and password_hash')
    values = {key: int(raw.get(key, default)) for key, default in {
        'service_interval_seconds': 600, 'server_interval_seconds': 60,
        'failure_threshold': 3, 'history_hours': 1440}.items()}
    if any(v <= 0 for v in values.values()) or float(raw.get('request_timeout_seconds', 8)) <= 0:
        raise ValueError('Intervals, thresholds and timeouts must be positive')
    return AppConfig(
        database=repository_path(environment.get('STATUS_DATABASE') or raw.get('database', 'data/status.db')),
        status_json=snapshot_path,
        request_timeout_seconds=float(raw.get('request_timeout_seconds', 8)),
        services=services, servers=servers, sources=sources, auth=auth, refresh=refresh, instance_name=instance_name, **values)
