"""Managed Prometheus metrics use stable IDs and local display metadata."""
import asyncio
import sqlite3
import unittest
from dataclasses import replace
from unittest.mock import patch
from backend.status_monitor.collector import collect_prometheus_servers
from backend.status_monitor.collectors import PrometheusConfig
from backend.status_monitor.config import ServerConfig
from backend.status_monitor.db import init_db
import test_status


class ManagedCollectionTests(unittest.TestCase):
    def test_local_name_cluster_and_id_survive_metric_aggregation(self):
        fixture = test_status.StatusTests();fixture.setUp()
        machine = ServerConfig('142','10.1.2.142:9100','local-cluster','ali-ecs-142')
        source = PrometheusConfig('http://prometheus:9090','nodes',id='ali',servers=(machine,))
        expressions = []
        def query(source, expression, timeout):
            expressions.append(expression)
            return {'ali-ecs-142':1 if expression.startswith('up{') else 25}
        with patch('backend.status_monitor.collector._query_metric',side_effect=query), patch('backend.status_monitor.collector.discover_prometheus_servers',side_effect=AssertionError('Must use local inventory')):
            asyncio.run(collect_prometheus_servers(fixture.connection,fixture.config,source))
        row = fixture.connection.execute('SELECT * FROM servers').fetchone()
        self.assertEqual((row['resource_id'],row['name'],row['cluster']),('ali-ecs-142','142','local-cluster'))
        self.assertEqual(fixture.connection.execute('SELECT cpu_usage FROM server_metrics').fetchone()[0],25)
        self.assertTrue(any('by(status_id)' in expression for expression in expressions))
        self.assertTrue(all('[5m]' in expression for expression in expressions if 'node_network_' in expression))
        fixture.tearDown()
