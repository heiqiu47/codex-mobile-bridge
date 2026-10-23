"""Opt-in control, persistence and public-entry safety regressions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_bridge as support
from bridge.app.desktop import Desktop
from bridge.features.network.adaptation import NetworkAdaptation, settings

ROOT = Path(__file__).resolve().parents[1]


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.directory = Path(self.temp.name)
        self.monitor = Mock()
        self.monitor.status.return_value = {'enabled': False, 'addresses': []}
        self.control = NetworkAdaptation(self.directory, self.monitor)

    def tearDown(self):
        self.temp.cleanup()

    def test_old_profiles_default_off_and_status_does_not_create_settings(self):
        self.assertEqual(settings(self.directory), {'enabled': False})
        self.assertFalse(self.control.control({'action': 'status'})['enabled'])
        self.assertFalse((self.directory / 'network-adaptation.json').exists())
        self.monitor.set_enabled.assert_not_called()

    def test_only_boolean_explicit_writes_persist_and_reach_monitor(self):
        for value in ({'action': 'set', 'enabled': True}, {'action': 'set', 'enabled': False}):
            self.control.control(value)
            self.assertEqual(settings(self.directory)['enabled'], value['enabled'])
            self.monitor.set_enabled.assert_called_with(value['enabled'])
        for value in ({}, {'enabled': True}, {'action': 'set', 'enabled': 1},
                      {'action': 'set', 'enabled': True, 'extra': True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.control.control(value)
        self.assertEqual(self.monitor.set_enabled.call_count, 2)

    def test_runtime_failure_rolls_back_persisted_setting(self):
        self.monitor.set_enabled.side_effect = OSError('watcher unavailable')
        with self.assertRaises(OSError):
            self.control.control({'action': 'set', 'enabled': True})
        self.assertFalse(settings(self.directory)['enabled'])

    def test_stopped_desktop_setting_never_activates_clients(self):
        desktop = Desktop(self.directory)
        desktop.status = lambda: {'running': False, 'portOccupied': False}
        with patch.object(desktop, 'local_services', side_effect=AssertionError('activated')):
            result = desktop.network_adaptation({'action': 'set', 'enabled': True})
        self.assertEqual(result, {'enabled': True, 'running': False})
        self.assertTrue(settings(self.directory)['enabled'])

    def test_live_write_failure_does_not_fall_back_to_disk_or_replay(self):
        desktop = Desktop(self.directory)
        desktop.status = lambda: {'running': True}
        with patch('bridge.app.desktop.read_record', return_value={'networkAdaptationManagement': True}), \
                patch('bridge.app.desktop.request_pairing', side_effect=ValueError('unknown')) as request:
            with self.assertRaises(ValueError):
                desktop.network_adaptation({'action': 'set', 'enabled': True})
        request.assert_called_once()
        self.assertFalse((self.directory / 'network-adaptation.json').exists())

    def test_bound_addresses_win_over_detected_pending_addresses(self):
        desktop = Desktop(self.directory)
        desktop.status = lambda: {'running': True, 'pid': 12, 'instanceId': 'owned'}
        (self.directory / 'desktop.json').write_text(json.dumps({
            'port': 8787, 'lan': True, 'lanInterfaces': ['en0'], 'codexHome': str(self.directory)}))
        (self.directory / 'network-status.json').write_text(json.dumps({
            'pid': 12, 'instanceId': 'owned', 'mode': 'selected', 'enabled': True,
            'interfaces': [{'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.8']}],
            'addresses': ['192.168.1.7'], 'pendingAddresses': ['192.168.1.8'],
            'stable': False, 'error': 'bind failed'}))
        with patch('bridge.app.desktop.interfaces.enumerate_interfaces', side_effect=AssertionError('poll')):
            result = desktop.snapshot()
        self.assertIn('http://192.168.1.7:8787/', result['urls'])
        self.assertNotIn('http://192.168.1.8:8787/', result['urls'])
        self.assertEqual(result['notificationUrls'], ['http://192.168.1.7:8787'])

    def test_other_instance_status_never_advertises_unconfirmed_addresses(self):
        desktop = Desktop(self.directory)
        desktop.status = lambda: {'running': True, 'pid': 12, 'instanceId': 'current'}
        (self.directory / 'network-status.json').write_text(json.dumps({
            'pid': 12, 'instanceId': 'old', 'mode': 'all', 'addresses': ['192.168.1.7']}))
        with patch('bridge.app.desktop.interfaces.enumerate_interfaces', return_value=[
                {'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.8']}]):
            result = desktop.snapshot()
        self.assertEqual(result['urls'], ['http://127.0.0.1:8787/'])
        self.assertEqual(result['notificationUrls'], [])


class ControlHttpTests(unittest.TestCase):
    setUpClass = classmethod(support.HttpTests.setUpClass.__func__)
    tearDown = support.HttpTests.tearDown
    request = support.HttpTests.request
    login = support.HttpTests.login

    def setUp(self):
        support.HttpTests.setUp(self)
        self.server.network_adaptation = Mock()
        self.server.network_adaptation.public.return_value = {'enabled': False}
        self.server.network_adaptation.control.return_value = {'enabled': True}

    def test_authenticated_read_and_csrf_write(self):
        route = '/api/network-adaptation'
        self.assertEqual(self.request('GET', route)[0], 401)
        self.assertEqual(self.request('POST', route, {'enabled': True})[0], 401)
        headers = self.login()
        self.assertEqual(self.request('GET', route, headers=headers)[2], {'enabled': False, 'canEdit': True})
        self.assertEqual(self.request('POST', route, {'enabled': True}, {'Cookie': headers['Cookie']})[0], 403)
        self.assertEqual(self.request('POST', route, {'enabled': True}, headers)[2], {'enabled': True, 'canEdit': True})
        self.server.network_adaptation.control.assert_called_once_with({'action': 'set', 'enabled': True})

    def test_query_extra_fields_and_wrong_origin_cannot_write(self):
        route = '/api/network-adaptation'
        headers = self.login()
        self.assertEqual(self.request('POST', route + '?enabled=1', {'enabled': True}, headers)[0], 400)
        self.assertEqual(self.request('POST', route, {'enabled': True, 'extra': True}, headers)[0], 400)
        self.assertEqual(self.request('POST', route, {'enabled': True}, {**headers, 'Origin': 'https://foreign.example'})[0], 403)
        self.server.network_adaptation.control.assert_not_called()

    def test_passwordless_read_only(self):
        self.server.auth.config['mode'] = 'none'
        headers = self.login()
        self.assertFalse(self.request('GET', '/api/network-adaptation', headers=headers)[2]['canEdit'])
        self.assertEqual(self.request('POST', '/api/network-adaptation', {'enabled': True}, headers)[0], 403)
        self.server.network_adaptation.control.assert_not_called()
