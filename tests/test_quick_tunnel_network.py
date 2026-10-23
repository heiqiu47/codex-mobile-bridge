"""Local, isolated recovery checks; never call Cloudflare or a real gateway."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bridge.features.network.tunnel import QuickTunnel

ROOT = Path(__file__).resolve().parents[1]


class QuickTunnelNetworkTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(self.folder.cleanup)
        self.now = 0
        self.tunnel = QuickTunnel(Path(self.folder.name)/'cloudflared', 8787,
                                  self.folder.name, MagicMock(), clock=lambda: self.now)
        self.process = MagicMock()
        self.process.poll.return_value = None
        self.tunnel.process = self.process
        self.tunnel.metrics_port = 43210
        self.tunnel.url = 'https://existing.trycloudflare.com'
        self.tunnel.ready.set()
        self.addCleanup(self.tunnel.close)

    def test_healthy_tunnel_keeps_url_ready_and_process_after_route_change(self):
        with patch.object(self.tunnel, '_local_readiness', return_value=True) as ready:
            self.assertTrue(self.tunnel.network_changed())
            self.tunnel._check_network_recovery()
            ready.assert_not_called()
            self.now = 15
            self.tunnel._check_network_recovery()
            ready.assert_called_once_with(43210)
            self.now = 60
            self.tunnel._check_network_recovery()
            self.assertEqual(ready.call_count, 1)
        self.assertTrue(self.tunnel.entry_stable())
        self.assertEqual(self.tunnel.url, 'https://existing.trycloudflare.com')
        self.process.terminate.assert_not_called()

    def test_two_explicit_failures_after_grace_trigger_recovery_with_cooldown(self):
        with patch.object(self.tunnel, '_local_readiness', return_value=False) as ready:
            self.tunnel.network_changed()
            self.now = 15
            self.tunnel._check_network_recovery()
            self.assertTrue(self.tunnel.entry_stable())
            self.now = 24
            self.tunnel._check_network_recovery()
            self.assertEqual(ready.call_count, 1)
            self.now = 25
            self.tunnel._check_network_recovery()
            self.assertTrue(self.tunnel.broken.is_set())
            self.assertFalse(self.tunnel.entry_stable())
            self.tunnel.network_changed()
            self.now = 50
            self.tunnel._check_network_recovery()
            self.assertEqual(ready.call_count, 2)

    def test_transient_failure_then_recovery_does_not_replace(self):
        with patch.object(self.tunnel, '_local_readiness', side_effect=[False, True]):
            self.tunnel.network_changed()
            for self.now in (15, 25):
                self.tunnel._check_network_recovery()
        self.assertTrue(self.tunnel.entry_stable())
        self.assertIsNone(self.tunnel._network_due)

    def test_unknown_metrics_are_bounded_and_do_not_prove_tunnel_failure(self):
        with patch.object(self.tunnel, '_local_readiness', return_value=None) as ready:
            self.tunnel.network_changed()
            for self.now in (15, 25, 35, 45):
                self.tunnel._check_network_recovery()
            self.assertEqual(ready.call_count, 3)
        self.assertTrue(self.tunnel.entry_stable())
        self.assertIsNone(self.tunnel._network_due)

    def test_disable_cancels_pending_and_inflight_health_result(self):
        with patch.object(self.tunnel, '_local_readiness', return_value=False) as ready:
            self.tunnel.network_changed()
            self.tunnel.cancel_network_check()
            self.now = 15
            self.tunnel._check_network_recovery()
            ready.assert_not_called()
        self.tunnel.network_changed()
        self.now = 30
        self.tunnel._network_failures = 1
        def disable(port):
            self.tunnel.cancel_network_check()
            return False
        with patch.object(self.tunnel, '_local_readiness', side_effect=disable):
            self.tunnel._check_network_recovery()
        self.assertTrue(self.tunnel.entry_stable())

    def test_replacement_process_cannot_receive_old_health_result(self):
        self.tunnel.network_changed()
        self.now = 15
        self.tunnel._network_failures = 1
        def replace(port):
            self.tunnel.process = MagicMock(poll=lambda: None)
            return False
        with patch.object(self.tunnel, '_local_readiness', side_effect=replace):
            self.tunnel._check_network_recovery()
        self.assertTrue(self.tunnel.entry_stable())

    def test_metrics_endpoint_comes_from_owned_process_loopback_log_only(self):
        self.tunnel.metrics_port = None
        self.process.stdout = io.StringIO(
            'Starting metrics server on 203.0.113.1:3333/metrics\n'
            'Starting metrics server on 127.0.0.1:43211/metrics\n')
        self.tunnel._read(self.process)
        self.assertEqual(self.tunnel.metrics_port, 43211)
        stale = MagicMock(stdout=io.StringIO('Starting metrics server on 127.0.0.1:1234/metrics\n'))
        self.tunnel._read(stale)
        self.assertEqual(self.tunnel.metrics_port, 43211)

    def test_local_health_has_no_proxy_redirect_or_public_host(self):
        for status, body, expected in ((200, {'readyConnections': 1}, True),
                                      (503, {'readyConnections': 0}, False),
                                      (302, {'readyConnections': 0}, None),
                                      (200, {}, None)):
            response = MagicMock(status=status)
            response.read.return_value = json.dumps(body).encode()
            with self.subTest(status=status, body=body), \
                    patch('bridge.features.network.tunnel.http.client.HTTPConnection') as connection:
                connection.return_value.getresponse.return_value = response
                self.assertIs(self.tunnel._local_readiness(43210), expected)
                connection.assert_called_once_with('127.0.0.1', 43210, timeout=2)
                connection.return_value.request.assert_called_once_with('GET', '/ready')
                connection.return_value.close.assert_called_once()
