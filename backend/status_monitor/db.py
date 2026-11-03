"""SQLite storage and synchronization of configured monitoring resources."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import AppConfig, ServerConfig, ServiceConfig, _identity


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS service_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  timestamp TEXT NOT NULL,
  latency_ms INTEGER,
  status TEXT NOT NULL CHECK (status IN ('up', 'down'))
);

CREATE INDEX IF NOT EXISTS idx_service_checks_recent
  ON service_checks(service_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS servers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  ip TEXT NOT NULL UNIQUE,
  cluster TEXT NOT NULL DEFAULT 'Default'
);

CREATE TABLE IF NOT EXISTS server_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  timestamp TEXT NOT NULL,
  cpu_usage REAL,
  memory_usage REAL,
  disk_usage REAL,
  network_in REAL,
  network_out REAL
);

CREATE INDEX IF NOT EXISTS idx_server_metrics_recent
  ON server_metrics(server_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS service_state (
  service_id INTEGER PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,
  consecutive_failures INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS server_state (
  server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
  last_timestamp TEXT NOT NULL,
  last_network_in_counter REAL,
  last_network_out_counter REAL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(servers)")}
    if "cluster" not in columns:
        conn.execute("ALTER TABLE servers ADD COLUMN cluster TEXT NOT NULL DEFAULT 'Default'")
    if 'resource_id' not in columns:
        conn.execute('ALTER TABLE servers ADD COLUMN resource_id TEXT')
    if 'active' not in columns:
        conn.execute('ALTER TABLE servers ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_servers_resource_id ON servers(resource_id)')
    conn.commit()


def sync_config(conn: sqlite3.Connection, config: AppConfig) -> None:
    service_urls = [service.url for service in config.services]
    server_targets = [server.target for server in config.all_servers]

    for service in config.services:
        upsert_service(conn, service)
    for server in config.all_servers:
        upsert_server(conn, server)

    if service_urls:
        placeholders = ",".join("?" for _ in service_urls)
        conn.execute(f"DELETE FROM services WHERE url NOT IN ({placeholders})", service_urls)
    else:
        conn.execute("DELETE FROM services")

    # Deactivate removed machines without deleting metrics or aggregated history.
    # Legacy discovery remains supported until an instance switches to managed files.
    legacy = config.prometheus or any(not source.managed for source in config.sources)
    if not legacy:
        if server_targets:
            placeholders = ','.join('?' for _ in server_targets)
            conn.execute(f'UPDATE servers SET active=0 WHERE ip NOT IN ({placeholders})',server_targets)
        else:
            conn.execute('UPDATE servers SET active=0')

    conn.commit()


def upsert_service(conn: sqlite3.Connection, service: ServiceConfig) -> int:
    conn.execute(
        """
        INSERT INTO services(name, url) VALUES (?, ?)
        ON CONFLICT(url) DO UPDATE SET name = excluded.name
        """,
        (service.name, service.url),
    )
    return int(conn.execute("SELECT id FROM services WHERE url = ?", (service.url,)).fetchone()["id"])


def upsert_server(conn: sqlite3.Connection, server: ServerConfig) -> int:
    identity = server.id or _identity('server', server.target)
    row = conn.execute('SELECT id,ip FROM servers WHERE resource_id=?',(identity,)).fetchone()
    endpoint = conn.execute('SELECT id,resource_id FROM servers WHERE ip=?',(server.target,)).fetchone()
    if row and endpoint and row['id'] != endpoint['id']:
        raise ValueError(f'Endpoint belongs to another machine: {server.target}')
    if row:
        if row['ip'] != server.target:
            # Network counters from a previous endpoint must not be differenced.
            conn.execute('DELETE FROM server_state WHERE server_id=?',(row['id'],))
        conn.execute('UPDATE servers SET name=?,ip=?,cluster=?,active=1 WHERE id=?',
                     (server.name,server.target,server.cluster,row['id']))
        return row['id']
    if endpoint:
        # One-time adoption of legacy rows keeps their integer keys and all history.
        if endpoint['resource_id'] not in (None, _identity('server',server.target)):
            raise ValueError(f'Machine ID changed at existing endpoint: {server.target}')
        conn.execute('UPDATE servers SET resource_id=?,name=?,cluster=?,active=1 WHERE id=?',
                     (identity,server.name,server.cluster,endpoint['id']))
        return endpoint['id']
    cursor = conn.execute('INSERT INTO servers(resource_id,name,ip,cluster) VALUES (?,?,?,?)',
                          (identity,server.name,server.target,server.cluster))
    return cursor.lastrowid


def recent_service_failures(conn: sqlite3.Connection, service_id: int, limit: int) -> int:
    rows = conn.execute(
        """
        SELECT status FROM service_checks
        WHERE service_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (service_id, limit),
    ).fetchall()
    failures = 0
    for row in rows:
        if row["status"] != "down":
            break
        failures += 1
    return failures


def service_failure_count(conn: sqlite3.Connection, service_id: int) -> int:
    row = conn.execute(
        "SELECT consecutive_failures FROM service_state WHERE service_id = ?",
        (service_id,),
    ).fetchone()
    return int(row["consecutive_failures"]) if row else 0


def set_service_failure_count(conn: sqlite3.Connection, service_id: int, count: int) -> None:
    conn.execute(
        """
        INSERT INTO service_state(service_id, consecutive_failures)
        VALUES (?, ?)
        ON CONFLICT(service_id) DO UPDATE
        SET consecutive_failures = excluded.consecutive_failures
        """,
        (service_id, count),
    )


def server_network_state(conn: sqlite3.Connection, server_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT last_timestamp, last_network_in_counter, last_network_out_counter
        FROM server_state
        WHERE server_id = ?
        """,
        (server_id,),
    ).fetchone()


def set_server_network_state(
    conn: sqlite3.Connection,
    server_id: int,
    timestamp: str,
    network_in_counter: float | None,
    network_out_counter: float | None,
) -> None:
    conn.execute(
        """
        INSERT INTO server_state(
          server_id, last_timestamp, last_network_in_counter, last_network_out_counter
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(server_id) DO UPDATE SET
          last_timestamp = excluded.last_timestamp,
          last_network_in_counter = excluded.last_network_in_counter,
          last_network_out_counter = excluded.last_network_out_counter
        """,
        (server_id, timestamp, network_in_counter, network_out_counter),
    )
