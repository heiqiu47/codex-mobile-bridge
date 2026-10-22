import json
import ctypes
from ctypes import POINTER
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import bridge.features.network.addresses as network
import bridge.features.network.interfaces as interfaces
import bridge.platforms.macos.interfaces
import bridge.platforms.windows.interfaces
from bridge.app.desktop import Desktop
from bridge.features.network.runtime import DynamicListenerManager, RuntimeNetworkMonitor

ROOT = Path(__file__).resolve().parents[1]


ROWS = [
    {'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
    {'id': 'bridge', 'name': 'Bridge', 'addresses': ['192.168.1.7', '10.0.0.2']},
    {'id': 'VMnet8', 'name': 'VMnet8', 'addresses': ['192.168.55.1']},
    {'id': 'bridge100', 'name': 'bridge100', 'addresses': ['10.211.55.2']},
    {'id': 'public', 'name': 'public', 'addresses': ['203.0.113.7', '100.64.0.1']},
]


class InterfaceSelectionTests(unittest.TestCase):
    def test_addresses_are_deduplicated_by_interface_identity(self):
        self.assertEqual(interfaces._rows(ROWS), [
            {'id': 'bridge', 'name': 'Bridge', 'addresses': ['10.0.0.2', '192.168.1.7'],
             'index': None, 'if_type': None, 'virtual': False},
            {'id': 'bridge100', 'name': 'bridge100', 'addresses': ['10.211.55.2'],
             'index': None, 'if_type': None, 'virtual': False},
            {'id': 'public', 'name': 'public', 'addresses': ['100.64.0.1', '203.0.113.7'],
             'index': None, 'if_type': None, 'virtual': False},
            {'id': 'VMnet8', 'name': 'VMnet8', 'addresses': ['192.168.55.1'],
             'index': None, 'if_type': None, 'virtual': False},
            {'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7'],
             'index': None, 'if_type': None, 'virtual': False},
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
                         ['en0'])
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(ROWS, ['192.0.2.7']), [])
        self.assertIsNone(interfaces.migrate_addresses_to_interfaces(ROWS, None))
        ambiguous = [
            {'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
            {'id': 'eth0', 'name': 'Ethernet', 'addresses': ['192.168.1.7']},
        ]
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(ambiguous, ['192.168.1.7']), [])

    def test_virtual_interface_is_detected_by_name_type_or_token(self):
        self.assertTrue(interfaces.is_virtual_interface({'id': 'tun0', 'name': 'Tunnel'}))
        self.assertTrue(interfaces.is_virtual_interface({'id': 'Ethernet 2', 'name': 'Hyper-V Virtual Ethernet'}))
        self.assertTrue(interfaces.is_virtual_interface(
            {'id': 'guid', 'name': 'Ethernet', 'if_type': 53}))
        self.assertTrue(interfaces.is_virtual_interface({'id': 'vpn0', 'name': 'Corporate VPN'}))
        self.assertTrue(interfaces.is_virtual_interface({'id': 'tailscale0', 'name': 'Tailscale'}))
        self.assertFalse(interfaces.is_virtual_interface({'id': 'en0', 'name': 'Wi-Fi', 'if_type': 71}))

    def test_macos_parser_keeps_interface_identity_without_dns(self):
        output = ('lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n'
                  '\tinet 127.0.0.1 netmask 0xff000000\n'
                  'en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n'
                  '\tinet 192.168.1.7 netmask 0xffffff00\n')
        with patch('bridge.platforms.macos.interfaces.subprocess.run') as command, \
                patch('bridge.platforms.macos.interfaces.os.path.exists', return_value=True):
            command.return_value.stdout = output
            rows = bridge.platforms.macos.interfaces.enumerate_interfaces()
            self.assertEqual([row['id'] for row in rows if row['addresses']], ['lo0', 'en0'])
        self.assertEqual(next(row for row in rows if row['id'] == 'en0')['addresses'], ['192.168.1.7'])

    def test_windows_metadata_and_ipv4_socket_are_normalized(self):
        class SOCKADDR(ctypes.Structure):
            _fields_ = [('family', ctypes.c_ushort), ('data', ctypes.c_ubyte * 14)]
        raw = (SOCKADDR(),)
        raw[0].family = 2
        for index, byte in enumerate((10, 1, 2, 3), start=6):
            raw[0].data[index] = byte
        address = bridge.platforms.windows.interfaces.SOCKET_ADDRESS(
            bridge.platforms.windows.interfaces.POINTER(
                bridge.platforms.windows.interfaces.SOCKADDR)(raw[0]),
            ctypes.sizeof(SOCKADDR))
        self.assertEqual(bridge.platforms.windows.interfaces._ipv4(address), '10.1.2.3')
        raw[0].family = 23
        self.assertIsNone(bridge.platforms.windows.interfaces._ipv4(address))
        self.assertEqual(
            bridge.platforms.windows.interfaces._ipv4_number(0x0100007F), '127.0.0.1')
        self.assertTrue(interfaces.is_virtual_interface({'id': 'guid', 'name': 'Tunnel', 'if_type': 53}))
        self.assertFalse(interfaces.is_virtual_interface({'id': 'guid', 'name': 'Wi-Fi', 'if_type': 71}))

    def test_automatic_addresses_exclude_virtual_public_and_carrier_nat(self):
        self.assertEqual(interfaces.eligible_lan_addresses(ROWS), ['192.168.1.7'])
        self.assertTrue(interfaces.is_virtual_interface({'id': 'bridge100', 'name': 'bridge100'}))
        self.assertFalse(interfaces.is_virtual_interface({'id': 'en0', 'name': 'Wi-Fi'}))

    def test_bindings_keep_all_selected_empty_and_disabled_distinct(self):
        self.assertEqual(network.bindings({'lan': True}), ['127.0.0.1'])
        self.assertEqual(network.bindings({'lan': True, 'lanAddresses': []}), ['127.0.0.1'])
        self.assertEqual(network.bindings({'lan': True, 'lanInterfaces': None}, ROWS),
                         ['127.0.0.1', '192.168.1.7'])
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

    def test_dynamic_lan_update_preserves_local_http_origins(self):
        self.root.origins.update({'http://127.0.0.1:8787', 'http://localhost:8787'})
        self.root.hosts.update({'127.0.0.1:8787', 'localhost:8787'})
        active, _ = self.manager.apply(['192.168.1.7'])
        self.assertEqual(active, ['192.168.1.7'])
        self.assertEqual(
            self.root.origins,
            {'http://192.168.1.7:8787', 'http://127.0.0.1:8787',
             'http://localhost:8787', 'https://fixed.example'})
        self.assertEqual(
            self.root.hosts,
            {'192.168.1.7:8787', '127.0.0.1:8787', 'localhost:8787', 'fixed.example'})

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

    def test_failed_close_keeps_listener_active_for_retry(self):
        original = self.manager.server_factory
        entries = []
        def factory(address, *args, **kwargs):
            server = original(address, *args, **kwargs)
            entries.append(server)
            return server
        self.manager.server_factory = factory
        self.manager.apply(['192.168.1.7'])
        entries[0].shutdown = lambda: (_ for _ in ()).throw(OSError('busy'))
        self.manager.apply(['192.168.1.8'])
        active, error = self.manager.apply(['192.168.1.8'])
        self.assertEqual(sorted(active), ['192.168.1.7', '192.168.1.8'])
        self.assertIn('192.168.1.7', error)
        entries[0].shutdown = lambda: None
        active, error = self.manager.apply(['192.168.1.8'])
        self.assertEqual(active, ['192.168.1.8'])
        self.assertEqual(error, '')


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
            rows = [dict(row) for row in ROWS]
            next(row for row in rows if row['id'] == 'en0')['addresses'] = ['192.168.1.7']
            clock = iter([0, 2, 8, 10])
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': ['en0']},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            route_enumerator=lambda rows: {'fixture-route': True},
                                            clock=lambda: next(clock))
            self.assertEqual(monitor.scan(initial=True), ['192.168.1.7'])
            next(row for row in rows if row['id'] == 'en0')['addresses'] = ['192.168.1.8']
            self.assertEqual(monitor.scan(), ['192.168.1.7'])
            status = json.loads((Path(folder)/'network-status.json').read_text(encoding='utf-8'))
            self.assertFalse(status['stable'])
            self.assertEqual(status['pendingAddresses'], ['192.168.1.8'])
            self.assertEqual(manager.applied, [['192.168.1.7']])
            self.assertEqual(monitor.scan(), ['192.168.1.8'])
            monitor.close()
            self.assertFalse((Path(folder)/'network-status.json').exists())
            self.assertTrue(manager.closed)

    def test_unchanged_status_does_not_rewrite_disk_every_scan(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            rows = [dict(row) for row in ROWS]
            next(row for row in rows if row['id'] == 'en0')['addresses'] = ['192.168.1.7']
            clock = {'value': 0}
            def read_clock(): return clock['value']
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': ['en0']},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            route_enumerator=lambda rows: {'fixture-route': True},
                                            clock=read_clock)
            with patch('bridge.features.network.runtime._write_status') as write:
                monitor.scan(initial=True)
                self.assertEqual(write.call_count, 1)
                clock['value'] = 2
                monitor.scan()
                self.assertEqual(write.call_count, 2)
                clock['value'] = 50
                monitor.scan()
                self.assertEqual(write.call_count, 3)
            monitor.close()

    def test_stable_network_change_notifies_quick_tunnel_once(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            rows = [dict(row) for row in ROWS]
            next(row for row in rows if row['id'] == 'en0')['addresses'] = ['192.168.1.7']
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': ['en0']},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            route_enumerator=lambda rows: {'fixture-route': True},
                                            clock=lambda: 0)
            monitor.scan(initial=True)
            callbacks = []
            monitor.network_changed = lambda: callbacks.append(list(manager.active))
            rows[0]['addresses'] = ['192.168.1.8']
            monitor.clock = lambda: 2
            monitor.scan()
            self.assertEqual(callbacks, [])
            monitor.clock = lambda: 8
            monitor.scan()
            self.assertEqual(callbacks, [['192.168.1.8']])
            monitor.scan()
            self.assertEqual(len(callbacks), 1)
            monitor.close()

    def test_selected_offline_adapter_has_no_lan_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            rows = [{'id': 'en0', 'name': 'Wi-Fi', 'addresses': []},
                    {'id': 'eth0', 'name': 'Ethernet', 'addresses': ['192.168.2.7']}]
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': ['en0']},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            route_enumerator=lambda rows: {'fixture-route': True},
                                            clock=lambda: 0)
            self.assertEqual(monitor.scan(initial=True), [])
            monitor.close()

    def test_quick_tunnel_rebuild_uses_route_signature_not_published_scope(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            rows = [{'id': 'en0', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
                    {'id': 'bridge100', 'name': 'bridge100', 'addresses': ['10.211.55.2']}]
            route = {'type': 'default', 'interface': 'en0', 'gateway': '192.168.1.1'}
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanAddresses': []},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            route_enumerator=lambda rows: route, clock=lambda: 0)
            monitor.scan(initial=True)
            callbacks = []
            monitor.network_changed = lambda: callbacks.append(list(route))
            route['gateway'] = '192.168.0.1'
            monitor.clock = lambda: 2
            monitor.scan()
            self.assertEqual(callbacks, [])
            monitor.clock = lambda: 8
            monitor.scan()
            self.assertEqual(len(callbacks), 1)
            monitor.close()

    def test_automatic_mode_ignores_virtual_adapters(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as folder:
            manager = FakeRuntimeManager()
            rows = [dict(row) for row in ROWS]
            next(row for row in rows if row['id'] == 'en0')['addresses'] = ['192.168.1.7']
            monitor = RuntimeNetworkMonitor(folder, {'lan': True, 'lanInterfaces': None},
                                            8787, manager, 'instance', enumerator=lambda: rows,
                                            route_enumerator=lambda rows: {'fixture-route': True},
                                            clock=lambda: 0)
            self.assertEqual(monitor.scan(initial=True), ['192.168.1.7'])
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
