import ctypes
import socket
import struct
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bridge.features.network.addresses as network
import bridge.features.network.interfaces as interfaces
from bridge.platforms.windows import interfaces as windows
from bridge.platforms.macos import interfaces as macos
from bridge.platforms.linux import interfaces as linux
import bridge.platforms.macos.interfaces
import bridge.platforms.windows.interfaces

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
            {'id': 'guid', 'name': 'Ethernet', 'if_type': 131}))
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
        for index, byte in enumerate((10, 1, 2, 3), start=2):
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
        adapter = bridge.platforms.windows.interfaces._IP_ADAPTER_ADDRESSES_LH()
        adapter.Alignment.IfIndex = 7
        adapter.IfType = 6
        self.assertEqual(adapter.Alignment.IfIndex, 7)
        self.assertEqual(adapter.IfType, 6)
        self.assertTrue(interfaces.is_virtual_interface({'id': 'guid', 'name': 'Tunnel', 'if_type': 131}))
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



class InterfaceMigrationTests(unittest.TestCase):
    def test_two_selected_networks_retain_both_unique_owners(self):
        rows = [
            {'id': 'wifi', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
            {'id': 'ethernet', 'name': 'Ethernet', 'addresses': ['10.1.2.3']},
            {'id': 'unused', 'name': 'Other', 'addresses': ['172.16.1.2']},
        ]
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(
            rows, ['192.168.1.7', '10.1.2.3', '192.168.1.7']), ['wifi', 'ethernet'])

    def test_missing_or_ambiguous_owner_never_selects_unrelated_network(self):
        rows = [
            {'id': 'wifi', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
            {'id': 'other', 'name': 'Ethernet', 'addresses': ['192.168.1.7']},
        ]
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(rows, []), [])
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(rows, ['192.168.1.7']), [])
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(rows, ['10.1.2.3']), [])

    def test_multiple_virtual_mirrors_prefer_each_unique_physical_owner(self):
        rows = [
            {'id': 'wifi', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
            {'id': 'ethernet', 'name': 'Ethernet', 'addresses': ['10.1.2.3']},
            {'id': 'bridge0', 'name': 'Bridge', 'addresses': ['192.168.1.7', '10.1.2.3']},
        ]
        self.assertEqual(interfaces.migrate_addresses_to_interfaces(
            rows, ['192.168.1.7', '10.1.2.3']), ['wifi', 'ethernet'])

    def test_default_route_signature_ignores_other_lan_and_missing_route(self):
        rows = [
            {'id': 'wifi', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7'], 'index': 7},
            {'id': 'ethernet', 'name': 'Ethernet', 'addresses': ['10.1.2.3'], 'index': 8},
        ]
        route = {'type': 'default', 'index': 7, 'gateway': '192.168.1.1'}
        first = interfaces.network_signature(rows, route)
        rows[1]['addresses'] = ['10.1.2.4']
        self.assertEqual(interfaces.network_signature(rows, route), first)
        self.assertEqual(interfaces.network_signature(rows, {}), {'route': {}, 'interfaces': []})


class WindowsAbiTests(unittest.TestCase):
    def test_sockaddr_bytes_use_real_windows_abi(self):
        # Byte offsets come from SOCKADDR_IN: family(2), port(2), IPv4(4), zero(8).
        raw = ctypes.create_string_buffer(b'\x02\x00\x22\x53\x0a\x15\x9a\xab' + b'\0'*8)
        address = windows.SOCKET_ADDRESS(ctypes.cast(raw, ctypes.POINTER(windows.SOCKADDR)), 16)
        self.assertEqual(windows._ipv4(address), '10.21.154.171')
        address.iSockaddrLength = 8
        self.assertIsNone(windows._ipv4(address))

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, 'x64/arm64 ABI fixture')
    def test_adapter_header_index_and_unicast_fields_match_fixed_width_abi(self):
        raw = ctypes.create_string_buffer(448)
        struct.pack_into('<II', raw, 0, 448, 7)
        struct.pack_into('<I', raw, 100, 6)  # IfType, not host unsigned-long size.
        adapter = ctypes.cast(raw, ctypes.POINTER(windows._IP_ADAPTER_ADDRESSES_LH)).contents
        self.assertEqual(adapter.Alignment.Length, 448)
        self.assertEqual(adapter.Alignment.IfIndex, 7)
        self.assertEqual(adapter.IfType, 6)
        self.assertEqual(windows._IP_ADAPTER_ADDRESSES_LH.Next.offset, 8)
        self.assertEqual(windows.IP_ADAPTER_UNICAST_ADDRESS_LH.Address.offset, 16)
        self.assertEqual(windows.IP_ADAPTER_UNICAST_ADDRESS_LH.PrefixOrigin.offset, 32)
        self.assertEqual(windows.IP_ADAPTER_UNICAST_ADDRESS_LH.ValidLifetime.offset, 44)
        self.assertEqual(ctypes.sizeof(windows.MIB_IPFORWARDROW), 56)
        self.assertTrue(interfaces.is_virtual_interface({'id': '{GUID}', 'name': 'Ethernet', 'if_type': 131}))
        self.assertFalse(interfaces.is_virtual_interface({'id': '{GUID}', 'name': 'Ethernet', 'if_type': 53}))

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, 'x64/arm64 ABI fixture')
    def test_get_adapters_parses_abi_fixture_not_production_struct_assignments(self):
        # Construct API-returned bytes independently, including pointed-to data.
        raw_adapter = ctypes.create_string_buffer(448)
        raw_unicast = ctypes.create_string_buffer(64)
        raw_address = ctypes.create_string_buffer(b'\x02\x00\0\0\x0a\x15\x9a\xab' + b'\0'*8)
        name = ctypes.create_string_buffer(b'{WIFI-GUID}')
        friendly = ctypes.create_unicode_buffer('Wi-Fi')
        struct.pack_into('<II', raw_adapter, 0, 448, 7)
        struct.pack_into('<Q', raw_adapter, 16, ctypes.addressof(name))
        struct.pack_into('<Q', raw_adapter, 24, ctypes.addressof(raw_unicast))
        struct.pack_into('<Q', raw_adapter, 72, ctypes.addressof(friendly))
        struct.pack_into('<I', raw_adapter, 100, 71)
        struct.pack_into('<II', raw_unicast, 0, 64, 0)
        struct.pack_into('<Qi', raw_unicast, 16, ctypes.addressof(raw_address), 16)

        def get_adapters(_family, _flags, _reserved, address, size):
            ctypes.cast(size, ctypes.POINTER(ctypes.c_uint32)).contents.value = 448
            if not address:
                return 111
            ctypes.memmove(address, raw_adapter, 448)
            return 0

        library = SimpleNamespace(GetAdaptersAddresses=Mock(side_effect=get_adapters))
        with patch.object(windows.ctypes, 'windll', SimpleNamespace(iphlpapi=library), create=True):
            self.assertEqual(windows.enumerate_interfaces(), [{
                'id': '{WIFI-GUID}', 'name': 'Wi-Fi', 'addresses': ['10.21.154.171'],
                'index': 7, 'if_type': 71,
            }])


