"""Optional SSH routing preserves machine identity and ordinary HTTP collection."""
import asyncio
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.status_monitor.config import load_config
from backend.status_monitor.collector import collect_server
from backend.status_monitor.db import connect, init_db
from backend.status_monitor.deploy_ssh import apply_units, planned_units, unit_prefix, validate_units
from backend.status_monitor.ssh_transport import collection_url, load_transport, render_unit, ssh_command


class SSHTransportTests(unittest.TestCase):
    def test_config_validation_and_instance_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            server = {'id': 'mml', 'target': '10.1.2.3:9100', 'transport': {'type': 'ssh', 'host': 'mml-ranges-jump'}}
            path.write_text(json.dumps({'servers': [server]}))
            config = load_config(path)
            first = config.servers[0]
            self.assertEqual(first.id, 'mml')
            self.assertEqual(first.target, server['target'])
            self.assertEqual(first.transport.host, 'mml-ranges-jump')
            units = planned_units(path, config.servers)
            self.assertEqual(len(units), 1)
            self.assertNotEqual(set(units), set(planned_units(path.with_name('other.json'), config.servers)))
            second = {**server, 'id': 'sp', 'target': '10.1.2.4:9100',
                      'transport': {**server['transport'], 'local_port': first.transport.local_port}}
            path.write_text(json.dumps({'servers': [server, second]}))
            with self.assertRaisesRegex(ValueError, 'Duplicate SSH local port'):
                load_config(path)
            del server['id']
            path.write_text(json.dumps({'servers': [server]}))
            with self.assertRaisesRegex(ValueError, 'explicit stable id'):
                load_config(path)

    def test_cleanup_only_removes_selected_instance_units(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config_path = base / 'general.json'
            unit_dir = base / 'systemd/user'
            unit_dir.mkdir(parents=True)
            stale = unit_dir / f'{unit_prefix(config_path)}old.service'
            other = unit_dir / f'{unit_prefix(base / "other.json")}keep.service'
            stale.write_text('old')
            other.write_text('keep')
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}), patch('backend.status_monitor.deploy_ssh.systemctl') as run:
                apply_units(config_path, {})
            self.assertFalse(stale.exists())
            self.assertEqual(other.read_text(), 'keep')
            self.assertEqual(run.call_args_list[0].args, ('disable', '--now', stale.name))

    def test_rejects_invalid_options_and_preserves_direct_urls(self):
        for options, target in [({'host': '-Fsecret'}, 'host:9100'), ({'host': 'alias', 'local_port': True}, 'host:9100'),
                                ({'host': 'alias'}, 'https://host:9100'), ({'host': 'alias', 'shell': 'cmd'}, 'host:9100')]:
            with self.subTest(options=options, target=target), self.assertRaises(ValueError):
                load_transport({'type': 'ssh', **options}, target, 'node', 'instance')
        for target, expected in [('node:9100', 'http://node:9100/metrics'),
                                 ('https://node/path?q=x', 'https://node/path?q=x')]:
            self.assertEqual(collection_url(target, None), expected)

    def test_systemd_unit_passes_real_parser(self):
        transport = load_transport({'type': 'ssh', 'host': 'example.org'}, '[::1]:9100', 'node', 'test')
        command = ssh_command('[::1]:9100', transport)
        self.assertIn(f'127.0.0.1:{transport.local_port}:[::1]:9100', command)
        self.assertIn('ControlPath=none', command)
        from types import SimpleNamespace
        server = SimpleNamespace(transport=transport)
        validate_units({'status-test-ssh.service': (render_unit('[::1]:9100', transport), server)})

    def test_http_over_forwarded_endpoint_and_failure_keep_original_identity(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'node_memory_MemAvailable_bytes 25\nnode_memory_MemTotal_bytes 100\n')
            def log_message(self, *args):
                pass
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.json'
                path.write_text(json.dumps({'servers': [{'id': 'mml', 'target': 'unreachable.invalid:9100',
                    'transport': {'type': 'ssh', 'host': 'alias', 'local_port': http.server_port}}]}))
                config = load_config(path)
                with connect(Path(directory) / 'test.db') as conn:
                    init_db(conn)
                    asyncio.run(collect_server(conn, config, config.servers[0]))
                    row = conn.execute('SELECT resource_id,ip,memory_usage FROM servers JOIN server_metrics ON servers.id=server_metrics.server_id').fetchone()
                    self.assertEqual(tuple(row), ('mml', 'unreachable.invalid:9100', 75))
                    with patch('backend.status_monitor.collector.fetch_text', side_effect=OSError('tunnel down')):
                        asyncio.run(collect_server(conn, config, config.servers[0]))
                    self.assertIsNone(conn.execute('SELECT memory_usage FROM server_metrics ORDER BY id DESC LIMIT 1').fetchone()[0])
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM servers').fetchone()[0], 1)
        finally:
            http.shutdown()
            http.server_close()
            thread.join()
