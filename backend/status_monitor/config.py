"""Load repository-relative configuration, resource groups, and instance secrets."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    url: str
    cluster: str = 'Default'
    id: str = ''


@dataclass(frozen=True)
class ServerConfig:
    name: str
    target: str
    cluster: str = 'Default'
    id: str = ''


@dataclass(frozen=True)
class PrometheusConfig:
    url: str
    job: str
    enabled_label: str = 'status_enabled'
    enabled_value: str = 'true'
    name_label: str = 'status_name'
    cluster_label: str = 'cluster'


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
            if key not in environment:
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
                resources.append(_expand(json.loads(resource_path.read_text()), environment))
    services, servers, sources = [], [], []
    ids, endpoints = set(), set()
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
                target_list.append((ServiceConfig if kind == 'service' else ServerConfig)(
                    str(item.get('name') or endpoint), endpoint, str(item.get('cluster') or 'Default'), identity))
        definitions = resource.get('prometheus', [])
        if isinstance(definitions, dict):
            definitions = [definitions]
        sources.extend(PrometheusConfig(**item) for item in definitions)
    refresh = {'minimum_seconds': 10, 'idle_seconds': 300, 'lease_seconds': 75,
               'presets': [10, 20, 60], **raw.get('refresh', {})}
    for key in ('minimum_seconds', 'idle_seconds', 'lease_seconds'):
        if not isinstance(refresh[key], int) or refresh[key] <= 0:
            raise ValueError(f'Invalid refresh.{key}')
    if refresh['idle_seconds'] < refresh['minimum_seconds'] or refresh['lease_seconds'] < 45:
        raise ValueError('Idle interval must respect minimum; lease must be at least 45 seconds')
    if len(refresh['presets']) != 3 or any(not isinstance(x, int) or x <= 0 or x > 86400 for x in refresh['presets']):
        raise ValueError('Exactly three refresh presets between 1 and 86400 are required')
    auth = raw.get('auth', {})
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
        status_json=repository_path(environment.get('STATUS_JSON') or raw.get('status_json', 'data/snapshots/current.json')),
        request_timeout_seconds=float(raw.get('request_timeout_seconds', 8)),
        services=services, servers=servers, sources=sources, auth=auth, refresh=refresh, **values)
