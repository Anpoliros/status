"""Adaptive scheduling never violates minimum spacing or multiplies requests."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from backend.status_monitor.config import load_config
from backend.status_monitor.scheduler import claim_due, connection, control_request, due_at, effective_interval, init_control


class SchedulerTests(unittest.TestCase):
    def test_intervals_and_pending_requests(self):
        self.assertEqual(effective_interval(10,300,[]),300)
        self.assertEqual(effective_interval(10,300,[600]),600)
        self.assertEqual(effective_interval(10,300,[60,23]),23)
        self.assertEqual(effective_interval(10,300,[5]),10)
        self.assertEqual(due_at(100,10,60,False),160)
        self.assertEqual(due_at(100,10,60,True),110)

    def test_multiple_pages_and_expiry(self):
        with tempfile.TemporaryDirectory() as temp:
            config = replace(load_config('configs/general.example.json'),database=Path(temp)/'test.db')
            init_control(config)
            first = {'page':'a'*20,'action':'connect','seconds':60}
            second = {'page':'b'*20,'action':'connect','seconds':5}
            control_request(config,'owner',first)
            result = control_request(config,'other',second)
            self.assertTrue(result['clamped'])
            self.assertEqual(result['effective_seconds'],10)
            with connection(config) as conn:
                conn.execute('UPDATE schedule SET last_started=100')
            self.assertFalse(claim_due(config,'servers',109))
            self.assertTrue(claim_due(config,'servers',110))
            self.assertFalse(claim_due(config,'servers',110))
            control_request(config,'other',dict(second,action='release'))
            self.assertEqual(control_request(config,'owner',dict(first,action='heartbeat'))['effective_seconds'],60)
            with self.assertRaises(ValueError):
                control_request(config,'intruder',first)

    def test_expired_leases_and_manual_refresh_do_not_keep_worker_active(self):
        with tempfile.TemporaryDirectory() as temp:
            config = replace(load_config('configs/general.example.json'),database=Path(temp)/'test.db')
            init_control(config)
            page = {'page':'c'*20,'action':'refresh','seconds':60}
            control_request(config,'owner',page)
            with connection(config) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM leases').fetchone()[0],0)
            control_request(config,'owner',dict(page,action='connect'))
            with connection(config) as conn:
                conn.execute('UPDATE leases SET expires=90')
                conn.execute('UPDATE schedule SET last_started=100,requested=0')
            self.assertFalse(claim_due(config,'servers',399))
            self.assertTrue(claim_due(config,'servers',400))
