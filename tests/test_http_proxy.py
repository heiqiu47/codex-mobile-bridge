"""Loopback proxy bursts and request framing, without any real client sessions."""
import http.client
import json
import socket
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bridge.api.assets import served_asset_bytes
from bridge.api.httpd import GatewayServer


ROOT = Path(__file__).resolve().parents[1]
HOST = 'phone.example.com'
THREAD = '11111111-1111-4111-8111-111111111111'


class ProxyHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = GatewayServer(
            ('127.0.0.1', 0), SimpleNamespace(accounts=SimpleNamespace()),
            {'auth': {'mode': 'none'}, 'origins': ['https://' + HOST],
             'localAccess': False}, ROOT / 'web')
        self.thread = None
        self.connections = []

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        if self.thread is not None:
            self.server.shutdown()
            self.thread.join(timeout=3)
        self.server.server_close()

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def connect(self):
        connection = socket.create_connection(self.server.server_address, timeout=2)
        self.connections.append(connection)
        return connection

    def request(self, connection, headers='', body=b'', method='GET', path='/wsl-accounts.js'):
        connection.sendall((f'{method} {path} HTTP/1.1\r\nHost: {HOST}\r\n'
                            + headers + '\r\n').encode('ascii') + body)
        response = http.client.HTTPResponse(connection)
        response.begin()
        payload = response.read()
        return response, payload

    def test_listen_queue_absorbs_a_full_startup_resource_burst(self):
        # Hold accept until the proxy has queued a cold page's scripts and styles.
        connections = [self.connect() for _ in range(38)]
        self.start()
        expected = served_asset_bytes(ROOT / 'web', '/wsl-accounts.js')
        for connection in connections:
            response, payload = self.request(connection, 'Connection: close\r\n')
            self.assertEqual(response.status, 200)
            self.assertEqual(payload, expected)

    def test_larger_listen_queue_preserves_the_active_connection_limit(self):
        requests = [MagicMock() for _ in range(49)]
        with patch.object(ThreadingHTTPServer, 'process_request') as dispatch:
            for request in requests:
                self.server.process_request(request, ('127.0.0.1', 12345))
            self.assertEqual(dispatch.call_count, 48)
            requests[-1].close.assert_called_once_with()
            for request in requests[:-1]:
                request.close.assert_not_called()

    def test_unread_get_body_does_not_become_a_second_http_request(self):
        self.start()
        expected = served_asset_bytes(ROOT / 'web', '/wsl-accounts.js')
        for headers, body in [
                ('Transfer-Encoding: chunked\r\n', b'0\r\n\r\n'),
                ('Content-Length: 1\r\n', b'x'),
                ('Content-Length: 0\r\nContent-Length: 1\r\n', b'x'),
                ('Content-Length: invalid\r\n', b'x'),
                ('Transfer-Encoding: \r\n', b'0\r\n\r\n')]:
            with self.subTest(headers=headers):
                connection = self.connect()
                response, payload = self.request(connection, headers, body)
                self.assertEqual(response.status, 200)
                self.assertEqual(payload, expected)
                self.assertEqual(response.getheader('Connection'), 'close')
                self.assertEqual(connection.recv(1), b'')

    def test_bodyless_gets_still_reuse_the_proxy_connection(self):
        self.start()
        connection = self.connect()
        for headers in ['', 'Content-Length: 0\r\n']:
            response, _ = self.request(connection, headers)
            self.assertEqual(response.status, 200)
            self.assertFalse(response.will_close)

    def test_rejected_post_returns_error_before_delayed_body_and_closes(self):
        self.start()
        connection = self.connect()
        connection.sendall((f'POST /api/accounts/switch HTTP/1.1\r\nHost: {HOST}\r\n'
                            'Origin: https://wrong.example\r\nContent-Length: 4\r\n'
                            'Content-Type: application/json\r\n\r\n').encode())
        response = http.client.HTTPResponse(connection)
        response.begin()
        self.assertEqual(response.status, 403)
        self.assertIn('error', json.loads(response.read()))
        self.assertEqual(response.getheader('Connection'), 'close')
        # The body arrives after rejection. It must never become another request.
        connection.sendall(b'null')
        self.assertEqual(connection.recv(1), b'')

    def test_chunked_writes_remain_rejected(self):
        self.start()
        connection = self.connect()
        response, _ = self.request(
            connection, 'Origin: https://' + HOST + '\r\n'
            'Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n',
            b'0\r\n\r\n', method='POST', path='/api/login')
        self.assertEqual(response.status, 400)
        self.assertEqual(response.getheader('Connection'), 'close')


    def session_target(self):
        target = self.server.bridge
        target.for_host = lambda host: target
        target.pin = MagicMock(return_value={'id': THREAD, 'bridgePinned': True})
        target.archive = MagicMock(return_value={'id': THREAD, 'archived': True, 'status': 'confirmed'})
        token, session = self.server.auth.new_session('127.0.0.1')
        cookie = 'Cookie: ' + self.server.auth.cookie_name + '=' + token + '\r\n'
        return target, cookie, 'X-CSRF-Token: ' + session['csrf'] + '\r\n'

    def test_framed_get_cannot_dispatch_pipelined_session_mutations(self):
        target, cookie, csrf = self.session_target()
        self.start()
        for action, value in [('pin', {'pinned': True}), ('archive', {'archived': True, 'id': THREAD})]:
            body = json.dumps(value).encode()
            pipeline = (f'POST /api/sessions/{THREAD}/{action} HTTP/1.1\r\nHost: {HOST}\r\n'
                        f'Origin: https://{HOST}\r\n' + cookie + csrf +
                        f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body
            # Without close, the unread GET body itself is a valid authenticated
            # POST, so this checks actual mutation suppression, not just a 400 tail.
            for headers in [f'Content-Length: {len(pipeline)}\r\n',
                            f'Content-Length: 0\r\nContent-Length: {len(pipeline)}\r\n',
                            'Content-Length: invalid\r\n']:
                with self.subTest(action=action, headers=headers):
                    connection = self.connect()
                    response, _ = self.request(connection, headers, pipeline)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader('Connection'), 'close')
                    self.assertEqual(connection.recv(1), b'')
                    target.pin.assert_not_called()
                    target.archive.assert_not_called()

    def test_session_write_auth_csrf_origin_and_framing_guards_remain_effective(self):
        target, cookie, csrf = self.session_target()
        self.start()
        for action, value in [('pin', {'pinned': True}), ('archive', {'archived': True, 'id': THREAD})]:
            payload = json.dumps(value).encode()
            common = f'Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n'
            origin = f'Origin: https://{HOST}\r\n'
            cases = [
                (origin + common, payload, 401),
                (origin + cookie + common, payload, 403),
                ('Origin: https://other.example.com\r\n' + cookie + csrf + common, payload, 403),
                (origin + cookie + csrf + 'Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n', b'0\r\n\r\n', 400),
                (origin + cookie + csrf + common + f'Content-Length: {len(payload)}\r\n', payload, 400),
                (origin + cookie + csrf + 'Content-Type: application/json\r\nContent-Length: invalid\r\n', payload, 400),
            ]
            for headers, body, status in cases:
                with self.subTest(action=action, status=status, headers=headers):
                    connection = self.connect()
                    response, _ = self.request(connection, headers, body, method='POST', path=f'/api/sessions/{THREAD}/{action}')
                    self.assertEqual(response.status, status)
                    self.assertEqual(response.getheader('Connection'), 'close')
                    target.pin.assert_not_called()
                    target.archive.assert_not_called()
            response, _ = self.request(self.connect(), origin + cookie + csrf + common + 'Connection: close\r\n',
                                       payload, method='POST', path=f'/api/sessions/{THREAD}/{action}')
            self.assertEqual(response.status, 200)
            getattr(target, action).assert_called_once()
            getattr(target, action).reset_mock()


if __name__ == '__main__':
    unittest.main()
