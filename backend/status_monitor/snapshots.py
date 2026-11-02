"""Incrementally aggregate history and publish private, atomic JSON snapshots."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import AppConfig
from .status import build_status

SCHEMA = '''
CREATE TABLE IF NOT EXISTS history_bins (
 kind TEXT NOT NULL, resource_id INTEGER NOT NULL, resolution TEXT NOT NULL,
 bucket TEXT NOT NULL, healthy INTEGER NOT NULL, warning INTEGER NOT NULL,
 critical INTEGER NOT NULL, total INTEGER NOT NULL,
 PRIMARY KEY(kind, resource_id, resolution, bucket)
);
CREATE TABLE IF NOT EXISTS history_cursors (kind TEXT PRIMARY KEY, last_id INTEGER NOT NULL);
'''


def update_bins(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for kind, table, foreign_key in [('services', 'service_checks', 'service_id'), ('servers', 'server_metrics', 'server_id')]:
        cursor = conn.execute('SELECT last_id FROM history_cursors WHERE kind=?', (kind,)).fetchone()
        last_id = cursor['last_id'] if cursor else 0
        maximum = conn.execute(f'SELECT COALESCE(MAX(id),0) FROM {table}').fetchone()[0]
        if maximum <= last_id:
            continue
        if kind == 'services':
            severity = "CASE WHEN status='up' THEN 0 ELSE 2 END"
        else:
            severity = '''CASE WHEN cpu_usage IS NULL AND memory_usage IS NULL AND disk_usage IS NULL THEN 2
                WHEN MAX(COALESCE(cpu_usage,0),COALESCE(memory_usage,0),COALESCE(disk_usage,0))>=95 THEN 2
                WHEN MAX(COALESCE(cpu_usage,0),COALESCE(memory_usage,0),COALESCE(disk_usage,0))>=80 THEN 1 ELSE 0 END'''
        for resolution, length in [('day', 10), ('hour', 13)]:
            conn.execute(f'''INSERT INTO history_bins
                SELECT ?, {foreign_key}, ?, substr(timestamp,1,?),
                    SUM(level=0), SUM(level=1), SUM(level=2), COUNT(*)
                FROM (SELECT *, {severity} AS level FROM {table} WHERE id>? AND id<=?)
                GROUP BY {foreign_key}, substr(timestamp,1,?)
                ON CONFLICT(kind,resource_id,resolution,bucket) DO UPDATE SET
                    healthy=healthy+excluded.healthy, warning=warning+excluded.warning,
                    critical=critical+excluded.critical, total=total+excluded.total''',
                (kind, resolution, length, last_id, maximum, length))
        conn.execute('INSERT OR REPLACE INTO history_cursors VALUES (?,?)', (kind, maximum))
    cutoff = (datetime.now(UTC) - timedelta(days=61)).strftime('%Y-%m-%d')
    conn.execute('DELETE FROM history_bins WHERE bucket<?', (cutoff,))
    conn.commit()


def history_snapshot(conn, current, kind, period):
    resolution = 'day' if period == '60d' else 'hour'
    now = datetime.now(UTC)
    start = now - timedelta(days=59) if period == '60d' else now - timedelta(hours=47)
    cutoff = start.strftime('%Y-%m-%d' if period == '60d' else '%Y-%m-%dT%H')
    grouped = {}
    for row in conn.execute('SELECT * FROM history_bins WHERE kind=? AND resolution=? AND bucket>=? ORDER BY bucket', (kind, resolution, cutoff)):
        if kind == 'services':
            level = 'warning' if row['healthy'] and row['critical'] else 'critical' if row['critical'] else 'healthy'
        else:
            level = 'critical' if row['critical'] else 'warning' if row['warning'] else 'healthy'
        grouped.setdefault(row['resource_id'], []).append({'key': row['bucket'], 'level': level, 'total': row['total']})
    return {'generated_at': current['generated_at'], 'collection_versions': current.get('collection_versions', {}), 'items': [
        {key: item[key] for key in ('id', 'name', 'url', 'ip', 'cluster') if key in item}
        | {'buckets': grouped.get(item['id'], [])} for item in current[kind]]}


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.snapshot-')
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(payload, output, ensure_ascii=False, separators=(',', ':'))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_snapshots(conn: sqlite3.Connection, config: AppConfig) -> None:
    update_bins(conn)
    current = build_status(conn, config, include_history=False)
    current.pop('history', None)
    from .scheduler import connection, init_control
    init_control(config)
    with connection(config) as control:
        current['collection_versions'] = {row['scope']: row['completed'] for row in control.execute('SELECT scope,completed FROM schedule')}
    for kind in ('services', 'servers'):
        for period in ('48h', '60d'):
            atomic_json(config.status_json.parent / f'{kind}-{period}.json', history_snapshot(conn, current, kind, period))
    atomic_json(config.status_json, current)


class SnapshotStore:
    """Reload bytes only when an atomic file replacement changes its identity."""
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def read(self, path: Path):
        with self.lock:
            stat = path.stat()
            identity = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if path not in self.cache or self.cache[path][0] != identity:
                self.cache[path] = (identity, json.loads(path.read_bytes()))
            return self.cache[path][1]
