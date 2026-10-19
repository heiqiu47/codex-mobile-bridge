"""Wire tests for the authenticated terminal WebSocket upgrade."""
import base64
import json
import os
import socket
import struct
import unittest
import uuid

import test_bridge as support


class TerminalSocketTests(unittest.TestCase):
    setUpClass = classmethod(support.HttpTests.setUpClass.__func__)
    tearDown = support.HttpTests.tearDown
    request = support.HttpTests.request
    login = support.HttpTests.login

    def setUp(self):
        support.HttpTests.setUp(self)
        self.identifier = str(uuid.uuid4())
        self.calls = []

        def terminal(thread, owner, action, params):
            self.calls.append((thread, owner, action, params))
            if action == 'poll':
                return {'output': '', 'cursor': 0, 'reset': False, 'running': True,
                        'shell': 'fixture', 'cwd': '/fixture'}
            return {'accepted': True}

        self.server.bridge.terminal = terminal

    def connect(self, auth, origin=None, protocols=None, identifier=None):
        connection = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        connection.settimeout(3)
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        fields = {'Host': '127.0.0.1:' + str(self.port), 'Origin': self.origin if origin is None else origin,
                  'Cookie': auth.get('Cookie', ''), 'Upgrade': 'websocket', 'Connection': 'Upgrade',
                  'Sec-WebSocket-Key': key, 'Sec-WebSocket-Version': '13',
                  'Sec-WebSocket-Protocol': protocols if protocols is not None else 'terminal.v1, ' + auth.get('X-CSRF-Token', '')}
        path = '/api/sessions/' + support.THREAD + '/terminal?host=local&mode=pty&id=' + (identifier or self.identifier) + '&after=0'
        request = 'GET ' + path + ' HTTP/1.1\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in fields.items()) + '\r\n'
        connection.sendall(request.encode('ascii'))
        response = b''
        while b'\r\n\r\n' not in response:
            response += connection.recv(1)
        return connection, response

    @staticmethod
    def send(connection, message):
        payload = json.dumps(message, ensure_ascii=False).encode('utf-8')
        mask = os.urandom(4)
        head = bytes((0x81, 0x80 | len(payload))) if len(payload) < 126 else bytes((0x81, 0xfe)) + struct.pack('!H', len(payload))
        connection.sendall(head + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))

    @staticmethod
    def receive(connection):
        def exact(length):
            result = b''
            while len(result) < length:
                result += connection.recv(length - len(result))
            return result
        head = exact(2)
        length = head[1] & 127
        if length == 126: length = struct.unpack('!H', exact(2))[0]
        elif length == 127: length = struct.unpack('!Q', exact(8))[0]
        return head[0] & 15, json.loads(exact(length)) if head[0] & 15 == 1 else exact(length)

    def test_rejects_missing_login_origin_csrf_and_other_terminal(self):
        auth = self.login()
        cases = [({}, None, None, None, b'401'),
                 (auth, 'https://evil.example', None, None, b'403'),
                 (auth, None, 'terminal.v1, wrong', None, b'403')]
        for credentials, origin, protocols, identifier, expected in cases:
            connection, response = self.connect(credentials, origin, protocols, identifier)
            self.assertIn(expected, response)
            connection.close()
        self.server.bridge.terminal = lambda *args: (_ for _ in ()).throw(KeyError('other owner'))
        connection, response = self.connect(auth)
        self.assertIn(b'404', response)
        connection.close()

    def test_ordered_resize_and_unicode_input_with_ack(self):
        auth = self.login()
        connection, response = self.connect(auth)
        try:
            self.assertIn(b'101 Switching Protocols', response)
            self.assertIn(b'Sec-WebSocket-Protocol: terminal.v1', response)
            resize_id, input_id = str(uuid.uuid4()), str(uuid.uuid4())
            self.send(connection, {'action': 'resize', 'requestId': resize_id, 'cols': 100, 'rows': 30})
            self.send(connection, {'action': 'input', 'inputId': input_id, 'data': '你好😀\r'})
            self.assertEqual(self.receive(connection), (1, {'type': 'ack', 'action': 'resize', 'id': resize_id}))
            self.assertEqual(self.receive(connection), (1, {'type': 'ack', 'action': 'input', 'id': input_id}))
            self.assertEqual([call[2] for call in self.calls if call[2] != 'poll'], ['resize', 'input'])
            self.assertEqual(next(call[3]['data'] for call in self.calls if call[2] == 'input'), '你好😀\r')
        finally:
            connection.close()

    def test_output_chunks_and_render_ack_use_bounded_frames(self):
        output = '好' * 40000
        self.server.bridge.terminal = lambda thread, owner, action, params: (
            {'output': output[params['after']:], 'cursor': len(output), 'reset': False,
             'running': True, 'shell': 'fixture', 'cwd': '/fixture'} if action == 'poll' else {'accepted': True})
        connection, response = self.connect(self.login())
        try:
            self.assertIn(b'101', response)
            frames = [self.receive(connection)[1] for _ in range(3)]
            self.assertEqual([frame['seq'] for frame in frames], [1, 2, 3])
            self.assertEqual(''.join(frame['value']['output'] for frame in frames), output)
            self.assertEqual([len(frame['value']['output']) for frame in frames], [16384, 16384, 7232])
            self.send(connection, {'action': 'rendered', 'seq': 3})
        finally:
            connection.close()

    def test_revoked_login_closes_existing_socket(self):
        auth = self.login()
        connection, response = self.connect(auth)
        try:
            self.assertIn(b'101', response)
            self.server.auth.logout(auth['Cookie'].split('=', 1)[1])
            opcode, _ = self.receive(connection)
            self.assertEqual(opcode, 8)
        finally:
            connection.close()


if __name__ == '__main__': unittest.main()
