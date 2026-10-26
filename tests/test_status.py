"""Status aggregation and configuration regression tests."""

import sqlite3
import unittest

from backend.status_monitor.config import AppConfig, ServerConfig, ServiceConfig
from backend.status_monitor.db import init_db, upsert_server
from backend.status_monitor.status import build_status


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        init_db(self.connection)
        self.config = AppConfig(
            database=None,
            status_json=None,
            service_interval_seconds=600,
            server_interval_seconds=60,
            failure_threshold=3,
            request_timeout_seconds=1,
            history_hours=1440,
            services=[ServiceConfig("Home", "https://example.com")],
            servers=[ServerConfig("App", "127.0.0.1:9100", "Cluster A")],
        )

    def tearDown(self):
        self.connection.close()

    def test_server_cluster_and_warning_level_are_exposed(self):
        server_id = upsert_server(self.connection, self.config.servers[0])
        self.connection.execute(
            "INSERT INTO server_metrics(server_id, timestamp, cpu_usage, memory_usage, disk_usage) VALUES (?, ?, ?, ?, ?)",
            (server_id, "2026-10-27T00:00:00Z", 81, 20, 30),
        )
        self.connection.commit()

        payload = build_status(self.connection, self.config)

        self.assertEqual(payload["servers"][0]["cluster"], "Cluster A")
        self.assertEqual(payload["servers"][0]["status"], "warning")
        self.assertEqual(payload["overall_status"], "warning")

    def test_missing_server_is_critical(self):
        upsert_server(self.connection, self.config.servers[0])
        payload = build_status(self.connection, self.config)
        self.assertEqual(payload["servers"][0]["status"], "critical")


if __name__ == "__main__":
    unittest.main()
