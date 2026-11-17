"""Local service-port telemetry: durable counters, bounded history and TCP gauges."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from datetime import datetime, UTC
from pathlib import Path

from .db import connect

COUNTERS = Path('/run/status-ports/counters.json')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS port_state (
 resource TEXT PRIMARY KEY, generation TEXT, timestamp REAL, incoming INTEGER, outgoing INTEGER
);
CREATE TABLE IF NOT EXISTS port_samples (
 resource TEXT, timestamp REAL, rx REAL, tx REAL, tcp INTEGER,
 PRIMARY KEY(resource,timestamp)
);
CREATE TABLE IF NOT EXISTS port_history (
 resource TEXT, resolution TEXT, bucket TEXT, incoming INTEGER DEFAULT 0,
 outgoing INTEGER DEFAULT 0, seconds REAL DEFAULT 0, tcp_sum INTEGER DEFAULT 0,
 tcp_count INTEGER DEFAULT 0, tcp_max INTEGER,
 PRIMARY KEY(resource,resolution,bucket)
);
'''


def connection_counts(ports):
    # Query only server endpoints: loopback's client half has an ephemeral local port.
    result = subprocess.run(['ss', '-Hnt', 'state', 'established'],
                            capture_output=True, text=True, timeout=4, check=True)
    counts = dict.fromkeys(ports, 0)
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            try:
                port = int(fields[2].rsplit(':', 1)[1])
            except (ValueError, IndexError):
                continue
            if port in counts:
                counts[port] += 1
    return counts


def record(conn, resource, timestamp, counter, tcp):
    previous = conn.execute('SELECT * FROM port_state WHERE resource=?', (resource,)).fetchone()
    rx = tx = elapsed = None
    if counter:
        generation, incoming, outgoing = counter
        if previous and generation == previous['generation']:
            duration = timestamp - previous['timestamp']
            if 0 < duration <= 30 and incoming >= previous['incoming'] and outgoing >= previous['outgoing']:
                elapsed = duration
                rx, tx = incoming - previous['incoming'], outgoing - previous['outgoing']
        conn.execute('INSERT OR REPLACE INTO port_state VALUES (?,?,?,?,?)',
                     (resource, generation, timestamp, incoming, outgoing))
    else:
        conn.execute('DELETE FROM port_state WHERE resource=?', (resource,))
    conn.execute('INSERT INTO port_samples VALUES (?,?,?,?,?)',
                 (resource, timestamp, None if rx is None else rx / elapsed,
                  None if tx is None else tx / elapsed, tcp))
    for resolution, fmt in [('hour', '%Y-%m-%dT%H'), ('day', '%Y-%m-%d')]:
        bucket = datetime.fromtimestamp(timestamp, UTC).strftime(fmt)
        conn.execute('''INSERT INTO port_history VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(resource,resolution,bucket) DO UPDATE SET
            incoming=incoming+excluded.incoming,outgoing=outgoing+excluded.outgoing,
            seconds=seconds+excluded.seconds,tcp_sum=tcp_sum+excluded.tcp_sum,
            tcp_count=tcp_count+excluded.tcp_count,tcp_max=CASE WHEN tcp_max IS NULL THEN excluded.tcp_max WHEN excluded.tcp_max IS NULL THEN tcp_max ELSE MAX(tcp_max,excluded.tcp_max) END''',
            (resource, resolution, bucket, rx or 0, tx or 0, elapsed or 0,
             tcp or 0, int(tcp is not None), tcp))


def collect_metrics(config):
    services = [service for service in config.services if service.metrics]
    ports = {service.metrics['port'] for service in services}
    timestamp = time.time()
    try:
        counts = connection_counts(ports)
    except (OSError, subprocess.SubprocessError):
        counts = {}
    try:
        payload = json.loads(COUNTERS.read_text())
        if not 0 <= timestamp - payload['timestamp'] <= 15:
            payload = {}
    except (OSError, ValueError, KeyError, TypeError):
        payload = {}
    with connect(config.database) as conn:
        conn.executescript(SCHEMA)
        for service in services:
            port = service.metrics['port']
            values = payload.get('ports', {}).get(str(port))
            counter = (payload['generation'], *values) if values else None
            record(conn, service.id, timestamp, counter, counts.get(port))
        conn.execute('DELETE FROM port_samples WHERE timestamp<?', (timestamp - 86400,))
        cutoff = datetime.fromtimestamp(timestamp - 61 * 86400, UTC).strftime('%Y-%m-%d')
        conn.execute('DELETE FROM port_history WHERE bucket<?', (cutoff,))


def attach_metrics(conn, config, services):
    conn.executescript(SCHEMA)
    definitions = {item.url: item for item in config.services}
    now = time.time()
    for service in services:
        definition = definitions.get(service['url'])
        if not definition or not definition.metrics:
            continue
        resource = definition.id
        row = conn.execute('SELECT * FROM port_samples WHERE resource=? ORDER BY timestamp DESC LIMIT 1', (resource,)).fetchone()
        fresh = row is not None and 0 <= now - row['timestamp'] < 35
        history = [dict(item) for item in conn.execute('SELECT * FROM port_history WHERE resource=? ORDER BY bucket', (resource,))]
        recent = [dict(item) for item in conn.execute('''SELECT CAST(timestamp/60 AS INTEGER)*60 AS timestamp,
            AVG(rx) AS rx,AVG(tx) AS tx,AVG(tcp) AS tcp FROM port_samples
            WHERE resource=? AND timestamp>? GROUP BY CAST(timestamp/60 AS INTEGER) ORDER BY timestamp''', (resource, now - 3600))]
        service['metrics'] = {'port': definition.metrics['port'], 'timestamp': row['timestamp'] if row else None,
            'rx': row['rx'] if fresh else None, 'tx': row['tx'] if fresh else None,
            'tcp': row['tcp'] if fresh else None, 'recent': recent, 'history': history}
