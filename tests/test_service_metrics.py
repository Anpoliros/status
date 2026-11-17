"""Verify counter generations, missing samples, socket attribution and history."""
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from backend.status_monitor.service_metrics import SCHEMA, record, connection_counts


class ServiceMetricsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def test_rates_and_reset(self):
        record(self.conn, 'web', 100, ('a', 100, 200), 3)
        record(self.conn, 'web', 110, ('a', 200, 400), 5)
        row = self.conn.execute('SELECT * FROM port_samples ORDER BY timestamp DESC').fetchone()
        self.assertEqual((row['rx'], row['tx']), (10, 20))
        record(self.conn, 'web', 120, ('b', 1000, 1000), 2)
        self.assertIsNone(self.conn.execute('SELECT rx FROM port_samples WHERE timestamp=120').fetchone()[0])
        history = self.conn.execute("SELECT * FROM port_history WHERE resolution='day'").fetchone()
        self.assertEqual((history['incoming'], history['outgoing'], history['tcp_max']), (100, 200, 5))

    def test_missing_and_long_gap_are_not_zero(self):
        record(self.conn, 'web', 100, ('a', 100, 200), 0)
        record(self.conn, 'web', 200, ('a', 900, 900), None)
        record(self.conn, 'web', 210, None, None)
        self.assertEqual(self.conn.execute('SELECT COUNT(rx) FROM port_samples').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM port_state').fetchone()[0], 0)

    def test_only_local_server_endpoint_is_counted(self):
        output = '0 0 127.0.0.1:1638 127.0.0.1:40000\n0 0 127.0.0.1:40000 127.0.0.1:1638\n0 0 [::1]:1638 [::1]:40001\n'
        with patch('subprocess.run', return_value=SimpleNamespace(stdout=output)):
            self.assertEqual(connection_counts({1638}), {1638: 2})
