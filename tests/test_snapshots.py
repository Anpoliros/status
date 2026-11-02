"""Incremental history aggregation preserves mixed service outcomes."""
import sqlite3
import unittest
from datetime import UTC, datetime
from backend.status_monitor.db import init_db
from backend.status_monitor.snapshots import update_bins


class SnapshotTests(unittest.TestCase):
    def test_incremental_aggregation_does_not_double_count(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute("INSERT INTO services(name,url) VALUES ('A','https://a')")
        timestamp = datetime.now(UTC).isoformat()
        for status in ['up', 'down']:
            conn.execute('INSERT INTO service_checks(service_id,timestamp,status) VALUES (1,?,?)', (timestamp,status))
        update_bins(conn)
        update_bins(conn)
        row = conn.execute("SELECT * FROM history_bins WHERE resolution='day'").fetchone()
        self.assertEqual((row['healthy'],row['critical'],row['total']), (1,1,2))
        conn.execute('INSERT INTO service_checks(service_id,timestamp,status) VALUES (1,?,?)', (timestamp,'up'))
        update_bins(conn)
        self.assertEqual(conn.execute("SELECT total FROM history_bins WHERE resolution='day'").fetchone()[0], 3)
        conn.close()
