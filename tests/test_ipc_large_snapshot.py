"""Large desktop histories must not disconnect unrelated followed threads."""
import json
import struct
import threading
import unittest
from unittest.mock import Mock, patch

from bridge.app.service import LiveSession
from bridge.clients.codex.ipc import DesktopIPC, IPCError
import test_bridge
from test_bridge import THREAD, state


class LargeSnapshotTests(unittest.TestCase):
    setUp = test_bridge.IntegrationTests.setUp
    tearDown = test_bridge.IntegrationTests.tearDown

    def test_large_snapshot_and_other_thread_updates_share_connection(self):
        session_a = self.bridge.session(THREAD)
        self.assertTrue(session_a.connected)
        session_b = LiveSession('00000000-0000-0000-0000-000000000065')
        session_b.discovering = True
        self.bridge.live[session_b.id] = session_b
        large = state()
        large['id'] = session_b.id
        large['turns'] = [{'turnId': 'large-turn', 'status': 'completed', 'items': [
            {'id': 'large-item', 'type': 'agentMessage', 'text': 'x' * (65 * 1024 * 1024) + '\n中文🚀'}]}]
        message = {'type': 'broadcast', 'sourceClientId': 'owner',
                   'method': 'thread-stream-state-changed', 'version': 11,
                   'params': {'hostId': 'local', 'conversationId': session_b.id,
                              'change': {'type': 'snapshot', 'revision': 1, 'conversationState': large}}}
        client_id = self.bridge.ipc.client_id
        errors = []

        def publish():
            try:
                self.fixture.send(message)
            except OSError as exc:
                errors.append(type(exc).__name__)

        worker = threading.Thread(target=publish, daemon=True)
        worker.start()
        worker.join(15)
        with session_b.condition:
            session_b.condition.wait_for(lambda: session_b.connected or not self.bridge.ipc.socket, timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(session_b.connected)
        self.assertTrue(session_a.connected)
        self.assertEqual(self.bridge.ipc.client_id, client_id)
        self.assertEqual(session_b.state['turns'][0]['items'][0]['text'], large['turns'][0]['items'][0]['text'])
        session_b.timeline.update(session_b.view())
        page = session_b.timeline.page()
        self.assertLess(len(json.dumps(page).encode()), 32 * 1024)
        self.assertTrue(page['rows'][0]['truncated'])
        # Both followers still receive subsequent patches on the same stream.
        for session in (session_a, session_b):
            message['params'] = {'hostId': 'local', 'conversationId': session.id, 'change': {
                'type': 'patches', 'baseRevision': 1, 'revision': 2,
                'patches': [{'op': 'replace', 'path': ['title'], 'value': 'Updated'}]}}
            self.fixture.send(message)
            with session.condition:
                self.assertTrue(session.condition.wait_for(lambda: session.revision == 2, timeout=3))
            self.assertEqual(session.state['title'], 'Updated')
        self.assertEqual([r['method'] for r in self.fixture.requests], ['initialize'])


class FrameBudgetTests(unittest.TestCase):
    def test_receive_uses_bounded_chunks_and_accepts_fragmented_header(self):
        stream = Mock()
        stream.recv.side_effect = [b'\x01', b'\x00\x00', b'\x00']
        self.assertEqual(DesktopIPC._exact(stream, 4), b'\x01\x00\x00\x00')
        sizes = []

        def recv(size):
            sizes.append(size)
            return b'x' * min(size, 256 * 1024)

        stream.recv.side_effect = recv
        self.assertEqual(len(DesktopIPC._exact(stream, 3 * 1024 * 1024 + 1)), 3 * 1024 * 1024 + 1)
        self.assertLessEqual(max(sizes), 1024 * 1024)

    def test_invalid_frame_rejected_before_body_allocation(self):
        for length in (0, DesktopIPC.MAX_FRAME + 1, 0xffffffff):
            with self.subTest(length=length):
                stream = Mock()
                stream.recv.return_value = struct.pack('<I', length)
                disconnected = Mock()
                ipc = DesktopIPC('unused', on_disconnect=disconnected)
                ipc.socket = stream
                with self.assertLogs('bridge.clients.codex.ipc', level='WARNING') as logs:
                    ipc._read_loop(stream)
                stream.recv.assert_called_once_with(4)
                disconnected.assert_called_once_with()
                self.assertIn('bytes='+str(length), logs.output[0])

    def test_outbound_budget_does_not_expand_with_snapshot_budget(self):
        self.assertEqual(DesktopIPC.MAX_REQUEST, 64 * 1024 * 1024)
        ipc = DesktopIPC('unused')
        ipc.socket = Mock()
        with patch.object(ipc, 'MAX_REQUEST', 10):
            with self.assertRaisesRegex(IPCError, '消息过大'):
                ipc._send({'text': 'not a small request'})
        ipc.socket.sendall.assert_not_called()


if __name__ == '__main__':
    unittest.main()
