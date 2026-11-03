"""Collect configured services, static machines and Prometheus resource groups."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AppConfig, PrometheusConfig, ServerConfig, ServiceConfig
from .db import (
    server_network_state,
    service_failure_count,
    set_server_network_state,
    set_service_failure_count,
    upsert_server,
    upsert_service,
)
from .node_exporter import extract_node_metrics


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_text(url: str, timeout: float) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": "status-monitor/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def fetch_status(url: str, timeout: float) -> int:
    request = Request(url, headers={"User-Agent": "status-monitor/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.status


def fetch_json(url: str, timeout: float) -> dict:
    request = Request(url, headers={"User-Agent": "status-monitor/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


async def check_service(conn: sqlite3.Connection, config: AppConfig, service: ServiceConfig) -> None:
    service_id = upsert_service(conn, service)
    started = time.perf_counter()
    try:
        status_code = await asyncio.to_thread(fetch_status, service.url, config.request_timeout_seconds)
        latency_ms = round((time.perf_counter() - started) * 1000)
        raw_status = "up" if 200 <= status_code < 400 else "down"
    except (TimeoutError, URLError, OSError):
        latency_ms = None
        raw_status = "down"

    failures = service_failure_count(conn, service_id)
    failures = failures + 1 if raw_status == "down" else 0
    set_service_failure_count(conn, service_id, failures)
    effective_status = "down" if failures >= config.failure_threshold else "up"
    conn.execute(
        """
        INSERT INTO service_checks(service_id, timestamp, latency_ms, status)
        VALUES (?, ?, ?, ?)
        """,
        (service_id, now_iso(), latency_ms, effective_status),
    )
    conn.commit()


async def collect_server(conn: sqlite3.Connection, config: AppConfig, server: ServerConfig) -> None:
    server_id = upsert_server(conn, server)
    url = server.target if server.target.startswith(("http://", "https://")) else f"http://{server.target}/metrics"
    timestamp = now_iso()
    try:
        status_code, body = await asyncio.to_thread(fetch_text, url, config.request_timeout_seconds)
        metrics = extract_node_metrics(body.decode("utf-8", errors="replace")) if status_code == 200 else {}
    except (TimeoutError, URLError, OSError):
        metrics = {}

    network_in, network_out = network_per_minute(conn, server_id, timestamp, metrics)

    conn.execute(
        """
        INSERT INTO server_metrics(
          server_id, timestamp, cpu_usage, memory_usage, disk_usage, network_in, network_out
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            timestamp,
            metrics.get("cpu_usage"),
            metrics.get("memory_usage"),
            metrics.get("disk_usage"),
            network_in,
            network_out,
        ),
    )
    conn.commit()


async def run_service_checks(conn: sqlite3.Connection, config: AppConfig) -> None:
    await asyncio.gather(*(check_service(conn, config, service) for service in config.services))


async def run_server_collection(conn: sqlite3.Connection, config: AppConfig) -> None:
    sources = config.sources or ([config.prometheus] if config.prometheus else [])
    for source in sources:
        await collect_prometheus_servers(conn, config, source)
    await asyncio.gather(*(collect_server(conn, config, server) for server in config.servers))


def _prometheus_url(source: PrometheusConfig, path: str, params: dict[str, str]) -> str:
    return f"{source.url}{path}?{urlencode(params)}"


def discover_prometheus_servers(source: PrometheusConfig, timeout: float) -> list[ServerConfig]:
    payload = fetch_json(_prometheus_url(source, "/api/v1/targets", {"state": "active"}), timeout)
    servers = []
    for target in payload.get("data", {}).get("activeTargets", []):
        labels = target.get("labels") or {}
        if labels.get("job") != source.job or labels.get(source.enabled_label) != source.enabled_value:
            continue
        instance = str(labels.get("instance") or target.get("scrapeUrl") or "")
        if not instance:
            continue
        servers.append(
            ServerConfig(
                name=str(labels.get(source.name_label) or instance),
                target=instance,
                cluster=str(labels.get(source.cluster_label) or "Default"),
            )
        )
    return servers


