import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import bridge.features.network.addresses as network
import bridge.features.network.interfaces as interfaces
from bridge.app.desktop import Desktop
from bridge.features.network.runtime import DynamicListenerManager, RuntimeNetworkMonitor

ROOT = Path(__file__).resolve().parents[1]


ROWS = [
    {'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
    {'id': 'bridge', 'name': 'Bridge', 'addresses': ['192.168.1.7', '10.0.0.2']},
    {'id': 'VMnet8', 'name': 'VMnet8', 'addresses': ['192.168.55.1']},
]


class InterfaceSelectionTests(unittest.TestCase):
    def test_addresses_are_deduplicated_by_interface_identity(self):
        self.assertEqual(interfaces._rows(ROWS), [
            {'id': 'bridge', 'name': 'Bridge', 'addresses': ['10.0.0.2', '192.168.1.7']},
            {'id': 'VMnet8', 'name': 'VMnet8', 'addresses': ['192.168.55.1']},
            {'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
        ])

    def test_invalid_and_unusable_addresses_are_not_selections(self):
        self.assertIsNone(interfaces.selected_interfaces(None))
        self.assertEqual(interfaces.selected_interfaces([]), [])
        for value in ([1], [''], ['x'*257]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                interfaces.selected_interfaces(value)
        self.assertEqual(interfaces.selected_interfaces(['en0', 'en0']), ['en0'])

    def test_legacy_address_migration_uses_the_current_owner(self):
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(ROWS, ['192.168.1.7']),
                         ['en0', 'bridge'])
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(ROWS, ['192.0.2.7']), [])
        self.assertIsNone(interfaces.migrate_addresses_to_interfaces(ROWS, None))

    def test_bindings_keep_all_selected_empty_and_disabled_distinct(self):
        self.assertEqual(network.bindings({'lan': True}), ['0.0.0.0'])
        self.assertEqual(network.bindings({'lan': True, 'lanAddresses': []}), ['127.0.0.1'])
        self.assertEqual(network.bindings({'lan': True, 'lanInterfaces': None}), ['0.0.0.0'])
        self.assertEqual(network.bindings({'lan': True, 'lanInterfaces': []}), ['127.0.0.1'])
        self.assertEqual(network.bindings({'lan': True, 'lanInterfaces': ['en0']}, ROWS),
                         ['127.0.0.1', '192.168.1.7'])
        self.assertEqual(network.bindings({'lan': False, 'lanInterfaces': ['en0']}, ROWS),
                         ['127.0.0.1'])


class FakeServer:
    def __init__(self, address, *args, **kwargs):
        self.address = address[0]
        self.closed = False

    def serve_forever(self, **kwargs):
        pass

    def shutdown(self):
        self.closed = True

    def server_close(self):
        self.server_closed = True


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.root = type('Root', (), {})()
        self.root.origins = {'http://9.0.0.1:8787', 'https://fixed.example'}
        self.root.hosts = {'9.0.0.1:8787', 'fixed.example'}
        self.manager = DynamicListenerManager(self.root, 8787, None, {}, '/web', FakeServer)

    def tearDown(self):
        self.manager.close()

    def test_selected_adapter_listeners_follow_addresses_and_own_only_http_origins(self):
        active, error = self.manager.apply(['192.168.1.7'])
        self.assertEqual(active, ['192.168.1.7'])
        self.assertEqual(error, '')
        self.assertIn('http://192.168.1.7:8787', self.root.origins)
        self.assertNotIn('http://9.0.0.1:8787', self.root.origins)
        self.assertIn('https://fixed.example', self.root.origins)
        active, _ = self.manager.apply(['192.168.1.8'])
        self.assertEqual(active, ['192.168.1.8'])
        self.assertNotIn('http://192.168.1.7:8787', self.root.origins)
        self.assertIn('http://192.168.1.8:8787', self.root.origins)
        self.assertEqual([entry[0].address for entry in self.manager.listeners.values()],
                         ['192.168.1.8'])

    def test_bind_failure_never_publishes_or_expands_the_failed_address(self):
        original = self.manager.server_factory
        def fail_new(address, *args, **kwargs):
            if address[0] == '192.0.2.9':
                raise OSError('unavailable')
            return original(address, *args, **kwargs)
        self.manager.server_factory = fail_new
        active, _ = self.manager.apply(['192.168.1.7'])
        active, error = self.manager.apply(['192.0.2.9'])
        self.assertEqual(active, ['192.168.1.7'])
        self.assertIn('192.0.2.9', error)
        self.assertNotIn('http://192.0.2.9:8787', self.root.origins)


class FakeRuntimeManager:
    def __init__(self):
        self.applied = []
        self.active = []
        self.closed = False

    def apply(self, addresses):
        self.applied.append(list(addresses))
        self.active = list(addresses)
        return list(addresses), ''

    def addresses(self):
        return list(self.active)

    def error_message(self):
        return ''

    def close(self):
        self.closed = True


class RuntimeMonitorTests(unittest.TestCase):
    def test_changes_wait_for_stability_and_publish_only_the_stable_set(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            clock = iter([0, 2, 8, 10])
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': ['en0']},
                                            8787, manager, 'instance', enumerator=lambda: ROWS,
                                            clock=lambda: next(clock))
            self.assertEqual(monitor.scan(initial=True), ['192.168.1.7'])
            ROWS[0]['addresses'] = ['192.168.1.8']
            self.assertEqual(monitor.scan(), ['192.168.1.7'])
            status = json.loads((Path(folder)/'network-status.json').read_text(encoding='utf-8'))
            self.assertFalse(status['stable'])
            self.assertEqual(status['pendingAddresses'], ['192.168.1.8'])
            self.assertEqual(manager.applied, [['192.168.1.7']])
            self.assertEqual(monitor.scan(), ['192.168.1.8'])
            monitor.close()
            self.assertFalse((Path(folder)/'network-status.json').exists())
            self.assertTrue(manager.closed)

    def test_selected_offline_adapter_has_no_lan_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            rows = [{'id': 'en0', 'name': 'Wi-Fi', 'addresses': []},
                    {'id': 'eth0', 'name': 'Ethernet', 'addresses': ['192.168.2.7']}]
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': ['en0']},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            clock=lambda: 0)
            self.assertEqual(monitor.scan(initial=True), [])
            monitor.close()


class EntryTests(unittest.TestCase):
    def test_dynamic_addresses_filter_even_when_legacy_addresses_remain(self):
        prefs = {'port': 8787, 'lan': True, 'lanAddresses': ['192.0.2.9'], 'connections': []}
        self.assertEqual(network.bindings({'lan': True, 'lanInterfaces': ['en0']}, ROWS),
                         ['127.0.0.1', '192.168.1.7'])
        from bridge.features.notifications.addresses import entry_urls
        self.assertEqual(
            entry_urls(prefs, ['127.0.0.1', 'localhost', '192.168.1.7', '192.0.2.9'],
                       lan_addresses=['192.168.1.7']),
            ['http://192.168.1.7:8787'])


class DesktopRuntimeTests(unittest.TestCase):
    def test_running_snapshot_uses_gateway_adapter_state_not_a_stale_saved_ip(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            desktop = Desktop(folder)
            desktop.status = lambda: {'running': True, 'pid': 100, 'instanceId': 'live',
                                      'supportsNotifications': True}
            (Path(folder)/'desktop.json').write_text(json.dumps({
                'port': 8787, 'lan': True, 'lanInterfaces': ['en0'],
                'lanAddresses': ['192.0.2.9'], 'codexHome': folder,
            }), encoding='utf-8')
            (Path(folder)/'network-status.json').write_text(json.dumps({
                'pid': 100, 'instanceId': 'live', 'mode': 'selected',
                'selectedInterfaces': ['en0'],
                'interfaces': [{'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.8']}],
                'addresses': ['192.168.1.8'],
            }), encoding='utf-8')
            with patch('bridge.app.desktop.interfaces.enumerate_interfaces',
                       return_value=[{'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.0.2.9']}]):
                value = desktop.snapshot()
            self.assertIn('http://192.168.1.8:8787/', value['urls'])
            self.assertNotIn('http://192.0.2.9:8787/', value['urls'])
            self.assertEqual(value['notificationUrls'], ['http://192.168.1.8:8787'])
            self.assertEqual(value['networkStatus']['addresses'], ['192.168.1.8'])
