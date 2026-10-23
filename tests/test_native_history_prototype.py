"""The prototype must never resume or write while probing native history."""
import importlib.util
from pathlib import Path
import time
import json
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts/prototypes/native_history.py'
spec = importlib.util.spec_from_file_location('native_history_probe', PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
spec_claude = importlib.util.spec_from_file_location('claude_history_probe', PATH.with_name('claude_history.py'))
claude = importlib.util.module_from_spec(spec_claude)
spec_claude.loader.exec_module(claude)


class NativeHistoryPrototypeTests(unittest.TestCase):
    def test_settings_probe_never_subscribes_or_exposes_settings_values(self):
        from unittest.mock import Mock
        ipc = probe.MeasuredIPC('unused')
        ipc.request = Mock(return_value={'result': {'settings': {'model': 'fixture'}}})
        ipc.follow = Mock(side_effect=AssertionError('metadata must not subscribe'))
        value = ipc.measure_settings('thread', 'original-owner')
        ipc.request.assert_called_once_with('thread-follower-read-model-settings',
                                           {'conversationId': 'thread'}, target='original-owner')
        self.assertEqual(value['resultKeys'], ['settings'])
        self.assertNotIn('fixture', json.dumps(value))

    def test_write_resume_and_full_read_rejected(self):
        for method in ('thread/resume', 'turn/start', 'thread/start', 'thread/fork',
                       'thread/goal/set', 'thread-follower-load-complete-history'):
            with self.subTest(method=method), self.assertRaises(ValueError):
                probe.read_params(method, {'threadId': 'a'})
        for value in (None, True):
            with self.assertRaises(ValueError):
                probe.read_params('thread/read', {'threadId': 'a', 'includeTurns': value})

    def test_unbounded_body_reads_rejected(self):
        for params in ({}, {'limit': 0}, {'limit': 101}, {'limit': True}, {'limit': 20, 'itemsView': 'full'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                probe.read_params('thread/turns/list', {'threadId': 'a', 'sortDirection': 'desc', **params})

    def test_real_snapshot_shape_and_thread_isolation(self):
        ipc = probe.MeasuredIPC('unused')
        ipc.target, ipc.started = 'a', time.perf_counter()
        ipc.last_frame = {'bytes': 1000, 'receivedAt': time.perf_counter()}
        message = {'method': 'thread-stream-state-changed', 'sourceClientId': 'owner',
                   'params': {'conversationId': 'a', 'change': {'type': 'snapshot',
                       'revision': 9, 'conversationState': {'id': 'b', 'turns': []}}}}
        ipc.event(message)
        self.assertIsNone(ipc.result)
        message['params']['change']['conversationState'] = {'id': 'a', 'turns': [{}, {}]}
        ipc.event(message)
        self.assertEqual(ipc.result['bytes'], 1000)
        self.assertEqual(ipc.result['turns'], 2)

    def test_two_pages_no_full_hydration_or_repeat(self):
        calls = []
        def request(method, params):
            probe.read_params(method, params)
            calls.append((method, params))
            if method == 'thread/read':
                return {'thread': {'id': 'a'}}
            if method == 'thread/turns/list':
                return {'data': [{'id': 'turn', 'items': []}]}
            i = 2 if params.get('cursor') else 1
            return {'data': [{'turnId': 'turn', 'item': {'id': str(i)}}], 'nextCursor': 'older' if i == 1 else None}
        reader = type('Reader', (), {'request': staticmethod(request)})()
        result = probe.stored_pages(reader, 'a')
        self.assertEqual(len(result['pages']), 2)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[-1][1]['cursor'], 'older')

    def test_unsupported_does_not_trigger_full_fallback(self):
        calls = []
        def request(method, params):
            calls.append(method)
            if method == 'thread/read':
                return {'thread': {'id': 'a'}}
            raise ValueError('unsupported')
        reader = type('Reader', (), {'request': staticmethod(request)})()
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            probe.stored_pages(reader, 'a')
        self.assertEqual(calls, ['thread/read', 'thread/turns/list'])

    def test_runtime_requires_isolated_home(self):
        with self.assertRaises(ValueError):
            probe.StoredReader('/not/launched', Path.home() / '.codex')


class ClaudeHistoryPrototypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'history.jsonl'
        self.path.write_bytes(b''.join((json.dumps({'type': 'user' if i % 2 else 'assistant',
            'uuid': str(i), 'message': {'content': '中文 \U0001f600 ' + 'x' * 100}}, ensure_ascii=False) + '\n').encode()
            for i in range(3000)))

    def test_recent_and_older_unicode_do_not_read_full_file(self):
        first = claude.event_page(self.path, 'computer/account/profile', limit=20)
        second = claude.event_page(self.path, 'computer/account/profile', limit=20, cursor=first['cursor'])
        self.assertEqual([r['uuid'] for r in first['events']], list(map(str, range(2980, 3000))))
        self.assertEqual([r['uuid'] for r in second['events']], list(map(str, range(2960, 2980))))
        self.assertLess(first['bytesRead'], first['sourceBytes'] / 4)
        self.assertIn('中文', first['events'][0]['message']['content'])

    def test_cursor_isolation_and_mutation_rejected(self):
        first = claude.event_page(self.path, 'A')
        with self.assertRaises(ValueError):
            claude.event_page(self.path, 'B', cursor=first['cursor'])
        with self.path.open('ab') as f:
            f.write(b'{"type":"user","uuid":"new"}\n')
        with self.assertRaises(ValueError):
            claude.event_page(self.path, 'A', cursor=first['cursor'])

    def test_oversized_record_has_no_silent_empty_or_full_fallback(self):
        self.path.write_text(json.dumps({'type': 'assistant', 'message': 'x' * 100000}) + '\n')
        with self.assertRaisesRegex(ValueError, 'byte budget'):
            claude.event_page(self.path, 'A', byte_budget=1024)

    def test_sidechain_excluded_and_oldest_page_exhausted(self):
        self.path.write_text('\n'.join(json.dumps(v) for v in [
            {'type': 'metadata'},
            {'type': 'user', 'uuid': 'main'}, {'type': 'assistant', 'uuid': 'side', 'isSidechain': True},
            {'type': 'progress', 'uuid': 'progress'}]) + '\n')
        page = claude.event_page(self.path, 'A')
        self.assertEqual([r['uuid'] for r in page['events']], ['main'])
        self.assertIsNone(page['cursor'])


if __name__ == '__main__':
    unittest.main()
