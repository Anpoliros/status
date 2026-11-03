"""Database machine IDs survive renames, endpoint moves and archival."""
import sqlite3
import unittest
from dataclasses import replace
from backend.status_monitor.config import ServerConfig
from backend.status_monitor.db import init_db, upsert_server, sync_config
import test_status


class IdentityTests(unittest.TestCase):
    def test_adopt_legacy_and_move_without_losing_history(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute("INSERT INTO servers(name,ip,cluster) VALUES ('old','node:9100','old')")
        original = conn.execute('SELECT id FROM servers').fetchone()[0]
        conn.execute("INSERT INTO server_metrics(server_id,timestamp,cpu_usage) VALUES (?,'2026-01-01',20)",(original,))
        machine = ServerConfig('142','node:9100','compute','ali-ecs-142')
        self.assertEqual(upsert_server(conn,machine),original)
        moved = replace(machine,name='new name',target='new-node:9100',cluster='other')
        self.assertEqual(upsert_server(conn,moved),original)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM server_metrics').fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,'Machine ID changed'):
            upsert_server(conn,replace(moved,id='other-id'))
        fixture = test_status.StatusTests();fixture.setUp()
        sync_config(conn,replace(fixture.config,servers=[]))
        self.assertEqual(conn.execute('SELECT active FROM servers').fetchone()[0],0)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM server_metrics').fetchone()[0],1)
        fixture.tearDown();conn.close()
