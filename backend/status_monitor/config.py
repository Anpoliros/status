from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    url: str


@dataclass(frozen=True)
class ServerConfig:
    name: str
    target: str
    cluster: str = "Default"


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


def _service_from_item(item: str | dict[str, Any]) -> ServiceConfig:
    if isinstance(item, str):
        url = item if item.startswith(("http://", "https://")) else f"https://{item}"
        return ServiceConfig(name=item.replace("https://", "").replace("http://", ""), url=url)
    name = str(item.get("name") or item.get("url"))
    url = str(item["url"])
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return ServiceConfig(name=name, url=url)


def _server_from_item(item: str | dict[str, Any]) -> ServerConfig:
    if isinstance(item, str):
        return ServerConfig(name=item, target=item)
    return ServerConfig(
        name=str(item.get("name") or item["target"]),
        target=str(item["target"]),
        cluster=str(item.get("cluster") or "Default"),
    )


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent

    database = Path(os.getenv("STATUS_DATABASE", raw.get("database", "data/status.db")))
    status_json = Path(os.getenv("STATUS_JSON", raw.get("status_json", "frontend/public/status.json")))
    if not database.is_absolute():
        database = base / database
    if not status_json.is_absolute():
        status_json = base / status_json

    return AppConfig(
        database=database,
        status_json=status_json,
        service_interval_seconds=int(raw.get("service_interval_seconds", 600)),
        server_interval_seconds=int(raw.get("server_interval_seconds", 60)),
        failure_threshold=int(raw.get("failure_threshold", 3)),
        request_timeout_seconds=float(raw.get("request_timeout_seconds", 8)),
        history_hours=int(raw.get("history_hours", 24 * 60)),
        services=[_service_from_item(item) for item in raw.get("services", [])],
        servers=[_server_from_item(item) for item in raw.get("servers", [])],
    )