class WindowsWatcherTests(unittest.TestCase):
    def library(self, fail_second=False):
        self.callbacks = []
        def register(_family, callback, _context, initial, handle):
            self.assertFalse(initial)
            self.callbacks.append(callback)
            if fail_second and len(self.callbacks) == 2:
                return 50
            ctypes.cast(handle, ctypes.POINTER(ctypes.c_void_p)).contents.value = len(self.callbacks)
            return 0
        return SimpleNamespace(
            NotifyUnicastIpAddressChange=Mock(side_effect=register),
            NotifyRouteChange2=Mock(side_effect=register),
            CancelMibChangeNotify2=Mock(return_value=0))

    def test_native_address_and_route_notifications_stop_after_close(self):
        library, changed = self.library(), Mock()
        watcher = windows._NetworkWatcher(library, changed, lambda fn: fn)
        for callback in self.callbacks:
            callback(None, None, 1)
        self.assertEqual(changed.call_count, 2)
        watcher.close()
        watcher.close()
        self.assertEqual(library.CancelMibChangeNotify2.call_count, 2)
        for callback in self.callbacks:
            callback(None, None, 1)
        self.assertEqual(changed.call_count, 2)

    def test_second_registration_failure_cancels_first(self):
        library = self.library(fail_second=True)
        with self.assertRaises(OSError):
            windows._NetworkWatcher(library, Mock(), lambda fn: fn)
        self.assertEqual(library.CancelMibChangeNotify2.call_count, 1)

    def test_close_waits_for_inflight_callback_without_holding_cancel_lock(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        def changed():
            entered.set()
            release.wait(2)
        library = self.library()
        watcher = windows._NetworkWatcher(library, changed, lambda fn: fn)
        worker = threading.Thread(target=lambda: self.callbacks[0](None, None, 1))
        worker.start()
        self.assertTrue(entered.wait(1))
        closer = threading.Thread(target=lambda: (watcher.close(), closed.set()))
        closer.start()
        self.assertFalse(closed.wait(.05))
        release.set()
        self.assertTrue(closed.wait(1))
        worker.join(1)
        closer.join(1)
        self.assertEqual(library.CancelMibChangeNotify2.call_count, 2)


    def test_unavailable_os_notification_returns_none(self):
        with patch.object(windows.ctypes, 'windll', SimpleNamespace(iphlpapi=SimpleNamespace()), create=True):
            self.assertIsNone(windows.watch_changes(Mock()))


class WatcherDispatchTests(unittest.TestCase):
    def test_dispatch_and_unavailable_fallback(self):
        changed = Mock()
        module = SimpleNamespace(watch_changes=Mock(return_value='watcher'))
        with patch.object(interfaces, '_platform_module', return_value=module):
            self.assertEqual(interfaces.watch_changes(changed), 'watcher')
            module.watch_changes.assert_called_once_with(changed)
            module.watch_changes.side_effect = OSError('unavailable')
            self.assertIsNone(interfaces.watch_changes(changed))
        with patch.object(interfaces, '_platform_module', return_value=None):
            self.assertIsNone(interfaces.watch_changes(changed))


class NativeSocketEventTests(unittest.TestCase):
    def test_macos_network_changes_ignore_queries_and_neighbors(self):
        def event(kind, flags=0, version=5):
            return struct.pack('=HBBHHI', 12, version, kind, 7, 0, flags)
        for kind in (1, 2, 3, 6, 12, 13, 14, 18):
            with self.subTest(kind=kind):
                self.assertTrue(macos._network_event(event(kind)))
        for kind in (4, 7, 11, 15, 16, 20):
            with self.subTest(kind=kind):
                self.assertFalse(macos._network_event(event(kind)))
        self.assertFalse(macos._network_event(event(1, 0x400)))
        self.assertFalse(macos._network_event(event(1, version=4)))
        self.assertFalse(macos._network_event(b'\0\0'))
        self.assertTrue(macos._network_event(event(4) + event(12)))

    def test_linux_batch_alignment_filters_noise(self):
        def event(kind, payload=b''):
            message = struct.pack('=IHHII', 16 + len(payload), kind, 0, 0, 0) + payload
            return message + b'\0' * (-len(message) % 4)
        for kind in (16, 17, 20, 21, 24, 25):
            with self.subTest(kind=kind):
                self.assertTrue(linux._network_event(event(kind)))
        self.assertFalse(linux._network_event(event(28)))  # neighbor updates
        self.assertFalse(linux._network_event(event(3)))  # dump complete
        self.assertFalse(linux._network_event(b'\0' * 20))
        self.assertTrue(linux._network_event(event(3, b'x') + event(24)))

    def test_socket_watcher_waits_for_events_and_close_prevents_callbacks(self):
        from bridge.platforms.posix.network_events import SocketNetworkWatcher
        source, writer = socket.socketpair()
        changed = threading.Event()
        calls = []
        def callback():
            calls.append(True)
            changed.set()
        watcher = SocketNetworkWatcher(source, callback, lambda data: data == b'change')
        try:
            self.assertFalse(changed.wait(.03))
            writer.sendall(b'noise')
            self.assertFalse(changed.wait(.03))
            writer.sendall(b'change')
            self.assertTrue(changed.wait(1))
            watcher.close()
            watcher.close()
            self.assertFalse(watcher._thread.is_alive())
            self.assertEqual(source.fileno(), -1)
            self.assertEqual(calls, [True])
        finally:
            watcher.close()
            writer.close()

    def test_socket_watcher_close_waits_for_inflight_callback(self):
        from bridge.platforms.posix.network_events import SocketNetworkWatcher
        source, writer = socket.socketpair()
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        def callback():
            entered.set()
            release.wait(2)
        watcher = SocketNetworkWatcher(source, callback, lambda data: True)
        try:
            writer.sendall(b'change')
            self.assertTrue(entered.wait(1))
            closer = threading.Thread(target=lambda: (watcher.close(), closed.set()))
            closer.start()
            self.assertFalse(closed.wait(.03))
            release.set()
            self.assertTrue(closed.wait(1))
            closer.join(1)
            self.assertFalse(watcher._thread.is_alive())
        finally:
            release.set()
            watcher.close()
            writer.close()

    def test_platform_socket_open_failure_returns_none(self):
        for module in (macos, linux):
            with self.subTest(platform=module.__name__), \
                    patch.object(module.socket, 'socket', side_effect=PermissionError):
                self.assertIsNone(module.watch_changes(Mock()))
