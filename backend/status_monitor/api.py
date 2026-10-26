from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import AppConfig, load_config
from .collector import run_server_collection, run_service_checks
from .db import connect, init_db, sync_config
from .status import build_status, server_history, service_history


class StatusHandler(BaseHTTPRequestHandler):
    config: AppConfig
    static_dir: Path | None = None

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/status", "/check", "/healthz", "/history/services", "/history/servers"}:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        else:
            self._static(parsed.path, head_only=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        hours = int(query.get("hours", [self.config.history_hours])[0])

        if parsed.path == "/healthz":
            self._json({"ok": True})
            return
        if parsed.path not in {"/status", "/check", "/history/services", "/history/servers"}:
            self._static(parsed.path)
            return

        with connect(self.config.database) as conn:
            if parsed.path == "/status":
                probe = query.get("probe", [""])[0]
                if probe in {"servers", "services", "all"}:
                    self._probe(conn, probe)
                self._json(build_status(conn, self.config))
            elif parsed.path == "/check":
                status = build_status(conn, self.config)
                unavailable = [item["name"] for item in status["services"] if item["status"] != "up"]
                unavailable.extend(item["name"] for item in status["servers"] if item["status"] == "critical")
                level = "healthy" if not unavailable else "alert" if len(unavailable) >= 3 else "attention"
                self._json({"overall_status": level, "unavailable": unavailable})
            elif parsed.path == "/history/services":
                self._json({"items": service_history(conn, hours)})
            elif parsed.path == "/history/servers":
                self._json({"items": server_history(conn, hours)})
            else:
                self._static(parsed.path)

    def _probe(self, conn, scope: str) -> None:
        async def collect() -> None:
            if scope in {"servers", "all"}:
                await run_server_collection(conn, self.config)
            if scope in {"services", "all"}:
                await run_service_checks(conn, self.config)

        asyncio.run(collect())

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, request_path: str, head_only: bool = False) -> None:
        if self.static_dir is None:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        relative = request_path.lstrip("/") or "index.html"
        candidate = (self.static_dir / relative).resolve()
        static_root = self.static_dir.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.exists() or candidate.is_dir():
            candidate = static_root / "index.html"
        if not candidate.exists():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


def run_server(config: AppConfig, host: str, port: int, static_dir: str | None = None) -> None:
    with connect(config.database) as conn:
        init_db(conn)
        sync_config(conn, config)
    StatusHandler.config = config
    StatusHandler.static_dir = Path(static_dir) if static_dir else None
    server = ThreadingHTTPServer((host, port), StatusHandler)
    print(f"Status API listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the status monitor read-only API.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--static-dir", default=None, help="Optional built frontend directory to serve.")
    args = parser.parse_args()
    run_server(load_config(args.config), args.host, args.port, args.static_dir)


if __name__ == "__main__":
    main()
