from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import AppConfig


def build_status(conn: sqlite3.Connection, config: AppConfig) -> dict[str, Any]:
    services = _sort_by_config(
        (
            dict(row)
            for row in conn.execute(
                """
                SELECT s.id, s.name, s.url,
                       c.timestamp, c.latency_ms, COALESCE(c.status, 'unknown') AS status
                FROM services s
                LEFT JOIN service_checks c ON c.id = (
                  SELECT id FROM service_checks
                  WHERE service_id = s.id
                  ORDER BY timestamp DESC, id DESC
                  LIMIT 1
                )
                """
            ).fetchall()
        ),
        {service.url: index for index, service in enumerate(config.services)},
        "url",
    )

    servers = _sort_by_config(
        (
            dict(row)
            for row in conn.execute(
                """
                SELECT s.id, s.name, s.ip,
                       m.timestamp, m.cpu_usage, m.memory_usage, m.disk_usage,
                       m.network_in, m.network_out
                FROM servers s
                LEFT JOIN server_metrics m ON m.id = (
                  SELECT id FROM server_metrics
                  WHERE server_id = s.id
                  ORDER BY timestamp DESC, id DESC
                  LIMIT 1
                )
                """
            ).fetchall()
        ),
        {server.target: index for index, server in enumerate(config.servers)},
        "ip",
    )

    if services and any(service["status"] == "down" for service in services):
        overall = "degraded"
    elif services and all(service["status"] == "up" for service in services):
        overall = "operational"
    else:
        overall = "unknown"

    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "overall_status": overall,
        "services": services,
        "servers": servers,
        "history": {
            "services": service_history(conn, config.history_hours),
            "servers": server_history(conn, config.history_hours),
        },
    }


def service_history(conn: sqlite3.Connection, hours: int = 24) -> list[dict[str, Any]]:
    since = _since(hours)
    rows = conn.execute(
        """
        SELECT s.name, s.url, c.timestamp, c.latency_ms, c.status
        FROM service_checks c
        JOIN services s ON s.id = c.service_id
        WHERE c.timestamp >= ?
        ORDER BY c.timestamp ASC
        """,
        (since,),
    ).fetchall()
    return [dict(row) for row in rows]


def server_history(conn: sqlite3.Connection, hours: int = 24) -> list[dict[str, Any]]:
    since = _since(hours)
    rows = conn.execute(
        """
        SELECT s.name, s.ip, m.timestamp, m.cpu_usage, m.memory_usage, m.disk_usage,
               m.network_in, m.network_out
        FROM server_metrics m
        JOIN servers s ON s.id = m.server_id
        WHERE m.timestamp >= ?
        ORDER BY m.timestamp ASC
        """,
        (since,),
    ).fetchall()
    return [dict(row) for row in rows]


def write_status_json(conn: sqlite3.Connection, config: AppConfig) -> None:
    payload = build_status(conn, config)
    _write_json(config.status_json, payload)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sort_by_config(rows: Any, order: dict[str, int], key: str) -> list[dict[str, Any]]:
    return sorted(list(rows), key=lambda row: order.get(row[key], len(order)))


def _since(hours: int) -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .astimezone(UTC)
        - timedelta(hours=hours)
    ).isoformat().replace("+00:00", "Z")