def _query_metric(source: PrometheusConfig, expression: str, timeout: float) -> dict[str, float]:
    payload = fetch_json(_prometheus_url(source, "/api/v1/query", {"query": expression}), timeout)
    values = {}
    for item in payload.get("data", {}).get("result", []):
        instance = item.get("metric", {}).get("status_id" if source.managed else "instance")
        value = item.get("value", [None, None])[1]
        if instance is None:
            continue
        try:
            values[str(instance)] = float(value)
        except (TypeError, ValueError):
            continue
    return values


async def collect_prometheus_servers(
    conn: sqlite3.Connection, config: AppConfig, source: PrometheusConfig
) -> None:
    try:
        servers = list(source.servers) if source.managed else await asyncio.to_thread(discover_prometheus_servers, source, config.request_timeout_seconds)
        selector = f'job="{source.job}",{source.enabled_label}="{source.enabled_value}"'
        group = "status_id" if source.managed else "instance"
        queries = {
            "up": f'up{{{selector}}}',
            "cpu_usage": f'100 * (1 - avg by({group}) (rate(node_cpu_seconds_total{{{selector},mode="idle"}}[5m])))',
            "memory_usage": f'100 * (1 - node_memory_MemAvailable_bytes{{{selector}}} / node_memory_MemTotal_bytes{{{selector}}})',
            "disk_usage": f'100 * (1 - sum by({group}) (node_filesystem_avail_bytes{{{selector}}}) / sum by({group}) (node_filesystem_size_bytes{{{selector}}}))',
            "network_in": f'sum by({group}) (rate(node_network_receive_bytes_total{{{selector}}}[1m]))',
            "network_out": f'sum by({group}) (rate(node_network_transmit_bytes_total{{{selector}}}[1m]))',
        }
        metrics = {
            name: await asyncio.to_thread(_query_metric, source, expression, config.request_timeout_seconds)
            for name, expression in queries.items()
        }
    except (TimeoutError, URLError, OSError, ValueError, json.JSONDecodeError):
        servers = list(source.servers) if source.managed else []
        metrics = {}

    timestamp = now_iso()
    for server in servers:
        server_id = upsert_server(conn, server)
        metric_id = server.id if source.managed else server.target
        up = metrics.get("up", {}).get(metric_id)
        if up != 1:
            values = {key: None for key in ("cpu_usage", "memory_usage", "disk_usage", "network_in", "network_out")}
        else:
            values = {key: metrics.get(key, {}).get(metric_id) for key in ("cpu_usage", "memory_usage", "disk_usage")}
            values["network_in"] = (metrics.get("network_in", {}).get(metric_id) or 0.0) * 60
            values["network_out"] = (metrics.get("network_out", {}).get(metric_id) or 0.0) * 60
        conn.execute(
            """
            INSERT INTO server_metrics(
              server_id, timestamp, cpu_usage, memory_usage, disk_usage, network_in, network_out
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (server_id, timestamp, values["cpu_usage"], values["memory_usage"], values["disk_usage"], values["network_in"], values["network_out"]),
        )
    conn.commit()


def network_per_minute(
    conn: sqlite3.Connection,
    server_id: int,
    timestamp: str,
    metrics: dict[str, float | None],
) -> tuple[float | None, float | None]:
    current_in = metrics.get("network_in")
    current_out = metrics.get("network_out")
    previous = server_network_state(conn, server_id)

    set_server_network_state(conn, server_id, timestamp, current_in, current_out)
    if previous is None or current_in is None or current_out is None:
        return None, None

    previous_in = previous["last_network_in_counter"]
    previous_out = previous["last_network_out_counter"]
    if previous_in is None or previous_out is None:
        return None, None

    elapsed_seconds = (parse_iso(timestamp) - parse_iso(previous["last_timestamp"])).total_seconds()
    if elapsed_seconds <= 0 or current_in < previous_in or current_out < previous_out:
        return None, None

    scale = 60.0 / elapsed_seconds
    return (current_in - previous_in) * scale, (current_out - previous_out) * scale


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
