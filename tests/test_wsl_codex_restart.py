"""Cold WSL switch fixtures: fake processes/RPC, real private account files."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import uuid

from bridge.features.accounts import wsl_account_worker as worker
from bridge.clients.codex.ipc import IPCError
from bridge.features.accounts.wsl_accounts import WslAccounts
from bridge.features.endpoints.registry import entry_id
from bridge.features.endpoints.wsl import WslEntry
from bridge.platforms.windows import wsl_account_runtime as native
from tests.test_wsl_accounts import install_target_toml
from tests.test_wsl_entries import Runtime
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class ColdRuntime(Runtime):
    def __init__(self, identifier, loaded=True):
        super().__init__(identifier)
        self.lock = threading.RLock()
        self.pending = {}
        self.thread.update(modelProvider='original_api', model='original-model', status={'type': 'idle' if loaded else 'notLoaded'})
        self.loaded = loaded
        self.second_active = False
        self.top_level_model = False
        self.effective_model = 'original-model'

    def request(self, method, params):
        if method == 'thread/loaded/list':
            self.calls.append((method, copy.deepcopy(params)))
            if self.second_active:
                return {'data': ['other-active'] if params.get('cursor') else [self.thread['id']],
                        'nextCursor': None if params.get('cursor') else 'next-page'}
            return {'data': [self.thread['id']] if self.loaded else [], 'nextCursor': None}
        if method == 'thread/read' and params['threadId'] == 'other-active':
            self.calls.append((method, copy.deepcopy(params)))
            return {'thread': {'id': 'other-active', 'status': {'type': 'active'}}}
        if method == 'thread/resume':
            self.loaded = True
            self.thread['status'] = {'type': 'idle'}
            result = super().request(method, params)
            if params.get('model'):
                self.effective_model = params['model']
            if self.top_level_model:
                result['thread'].pop('model', None)
                result['model'] = self.effective_model
            return {**result, 'approvalPolicy': 'on-request', 'sandbox': {'type': 'workspaceWrite'}}
        if method == 'thread/read' and self.top_level_model:
            result = super().request(method, params)
            result['thread'].pop('model', None)
            return result
        return super().request(method, params)


@unittest.skipUnless(os.name == 'posix', 'Synthetic native account files require POSIX ownership')
class WslCodexColdRestartTests(unittest.TestCase):
    def setUp(self):
        install_target_toml(self)
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        (self.home / 'auth.json').write_text('{"auth_mode":"apikey","OPENAI_API_KEY":"old-fixture"}')
        (self.home / 'config.toml').write_text('model_provider="original_api"\nmodel="original-model"\n[model_providers.original_api]\nname="Original"\nbase_url="https://old.invalid/v1"\nrequires_openai_auth=true\n')
        self.row = {'distribution': 'FixtureUbuntu', 'user': 'fixture', 'home': str(self.home), 'label': 'Fixture', 'enabled': True}
        self.row['id'] = entry_id(self.row['distribution'], self.row['user'], self.row['home'])
        self.identifier = str(uuid.uuid4())
        self.old = ColdRuntime(self.identifier)
        self.new = ColdRuntime(self.identifier, loaded=False)
        self.entry = WslEntry(self.row, self.root / self.row['id'][4:])
        self.addCleanup(self.entry.close)
        self.entry.server = self.old
        self.entry.generation = 'original-generation'
        self.entry.subscriptions[self.identifier] = self.entry.generation
        self.entry.store = SimpleNamespace(get=lambda sid: {'id': sid, 'cwd': '/home/fixture/project', 'model_provider': 'original_api'})
        self.entry._account_route = lambda: {'managed': False}
        self.entry.capture_account_drafts = Mock(return_value={})
        self.entry.complete_account_drafts = Mock(return_value=[])
        self.session = self.entry.session(self.identifier, attach=False)
        self.session.loading = False
        self.daemon = {'pid': 123, 'startTicks': '456', 'executable': '/fixture/codex', 'socket': '/fixture/control.sock'}
        self.entry.daemon_identity = dict(self.daemon)
        self.running = True
        self.store = worker.AccountStore('codex', self.home, guard=lambda *_: [worker.ERROR_MESSAGES['runtime_running']] if self.running else [])
        self.store.change({'action': 'save-api', 'name': 'New fixture', 'model': 'new-default-model', 'baseUrl': 'https://new.invalid/v1', 'apiKey': 'new-fixture'})
        self.target = self.store.public()['accounts'][0]['id']
        registry = SimpleNamespace(entries=[self.row], lock=threading.RLock(), directory=self.root, bridges={self.row['id']: self.entry})
        self.accounts = WslAccounts(SimpleNamespace(entries=registry, data_dir=self.root))
        self.addCleanup(self.accounts.close)
        self.calls = []
        def target(provider, row, request):
            self.calls.append(dict(request))
            return self.store.public() if request['action'] == 'read' else self.store.preview_switch(request) if request['action'] == 'preview-switch' else self.store.change(request)
        self.mocks = ExitPatches(self)
        self.call = self.mocks.start(patch.object(self.accounts, '_call', side_effect=target))
        self.mocks.start(patch('bridge.features.accounts.wsl_accounts.wsl.running_distributions', return_value=['FixtureUbuntu']))
        self.native_lock = Mock()
        self.mocks.start(patch.object(native, 'OperationLock', return_value=self.native_lock))
        self.inspect = self.mocks.start(patch.object(native, 'inspect', side_effect=lambda *_: {'daemons': [self.daemon] if self.running else [], 'blockers': []}))
        self.stop = self.mocks.start(patch.object(native, 'stop', side_effect=self.stop_native))
        self.start = self.mocks.start(patch.object(native, 'start', side_effect=self.start_native))
        def runtime(allow_start=False):
            self.entry.server = self.new
            self.entry.generation = 'replacement-generation'
            return self.new
        self.mocks.start(patch.object(self.entry, 'runtime', side_effect=runtime))

    def stop_native(self, *args):
        self.assertEqual(args, (self.row['distribution'], self.row['user'], self.row['home'], self.daemon))
        self.assertEqual(json.loads((self.home / 'auth.json').read_text())['OPENAI_API_KEY'], 'old-fixture')
        self.running = False
        return {'stopped': True}

    def start_native(self, *args):
        if self.running and self.entry.server is self.old and not self.old.closed and args[-1]:
            raise ValueError('original service is still draining; no second signal')
        self.running = True
        return {'started': True, 'daemon': {**self.daemon, 'pid': 124, 'startTicks': 'replacement'}}

    def request(self, **values):
        return {'provider': 'codex', 'entry': self.row['id'], 'action': 'switch', 'id': self.target,
                'expectedIdentity': self.store.public()['identity'], **values}

    def test_explicit_switch_stops_before_auth_write_and_resumes_same_thread_model_and_permissions(self):
        result = self.accounts.change(self.request())
        self.assertTrue(result['restartVerified'])
        self.assertFalse(result.get('restartPending', False))
        self.stop.assert_called_once()
        self.start.assert_called_once()
        self.assertEqual(json.loads((self.home / 'auth.json').read_text())['OPENAI_API_KEY'], 'new-fixture')
        self.assertEqual(self.new.thread['id'], self.identifier)
        self.assertEqual(self.new.thread['cwd'], self.old.thread['cwd'])
        self.assertEqual(self.new.thread['model'], self.old.thread['model'])
        self.assertEqual(self.session.state['currentPermissions'], {'approvalPolicy': 'on-request', 'sandboxPolicy': {'type': 'workspaceWrite'}})
        resume = [params for method, params in self.new.calls if method == 'thread/resume']
        self.assertEqual(resume, [{'threadId': self.identifier, 'excludeTurns': True, 'model': 'original-model', 'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'}])
        self.assertFalse(any(method in ('turn/start', 'turn/steer', 'thread/start', 'thread/fork') for method, _ in self.old.calls + self.new.calls))

    def test_active_thread_on_later_page_or_unknown_receipt_never_stops_or_writes(self):
        before = self.store.files()
        self.old.second_active = True
        with self.assertRaisesRegex(ValueError, '运行中'):
            self.accounts.change(self.request())
        self.old.second_active = False
        self.entry.receipts['unknown'] = {'result': {'status': 'unknown'}}
        with self.assertRaisesRegex(ValueError, '待核对'):
            self.accounts.change(self.request())
        self.stop.assert_not_called()
        self.assertEqual(self.store.files(), before)

    def test_stale_identity_or_failed_graceful_exit_never_writes_or_force_kills(self):
        before = self.store.files()
        with self.assertRaises(ValueError):
            self.accounts.change(self.request(expectedIdentity='stale'))
        self.stop.assert_not_called()
        self.stop.side_effect = ValueError('fixture normal exit timed out')
        with self.assertRaisesRegex(ValueError, 'timed out'):
            self.accounts.change(self.request())
        self.assertEqual(self.store.files(), before)
        self.start.assert_not_called()

    def test_applied_configuration_restart_failure_recovers_without_repeating_switch(self):
        self.start.side_effect = ValueError('fixture start unavailable')
        result = self.accounts.change(self.request())
        self.assertTrue(result['restartPending'])
        self.assertTrue(result['capabilities']['recoverRestart'])
        self.assertEqual(sum(call['action'] == 'switch' for call in self.calls), 1)
        self.start.side_effect = self.start_native
        recovered = self.accounts.change(self.request(action='recover-restart', id=None))
        self.assertTrue(recovered['restartVerified'])
        self.assertFalse(recovered['restartPending'])
        self.assertEqual(sum(call['action'] == 'switch' for call in self.calls), 1)
        self.stop.assert_called_once()

    def test_native_top_level_model_is_restored_instead_of_new_account_default(self):
        self.old.top_level_model = self.new.top_level_model = True
        self.new.effective_model = 'new-default-model'
        result = self.accounts.change(self.request())
        self.assertTrue(result['restartVerified'])
        self.assertEqual(self.new.effective_model, 'original-model')
        self.assertEqual(self.session.state['latestModel'], 'original-model')
        record = json.loads((self.entry.data_dir / 'account-restart.json').read_text())
        self.assertEqual(record['threads'][self.identifier]['model'], 'original-model')

    def test_account_read_is_advisory_without_native_thread_queries_or_subscription(self):
        result = self.accounts.read('codex', self.row['id'])
        self.assertTrue(result['restartRequired'])
        self.assertTrue(result['capabilities']['attemptSwitch'])
        self.assertFalse(self.old.calls)
        self.native_lock.acquire.assert_not_called()
        self.stop.assert_not_called()

    def test_timeout_retry_never_sends_second_term_and_recovery_waits_for_original_exit(self):
        before = self.store.files()
        self.stop.side_effect = ValueError('fixture drain timeout')
        with self.assertRaisesRegex(ValueError, 'timeout'):
            self.accounts.change(self.request())
        with self.assertRaisesRegex(ValueError, '不会再次'):
            self.accounts.change(self.request())
        self.stop.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'still draining'):
            self.accounts.change(self.request(action='recover-restart', id=None))
        self.running = False
        self.old.close()
        restored = self.accounts.change(self.request(action='recover-restart', id=None))
        self.assertTrue(restored['restartVerified'])
        self.assertEqual(self.store.files(), before)
        self.assertEqual(sum(call['action'] == 'switch' for call in self.calls), 0)
        self.stop.assert_called_once()

    def test_confirmed_rejection_before_signal_does_not_leave_an_unrecoverable_intent(self):
        self.stop.side_effect = native.HandoffError('fixture identity changed before signal', False)
        with self.assertRaises(native.HandoffError):
            self.accounts.change(self.request())
        pending = json.loads((self.entry.data_dir / 'account-restart.json').read_text())
        self.assertFalse(pending['terminationRequested'])
        self.assertEqual(pending['phase'], 'cancelled')
        self.stop.side_effect = self.stop_native
        self.assertTrue(self.accounts.change(self.request())['restartVerified'])

    def test_committed_worker_response_loss_reconciles_from_exact_intent_without_replay(self):
        original = self.call.side_effect
        def lost(provider, row, request):
            result = original(provider, row, request)
            if request['action'] == 'switch':
                raise TimeoutError('fixture response lost after durable commit')
            return result
        self.call.side_effect = lost
        result = self.accounts.change(self.request())
        self.assertTrue(result['switchReconciled'])
        self.assertTrue(result['restartVerified'])
        self.assertEqual(result['activeId'], self.target)
        self.assertEqual(sum(call['action'] == 'switch' for call in self.calls), 1)
        self.stop.assert_called_once()

    def test_stop_response_loss_recovers_prepared_record_without_rewriting_account(self):
        before = self.store.files()
        def lost(*args):
            self.stop_native(*args)
            self.old.close()
            raise TimeoutError('fixture stop response lost')
        self.stop.side_effect = lost
        with self.assertRaises(TimeoutError):
            self.accounts.change(self.request())
        pending = json.loads((self.entry.data_dir / 'account-restart.json').read_text())
        self.assertEqual(pending['phase'], 'prepared')
        recovered = self.accounts.change(self.request(action='recover-restart', id=None))
        self.assertTrue(recovered['restartVerified'])
        self.assertEqual(self.store.files(), before)
        self.assertEqual(sum(call['action'] == 'switch' for call in self.calls), 0)

    def test_partial_thread_restore_resumes_after_gateway_subscription_cache_loss(self):
        second = str(uuid.uuid4())
        second_thread = {**self.old.thread, 'id': second}
        original_old, original_new = self.old.request, self.new.request
        second_loaded = [False]
        fail = [True]
        def old_request(method, params):
            if method == 'thread/loaded/list':
                return {'data': [self.identifier, second], 'nextCursor': None}
            if params.get('threadId') == second:
                return {'thread': copy.deepcopy(second_thread), 'approvalPolicy': 'on-request', 'sandbox': {'type': 'workspaceWrite'}}
            return original_old(method, params)
        def new_request(method, params):
            if method == 'thread/loaded/list':
                return {'data': ([self.identifier] if self.new.loaded else []) + ([second] if second_loaded[0] else []), 'nextCursor': None}
            if params.get('threadId') == second:
                if method == 'thread/resume':
                    if fail[0]:
                        raise IPCError('fixture second thread unavailable')
                    second_loaded[0] = True
                thread = {**second_thread, 'status': {'type': 'idle' if second_loaded[0] else 'notLoaded'}}
                return {'thread': thread, 'approvalPolicy': 'on-request', 'sandbox': {'type': 'workspaceWrite'}}
            return original_new(method, params)
        self.old.request, self.new.request = old_request, new_request
        self.entry.subscriptions[second] = self.entry.generation
        self.entry.session(second, attach=False).loading = False
        first = self.accounts.change(self.request())
        self.assertTrue(first['restartPending'])
        pending = json.loads((self.entry.data_dir / 'account-restart.json').read_text())
        self.assertIn(self.identifier, pending['restoredThreads'])
        self.entry.subscriptions.clear()
        self.entry._managed_routes.clear()
        fail[0] = False
        recovered = self.accounts.change(self.request(action='recover-restart', id=None))
        self.assertTrue(recovered['restartVerified'])
        self.assertTrue(second_loaded[0])
        self.assertEqual(sum(call['action'] == 'switch' for call in self.calls), 1)
        self.stop.assert_called_once()

    def test_cold_switch_integrates_real_draft_capture_and_standalone_identity_without_native_messages(self):
        del self.entry.capture_account_drafts
        del self.entry.complete_account_drafts
        metadata = {'id': self.identifier, 'cwd': '/home/fixture/project', 'model_provider': 'original_api'}
        self.entry.store.list = lambda **options: [dict(metadata)] if not options['archived'] and not options['offset'] else []
        def read(_alias, source, **_options):
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
                exec(source, {'__file__': worker.__file__})
            return json.loads(output.getvalue())
        self.entry.read = read
        self.session.state.update(cwd=metadata['cwd'], modelProvider='original_api')
        old = self.entry._account_draft_state('original_api')['accountIdentity']
        self.assertTrue(old)
        result = self.accounts.change(self.request())
        self.assertTrue(result['restartVerified'])
        self.assertEqual(result['draftContinuations'][0]['id'], self.identifier)
        self.assertEqual(result['draftContinuations'][0]['previousAccountIdentity'], old)
        view = self.entry.view(self.identifier, attach=False)
        self.assertEqual(view['draftContinuation']['accountIdentity'], view['draftAccountIdentity'])
        self.assertEqual(view['draftContinuation']['previousAccountIdentities'], [old])

    def test_stopped_daemon_offline_history_receives_draft_lineage_without_starting_codex(self):
        del self.entry.capture_account_drafts
        del self.entry.complete_account_drafts
        metadata = {'id': self.identifier, 'cwd': '/home/fixture/project', 'model_provider': 'original_api'}
        self.entry.store.list = lambda **options: [dict(metadata)] if not options['archived'] and not options['offset'] else []
        def read(_alias, source, **_options):
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
                exec(source, {'__file__': worker.__file__})
            return json.loads(output.getvalue())
        self.entry.read = read
        self.running = False
        self.old.close()
        self.entry.server = None
        self.entry.subscriptions.clear()
        self.entry.live.clear()
        result = self.accounts.change(self.request())
        self.assertFalse(result['restartVerified'])
        self.assertEqual(result['draftContinuations'][0]['id'], self.identifier)
        self.stop.assert_not_called()
        self.start.assert_not_called()
        self.entry.runtime.assert_not_called()


class ExitPatches:
    def __init__(self, testcase):
        self.testcase = testcase
    def start(self, value):
        result = value.start()
        self.testcase.addCleanup(value.stop)
        return result
