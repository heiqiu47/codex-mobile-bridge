import unittest
import uuid
from unittest.mock import Mock

import test_desktop_sessions


class ForkReceipts(unittest.TestCase):
    setUp = test_desktop_sessions.Adapters.setUp

    def test_fork_keeps_source_and_never_replays_unknown_result(self):
        adapter = Mock()
        adapter.call.side_effect = TimeoutError('lost receipt')
        self.manager.adapters['deepseek'] = adapter
        body = {'id': str(uuid.uuid4()), 'messageId': '42'}
        first = self.manager.call('deepseek', 'fork', 'original', body)
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(self.manager.call('deepseek', 'fork', 'original', body), first)
        adapter.call.assert_called_once_with('fork', 'original', body)
        with self.assertRaises(ValueError):
            self.manager.call('deepseek', 'fork', 'other', body)

    def test_fork_only_accepts_native_message_anchor(self):
        adapter = Mock()
        self.manager.adapters['claude'] = adapter
        for extra in ({}, {'messageId': ''}, {'messageId': 1},
                      {'messageId': 'm', 'cwd': '/elsewhere'},
                      {'messageId': 'm', 'text': 'do not send'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.manager.call('claude', 'fork', 'source', {'id': str(uuid.uuid4()), **extra})
        adapter.call.assert_not_called()

    def test_confirmed_fork_returns_saved_child_receipt(self):
        adapter = Mock()
        adapter.call.return_value = {'status': 'ready', 'result': {'id': 'child'}}
        self.manager.adapters['claude'] = adapter
        body = {'id': str(uuid.uuid4()), 'messageId': 'native-message-uuid'}
        self.assertEqual(self.manager.call('claude', 'fork', 'source', body)['result']['id'], 'child')
        self.assertEqual(self.manager.call('claude', 'fork', 'source', body)['result']['id'], 'child')
        self.assertEqual(adapter.call.call_count, 1)
