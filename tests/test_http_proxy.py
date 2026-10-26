"""Loopback proxy bursts and request framing, without any real client sessions."""
import http.client
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
                ('Content-Length: 0\r\nContent-Length: 1\r\n', b'x')]:
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

    def test_chunked_writes_remain_rejected(self):
        self.start()
        connection = self.connect()
        response, _ = self.request(
            connection, 'Origin: https://' + HOST + '\r\n'
            'Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n',
            b'0\r\n\r\n', method='POST', path='/api/login')
        self.assertEqual(response.status, 400)
        self.assertEqual(response.getheader('Connection'), 'close')


if __name__ == '__main__':
    unittest.main()
