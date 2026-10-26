"""Confirmed stop/archive contracts; all identities and processes are fixtures."""
import json
import subprocess
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge.clients.claude.cli_session import _Owned
from bridge.clients.errors import BridgeUnavailable
from bridge.clients.manager import DesktopSessions
from bridge.features.sessions.archive import ArchiveCommands
from bridge.features.sessions.create import ArchiveNotSent, stop_archive_runtime

ROOT = Path(__file__).resolve().parents[1]


class DisconnectArchive(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.sid = str(uuid.uuid4())

    def runtime(self, stuck=False):
        states = {self.sid: 'active', 'child': 'active', 'other': 'active'}
        background = {self.sid: True, 'child': False, 'other': True}
        calls = []

        def request(method, params):
            calls.append((method, dict(params)))
            sid = params['threadId']
            if method == 'thread/read':
                return {'thread': {'id': sid, 'status': {'type': states[sid]}}}
            if method == 'thread/turns/list':
                return {'data': [{'id': 'turn-' + sid, 'status': 'inProgress'}]}
            if method == 'thread/backgroundTerminals/list':
                return {'data': [{'processId': 'p'}] if background[sid] else []}
            if method == 'turn/interrupt':
                self.assertEqual(params['turnId'], 'turn-' + sid)
                if not stuck:
                    states[sid] = 'idle'
                return {}
            if method == 'thread/backgroundTerminals/clean':
                background[sid] = False
                return {}
            self.fail(method)
        return request, states, background, calls

    def test_stop_covers_exact_subtree_and_background_before_archive(self):
        request, states, background, calls = self.runtime()
        stop_archive_runtime(request, [self.sid, 'child'])
        self.assertEqual(states, {self.sid: 'idle', 'child': 'idle', 'other': 'active'})
        self.assertFalse(background[self.sid])
        self.assertTrue(background['other'])
        self.assertTrue(all(params['threadId'] != 'other' for _, params in calls))
        self.assertEqual([params['threadId'] for method, params in calls if method == 'turn/interrupt'], [self.sid, 'child'])

    def test_unloaded_saved_thread_never_loads_an_executor_to_check_background(self):
        request = Mock(return_value={'thread': {'id': self.sid, 'status': {'type': 'notLoaded'}}})
        stop_archive_runtime(request, [self.sid])
        self.assertTrue(all(call.args[0] == 'thread/read' for call in request.call_args_list))

    def test_unverified_stop_capability_refuses_before_any_mutation(self):
        request, _, _, calls = self.runtime()

        def unsupported(method, params):
            if method == 'thread/backgroundTerminals/list':
                raise ValueError('unsupported')
            return request(method, params)
        with self.assertRaises(ArchiveNotSent):
            stop_archive_runtime(unsupported, [self.sid, 'child'])
        self.assertFalse(any(method in ('turn/interrupt', 'thread/backgroundTerminals/clean') for method, _ in calls))

    def test_unknown_stop_is_persisted_before_interrupt_and_never_replayed(self):
        commands = ArchiveCommands(self.directory)
        request, _, _, calls = self.runtime(stuck=True)
        request_id = str(uuid.uuid4())
        native = {'archived': False, '_archiveFlags': {self.sid: False}}

        def recorded(method, params):
            if method == 'turn/interrupt':
                self.assertEqual(json.loads(commands.path.read_text())[request_id]['status'], 'unknown')
            return request(method, params)
        prepare = Mock(return_value=lambda: stop_archive_runtime(recorded, [self.sid], timeout=0))
        with self.assertRaisesRegex(ValueError, '待核对'):
            commands.perform(self.sid, True, request_id, lambda: native, prepare)
        count = len(calls)
        with self.assertRaisesRegex(ValueError, '待核对'):
            commands.perform(self.sid, True, str(uuid.uuid4()), lambda: native, prepare)
        self.assertEqual(len(calls), count)
        self.assertEqual(prepare.call_count, 1)

    def test_partial_subtree_archive_is_not_confirmed_or_reconciled_as_success(self):
        commands = ArchiveCommands(self.directory)
        native = {'archived': False, '_archiveFlags': {self.sid: False, 'child': False}}
        prepare = Mock(return_value=lambda: native.update(archived=True, _archiveFlags={self.sid: True, 'child': False}))
        read = lambda: dict(native)
        request_id = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, '待核对'):
            commands.perform(self.sid, True, request_id, read, prepare)
        with self.assertRaisesRegex(ValueError, '待核对'):
            commands.perform(self.sid, True, request_id, read, prepare)
        native['_archiveFlags']['child'] = True
        self.assertEqual(commands.perform(self.sid, True, request_id, read, prepare)['status'], 'confirmed')
        self.assertEqual(prepare.call_count, 1)

    def test_provider_confirmation_allows_stop_only_after_intent_and_keeps_unknown_gate(self):
        manager = DesktopSessions(self.directory)
        self.addCleanup(manager.close)
        manager.config['enabled'] = {'deepseek': True}
        state = {'archived': False, 'status': 'active', 'runtimeKnown': True, 'archiveSafe': False,
                 'requests': [{'id': 'pending'}], 'capabilities': {'archive': True, 'unarchive': True}}
        calls = []
        request_id = str(uuid.uuid4())

        def call(provider, action, sid, body):
            if action == 'archive-state':
                return dict(state)
            calls.append(body)
            path = manager.adapters[provider].directory / 'session-archives.json'
            self.assertEqual(json.loads(path.read_text())[request_id]['status'], 'unknown')
            state.update(archived=True, status='idle', archiveSafe=True, requests=[])
        with patch.object(manager, '_adapter_call', side_effect=call):
            with self.assertRaises(ValueError):
                manager.call('deepseek', 'archive', 'native', {'archived': True, 'id': request_id})
            result = manager.call('deepseek', 'archive', 'native', {'archived': True, 'id': request_id, 'disconnect': True})
            self.assertEqual(result['status'], 'confirmed')
            self.assertEqual(calls, [{'archived': True, 'disconnect': True}])
            for body in ({'archived': False, 'disconnect': True}, {'archived': True, 'disconnect': 'yes'}):
                with self.assertRaises(ValueError):
                    manager.call('deepseek', 'archive', 'native', {**body, 'id': str(uuid.uuid4())})

    def owner(self):
        owned = _Owned.__new__(_Owned)
        owned.condition = threading.Condition()
        owned.error, owned.finished, owned.active, owned.pending = None, False, True, {'approval': {}}
        owned.process = Mock()
        owned.process.poll.return_value = None
        events = []

        def interrupt(value, timeout):
            self.assertEqual(value, {'subtype': 'interrupt'})
            events.append('interrupt')
            owned.active = False
            owned.pending.clear()
        owned.control = Mock(side_effect=interrupt)
        owned.process.stdin.close.side_effect = lambda: events.append('EOF')
        owned.process.wait.side_effect = lambda timeout: (events.append('exit'), 0)[1]
        return owned, events

    def test_owned_cli_release_interrupts_then_flushes_eof_without_kill(self):
        owned, events = self.owner()
        owned.release_for_archive()
        self.assertEqual(events, ['interrupt', 'EOF', 'exit'])
        owned.process.terminate.assert_not_called()
        owned.process.kill.assert_not_called()

    def test_acknowledged_interruption_allows_native_exit_one_but_signal_exit_refuses(self):
        owned, _ = self.owner()
        owned.process.wait.side_effect = lambda timeout: 1
        owned.release_for_archive()
        owned, _ = self.owner()
        owned.process.wait.side_effect = lambda timeout: -9
        with self.assertRaisesRegex(BridgeUnavailable, '未正常退出'):
            owned.release_for_archive()

    def test_owned_cli_exit_timeout_is_not_replaced_by_force_kill(self):
        owned, _ = self.owner()
        owned.process.wait.side_effect = subprocess.TimeoutExpired('fixture', .01)
        with self.assertRaisesRegex(BridgeUnavailable, '尚未释放'):
            owned.release_for_archive(timeout=.01)
        owned.process.terminate.assert_not_called()
        owned.process.kill.assert_not_called()
