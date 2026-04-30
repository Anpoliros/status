import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.status_monitor.collector import network_per_minute
from backend.status_monitor.config import ServerConfig
from backend.status_monitor.db import connect, init_db, upsert_server
from backend.status_monitor.node_exporter import extract_node_metrics


class NodeExporterTests(unittest.TestCase):
    def test_extracts_core_metrics(self):
        payload = """
node_cpu_seconds_total{cpu="0",mode="idle"} 70
node_cpu_seconds_total{cpu="0",mode="user"} 20
node_cpu_seconds_total{cpu="0",mode="system"} 10
node_memory_MemTotal_bytes 1000
node_memory_MemAvailable_bytes 250
node_filesystem_size_bytes{fstype="ext4",mountpoint="/"} 2000
node_filesystem_avail_bytes{fstype="ext4",mountpoint="/"} 500
node_filesystem_size_bytes{fstype="tmpfs",mountpoint="/run"} 9000
node_filesystem_avail_bytes{fstype="tmpfs",mountpoint="/run"} 9000
node_network_receive_bytes_total{device="eth0"} 1024
node_network_transmit_bytes_total{device="eth0"} 2048
node_network_receive_bytes_total{device="lo"} 99
node_network_transmit_bytes_total{device="lo"} 99
"""
        metrics = extract_node_metrics(payload)

        self.assertAlmostEqual(metrics["cpu_usage"], 30.0)
        self.assertAlmostEqual(metrics["memory_usage"], 75.0)
        self.assertAlmostEqual(metrics["disk_usage"], 75.0)
        self.assertEqual(metrics["network_in"], 1024)
        self.assertEqual(metrics["network_out"], 2048)


class NetworkRateTests(unittest.TestCase):
    def test_network_counters_are_converted_to_bytes_per_minute(self):
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "status.db")
            init_db(conn)
            server_id = upsert_server(conn, ServerConfig(name="server", target="127.0.0.1:9100"))

            first = network_per_minute(
                conn,
                server_id,
                "2026-05-01T00:00:00Z",
                {"network_in": 1000.0, "network_out": 2000.0},
            )
            second = network_per_minute(
                conn,
                server_id,
                "2026-05-01T00:01:00Z",
                {"network_in": 1600.0, "network_out": 2600.0},
            )

            self.assertEqual(first, (None, None))
            self.assertEqual(second, (600.0, 600.0))


if __name__ == "__main__":
    unittest.main()
