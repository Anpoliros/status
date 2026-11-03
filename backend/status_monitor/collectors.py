"""Typed collector definitions and validation of locally managed Prometheus targets."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')


def identifier(value, description):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f'Invalid {description}: {value!r}')
    return value


def target_address(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        raise ValueError('Target must be host:port')
    parsed = urlparse('//'+value)
    try:
        valid = parsed.hostname and parsed.port and not parsed.path and not parsed.username and not parsed.query and not parsed.fragment
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f'Invalid Prometheus target: {value}')
    return value


@dataclass(frozen=True)
class PrometheusConfig:
    url: str
    job: str
    enabled_label: str = 'status_enabled'
    enabled_value: str = 'true'
    name_label: str = 'status_name'
    cluster_label: str = 'cluster'
    id: str = ''
    file: str = ''
    servers: tuple = ()
    deploy: dict = field(default_factory=dict)
    export_cluster_label: bool = False

    @property
    def managed(self):
        return bool(self.id)


def load_collectors(definitions, environment, read_json):
    # Import lazily to keep the shared resource types in config.py.
    from .config import ServerConfig, _expand
    sources, collector_ids, jobs, destinations = [], set(), set(), set()
    for item in definitions:
        if item.get('type') != 'prometheus':
            raise ValueError('Unsupported collector type')
        allowed = {'type','id','url','job','file','deploy','export_cluster_label'}
        if set(item)-allowed:
            raise ValueError(f'Unknown collector fields: {set(item)-allowed}')
        identity = identifier(item['id'],'collector ID')
        if identity in collector_ids:
            raise ValueError(f'Duplicate collector: {identity}')
        collector_ids.add(identity)
        if urlparse(item['url']).scheme not in ('http','https') or not urlparse(item['url']).hostname:
            raise ValueError('Collector URL must be HTTP(S)')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*',item['job']):
            raise ValueError('Invalid job name')
        job_key = (item['url'].rstrip('/'), item['job'])
        if job_key in jobs:
            raise ValueError('Each Prometheus job must have exactly one managed collector')
        jobs.add(job_key)
        if not item['file'].endswith('.prometheus.json'):
            raise ValueError('Collector file must end in .prometheus.json')
        content = _expand(read_json(item['file']),environment)
        if not isinstance(content,dict) or set(content) != {'servers'} or not isinstance(content['servers'],list):
            raise ValueError('Collector file must contain a servers array only')
        servers = []
        for server in content['servers']:
            if set(server)-{'id','name','target','cluster','order'}:
                raise ValueError('Unknown Prometheus server fields')
            machine_id = identifier(server['id'],'machine ID')
            target = target_address(server['target'])
            if not isinstance(server.get('name'),str) or not server['name']:
                raise ValueError('Machine display name is required')
            if not isinstance(server.get('cluster','Default'),str):
                raise ValueError('Cluster must be a string')
            servers.append(ServerConfig(server['name'],target,server.get('cluster','Default'),machine_id,int(server.get('order',0))))
        export = item.get('export_cluster_label',False)
        if not isinstance(export,bool):
            raise ValueError('export_cluster_label must be boolean')
        deploy = item.get('deploy',{})
        if deploy:
            if set(deploy)-{'ssh_host','target_file','promtool','config_file'}:
                raise ValueError('Unknown deployment fields')
            identifier(deploy['ssh_host'],'SSH host alias')
            destination = (deploy['ssh_host'], deploy['target_file'])
            if destination in destinations:
                raise ValueError('Collectors must not overwrite the same destination file')
            destinations.add(destination)
            path = deploy['target_file']
            if not path.startswith('/') or not path.endswith('.json') or '\n' in path or '..' in path.split('/'):
                raise ValueError('Deployment target must be an absolute JSON path')
        sources.append(PrometheusConfig(url=item['url'].rstrip('/'),job=item['job'],id=identity,
                       file=item['file'],servers=tuple(servers),deploy=deploy,export_cluster_label=export))
    return sources


def file_sd(source):
    result = []
    for server in source.servers:
        labels = {'status_id':server.id,'status_enabled':'true'}
        if source.export_cluster_label:
            labels['cluster'] = server.cluster
        result.append({'targets':[server.target],'labels':labels})
    return result
