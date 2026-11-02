"""Coordinate expiring page leases and coalesced refresh requests across processes."""
from __future__ import annotations

import math
import re
import sqlite3
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS leases (
 page TEXT PRIMARY KEY, owner TEXT NOT NULL, seconds REAL NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule (
 scope TEXT PRIMARY KEY, last_started REAL NOT NULL DEFAULT 0,
 requested INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0, boot TEXT NOT NULL
);
'''


def connection(config):
    conn = sqlite3.connect(config.state_database,timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_control(config):
    from pathlib import Path
    config.state_database.parent.mkdir(parents=True,exist_ok=True)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    with connection(config) as conn:
        conn.executescript(SCHEMA)
        conn.execute('DELETE FROM schedule WHERE boot<>?',(boot,))
        if conn.total_changes:
            conn.execute('DELETE FROM leases')
        for scope in ('servers','services'):
            conn.execute('INSERT OR IGNORE INTO schedule(scope,boot) VALUES (?,?)',(scope,boot))


def effective_interval(minimum, idle, intervals):
    return max(minimum,min(intervals)) if intervals else idle


def due_at(last_started, minimum, interval, requested):
    return last_started + (minimum if requested else max(minimum,interval))


def control_request(config,owner,payload):
    page = str(payload.get('page',''))
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',page):
        raise ValueError('Invalid page lease')
    action = payload.get('action','heartbeat')
    if action not in ('connect','heartbeat','update','release','refresh'):
        raise ValueError('Invalid control action')
    scope = payload.get('scope','servers')
    if scope not in ('servers','services'):
        raise ValueError('Invalid collection scope')
    seconds = payload.get('seconds',60)
    if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<seconds<=86400:
        raise ValueError('Invalid refresh interval')
    now = time.monotonic()
    minimum = config.refresh['minimum_seconds']
    accepted = max(minimum,seconds)
    with connection(config) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM leases WHERE expires<=?',(now,))
        existing = conn.execute('SELECT owner FROM leases WHERE page=?',(page,)).fetchone()
        if existing and existing['owner']!=owner:
            raise ValueError('Page lease owner mismatch')
        if action=='release':
            conn.execute('DELETE FROM leases WHERE page=? AND owner=?',(page,owner))
        elif scope=='servers':
            count = conn.execute('SELECT COUNT(*) FROM leases WHERE owner=?',(owner,)).fetchone()[0]
            total = conn.execute('SELECT COUNT(*) FROM leases').fetchone()[0]
            if not existing and (count>=16 or total>=512):
                raise ValueError('Too many active pages')
            conn.execute('INSERT INTO leases VALUES (?,?,?,?) ON CONFLICT(page) DO UPDATE SET seconds=excluded.seconds,expires=excluded.expires',
                         (page,owner,accepted,now+config.refresh['lease_seconds']))
        if action in ('connect','refresh'):
            conn.execute('UPDATE schedule SET requested=1 WHERE scope=?',(scope,))
        intervals = [row[0] for row in conn.execute('SELECT seconds FROM leases')]
        state = conn.execute('SELECT * FROM schedule WHERE scope=?',(scope,)).fetchone()
    return {'accepted_seconds':accepted,'minimum_seconds':minimum,'clamped':seconds<minimum,
            'effective_seconds':effective_interval(minimum,config.refresh['idle_seconds'],intervals),
            'wait_seconds':max(0,state['last_started']+minimum-now),'pending':bool(state['requested']), 'version':state['completed']}


def claim_due(config,scope,now=None):
    """Only the worker claims jobs; start times are committed before network work."""
    now = time.monotonic() if now is None else now
    with connection(config) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM leases WHERE expires<=?',(now,))
        intervals = [row[0] for row in conn.execute('SELECT seconds FROM leases')]
        interval = effective_interval(config.refresh['minimum_seconds'],config.refresh['idle_seconds'],intervals) if scope=='servers' else config.service_interval_seconds
        row = conn.execute('SELECT * FROM schedule WHERE scope=?',(scope,)).fetchone()
        if now<due_at(row['last_started'],config.refresh['minimum_seconds'],interval,row['requested']):
            return False
        conn.execute('UPDATE schedule SET last_started=?,requested=0 WHERE scope=?',(now,scope))
        return True


def finish_collection(config,scope):
    # Requests arriving during a collection share that result, avoiding a trailing job.
    with connection(config) as conn:
        conn.execute('UPDATE schedule SET requested=0,completed=completed+1 WHERE scope=?',(scope,))
