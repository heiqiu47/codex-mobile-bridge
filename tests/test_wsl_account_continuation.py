"""Synthetic account files and native RPC harness; no WSL or model execution."""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from bridge.clients.codex.ipc import IPCError
from bridge.features.accounts import wsl_account_worker as worker
from tests.test_wsl_accounts import install_target_toml
from tests import test_wsl_entries

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'AccountStore fixtures require POSIX file permissions')
class WslAccountContinuationTests(unittest.TestCase):
    def setUp(self):
        install_target_toml(self)
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'original-home'
        self.home.mkdir()
        (self.home / 'auth.json').write_text('{"OPENAI_API_KEY":"old-fixture-key"}')
        (self.home / 'config.toml').write_text(
            'model_provider = "original_api"\nmodel = "original-model"\n'
            '[history]\npersistence = "save-all"\n'
            '[model_providers.original_api]\nname = "Original API"\n'
            'base_url = "https://old.invalid/v1"\nwire_api = "responses"\n'
            'requires_openai_auth = true\n')
        self.history = self.home / 'history.jsonl'
        self.history.write_text('{"session_id":"original","text":"retained input"}\n')
        self.draft = self.home / 'draft.json'
        self.draft.write_text('{"text":"unsent draft"}')
        self.store = worker.AccountStore('codex', self.home, guard=lambda *_: [])
        self.store.change({'action': 'save-api', 'name': 'Replacement fixture',
                           'model': 'replacement-model', 'baseUrl': 'https://new.invalid/v1',
                           'apiKey': 'new-fixture-key'})
        self.account_id = self.store.public()['accounts'][0]['id']
        self.identifier = str(uuid.uuid4())
        self.row = {'id': 'wsl:' + 'a' * 32, 'distribution': 'FixtureUbuntu',
                    'user': 'fixture', 'home': str(self.home), 'label': 'Fixture'}
        self.entry = test_wsl_entries.WslSessionTests.make_entry(self)
        self.addCleanup(self.entry.close)
        self.entry._account_route = self.store.route_summary
        self.metadata = {'id': self.identifier, 'cwd': '/home/fixture/project',
                         'model_provider': 'original_api'}
        self.entry.store = SimpleNamespace(get=lambda _: dict(self.metadata))
        self.entry.server.thread.update(modelProvider='original_api', model='original-model',
                                        status={'type': 'notLoaded'}, canAcceptDirectInput=None)
        original_request = self.entry.server.request

        def request(method, params):
            if method == 'config/read':
                self.entry.server.calls.append((method, copy.deepcopy(params)))
                return {'config': worker._toml_loads((self.home / 'config.toml').read_text())}
            if method == 'thread/resume':
                self.entry.server.thread.update(status={'type': 'idle'}, canAcceptDirectInput=True)
            return original_request(method, params)

        self.entry.server.request = request

    def switch(self):
        return self.store.change({'action': 'switch', 'id': self.account_id,
                                  'expectedIdentity': self.store.public()['identity']})

    def test_switched_files_allow_original_thread_subscription_without_new_task_or_replay(self):
        retained = {path: path.read_bytes() for path in (self.history, self.draft)}
        self.switch()
        config = worker._toml_loads((self.home / 'config.toml').read_text())
        self.assertEqual(config['model_provider'], 'original_api')
        self.assertEqual(config['model_providers']['original_api']['base_url'], 'https://new.invalid/v1')
        self.assertEqual(json.loads((self.home / 'auth.json').read_text())['OPENAI_API_KEY'], 'new-fixture-key')
        runtime, thread = self.entry._target(self.identifier, activate=True)
        self.assertIs(runtime, self.entry.server)
        self.assertEqual((thread['id'], thread['cwd'], thread['modelProvider']),
                         (self.identifier, self.metadata['cwd'], 'original_api'))
        self.assertEqual([params for method, params in runtime.calls if method == 'thread/resume'],
                         [{'threadId': self.identifier, 'excludeTurns': True}])
        self.assertTrue(all(method in ('thread/read', 'config/read', 'thread/resume')
                            for method, _ in runtime.calls))
        self.assertFalse(runtime.responses)
        self.assertFalse(self.entry.receipts_path.exists())
        self.assertEqual({path: path.read_bytes() for path in retained}, retained)

    def test_different_provider_still_rejects_before_resume_or_task(self):
        self.switch()
        self.metadata['model_provider'] = 'other_api'
        self.entry.server.thread['modelProvider'] = 'other_api'
        with self.assertRaisesRegex(IPCError, '提供商与当前接入不同'):
            self.entry._target(self.identifier, activate=True)
        self.assertEqual([method for method, _ in self.entry.server.calls], ['thread/read', 'config/read'])
        self.assertFalse(self.entry.receipts_path.exists())

    def test_project_endpoint_or_auth_override_blocks_before_resume_and_turn(self):
        self.switch()
        original = self.entry.server.request
        for override in ({'base_url': 'https://old.invalid/v1'}, {'env_key': 'PROJECT_API_KEY'},
                         {'requires_openai_auth': False}, {'http_headers': {'Authorization': 'old-private'}}):
            with self.subTest(override=override):
                def request(method, params):
                    result = original(method, params)
                    if method == 'config/read':
                        result['config']['model_providers']['original_api'].update(override)
                    return result
                self.entry.server.request = request
                self.entry.server.calls.clear()
                with self.assertRaisesRegex(IPCError, '项目覆盖'):
                    self.entry._target(self.identifier, activate=True)
                self.assertFalse(any(method in ('thread/resume', 'turn/start') for method, _ in self.entry.server.calls))
                self.assertNotIn(self.identifier, self.entry._managed_routes)
        self.entry.server.request = original

    def test_loaded_thread_without_generation_proof_requires_manual_service_exit(self):
        self.switch()
        self.entry.server.thread.update(status={'type': 'idle'}, canAcceptDirectInput=True)
        with self.assertRaisesRegex(IPCError, '退出原 WSL 服务'):
            self.entry.send(self.identifier, 'must not send', str(uuid.uuid4()))
        self.assertFalse(any(method in ('thread/resume', 'turn/start') for method, _ in self.entry.server.calls))
        self.assertFalse(self.entry.receipts_path.exists())

    def test_verified_thread_sends_with_original_id_model_and_rechecks_project_route(self):
        self.switch()
        self.entry._target(self.identifier, activate=True)
        proof = self.entry._managed_routes[self.identifier]
        self.assertEqual(proof[0], self.entry.generation)
        self.assertEqual(proof[-1], 'original-model')
        result = self.entry.send(self.identifier, 'fixture input', str(uuid.uuid4()))
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(self.entry.server.thread['model'], 'original-model')
        self.assertEqual(sum(method == 'turn/start' for method, _ in self.entry.server.calls), 1)
        self.entry.server.thread['status'] = {'type': 'idle'}
        original = self.entry.server.request
        def request(method, params):
            result = original(method, params)
            if method == 'config/read':
                result['config']['model_providers']['original_api']['base_url'] = 'https://old.invalid/v1'
            return result
        self.entry.server.request = request
        with self.assertRaisesRegex(IPCError, '项目覆盖'):
            self.entry.send(self.identifier, 'must not send', str(uuid.uuid4()))
        self.assertEqual(sum(method == 'turn/start' for method, _ in self.entry.server.calls), 1)
        self.assertFalse(any(method in ('model/list', 'config/batchWrite', 'thread/start')
                             for method, _ in self.entry.server.calls))

    def test_changed_home_identity_or_daemon_generation_invalidates_loaded_proof(self):
        self.switch()
        self.entry._target(self.identifier, activate=True)
        self.entry.generation = 'replacement-generation'
        with self.assertRaisesRegex(IPCError, '退出原 WSL 服务'):
            self.entry._target(self.identifier, activate=True)
        with (self.home / 'auth.json').open('a') as output:
            output.write(' ')
        with self.assertRaisesRegex(IPCError, '账号配置已变化'):
            self.entry._target(self.identifier, activate=True)
        self.assertFalse(any(method == 'turn/start' for method, _ in self.entry.server.calls))

    def test_failed_resume_does_not_record_managed_route_proof(self):
        self.switch()
        original = self.entry.server.request
        def request(method, params):
            if method == 'thread/resume':
                raise IPCError('fixture resume failure')
            return original(method, params)
        self.entry.server.request = request
        with self.assertRaisesRegex(IPCError, 'resume failure'):
            self.entry._target(self.identifier, activate=True)
        self.assertNotIn(self.identifier, self.entry._managed_routes)

    def test_passive_target_does_not_inspect_or_activate_managed_route(self):
        self.switch()
        self.entry.server.thread.update(status={'type': 'idle'}, canAcceptDirectInput=True)
        with patch.object(self.entry, '_account_route', side_effect=AssertionError('passive route inspection')):
            self.entry._target(self.identifier)
        self.assertEqual([method for method, _ in self.entry.server.calls], ['thread/read'])
        self.assertFalse(self.entry._managed_routes)

    def test_route_summary_transport_is_readonly_and_exposes_no_secret(self):
        from bridge.features.endpoints.wsl import WslEntry
        import contextlib
        import io
        self.switch()
        before = {path: path.read_bytes() for path in self.home.rglob('*') if path.is_file()}
        def read(_alias, source):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exec(source, {'__file__': worker.__file__})
            return json.loads(output.getvalue())
        with patch.object(self.entry, 'read', side_effect=read), \
                patch.object(worker, 'runtime_blockers', side_effect=AssertionError('no process inspection')), \
                patch.object(worker, 'fetch_models', side_effect=AssertionError('no model lookup')):
            summary = WslEntry._account_route(self.entry)
        self.assertTrue(summary['managed'])
        self.assertTrue(summary['valid'])
        self.assertEqual(summary['baseUrl'], 'https://new.invalid/v1')
        self.assertNotIn('new-fixture-key', json.dumps(summary))
        self.assertNotIn('old-fixture-key', json.dumps(summary))
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_route_store_path_uses_posix_join_even_on_windows_gateway(self):
        from bridge.features.endpoints.wsl import WslEntry
        from pathlib import PureWindowsPath
        import ast
        self.entry.row['home'] = '/home/fixture/.codex'
        captured = []
        def read(_alias, source):
            captured.append(source)
            return {'managed': False}
        # Windows Path must not participate in constructing target Linux paths.
        with patch('bridge.features.endpoints.wsl.Path', PureWindowsPath), \
                patch.object(self.entry, 'read', side_effect=read):
            self.assertEqual(WslEntry._account_route(self.entry), {'managed': False})
        tree = ast.parse(captured[0])
        path = next(node.args[0].value for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'lexists')
        self.assertEqual(path, '/home/fixture/.codex/.codex-mobile-bridge-accounts/store.json')
        self.assertNotIn('\\', path)

    def test_unmanaged_home_does_not_enter_account_store_path_validation(self):
        from bridge.features.endpoints.wsl import WslEntry
        import contextlib
        import io
        legacy = Path(self.temp.name) / 'legacy'
        legacy.mkdir()
        alias = Path(self.temp.name) / 'linked-home'
        alias.symlink_to(legacy, target_is_directory=True)
        self.entry.row['home'] = str(alias)
        def read(_alias, source):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exec(source, {'__file__': worker.__file__})
            return json.loads(output.getvalue())
        with patch.object(self.entry, 'read', side_effect=read):
            self.assertEqual(WslEntry._account_route(self.entry), {'managed': False})
        self.assertFalse(list(legacy.iterdir()))

    def test_create_project_route_rejection_precedes_durable_creation_receipt(self):
        self.switch()
        self.entry.store.list = lambda **_kwargs: [{'cwd': self.metadata['cwd']}]
        self.entry.read = lambda *_args, **_kwargs: {'cwd': self.metadata['cwd']}
        original = self.entry.server.request
        def request(method, params):
            result = original(method, params)
            if method == 'config/read':
                result['config']['model_providers']['original_api']['base_url'] = 'https://old.invalid/v1'
            return result
        self.entry.server.request = request
        with self.assertRaisesRegex(IPCError, '项目覆盖'):
            self.entry.create_chat(self.entry.host+'|'+self.metadata['cwd'], 'Fixture', str(uuid.uuid4()))
        self.assertFalse(self.entry.creations_path.exists())
        self.assertFalse(self.entry.creations)
        self.assertFalse(any(method in ('thread/start', 'turn/start') for method, _ in self.entry.server.calls))

    def test_verified_send_rechecks_route_once_and_rejection_creates_no_unknown_receipt(self):
        self.switch()
        self.entry._target(self.identifier, activate=True)
        self.entry.server.calls.clear()
        original = self.entry.server.request
        def request(method, params):
            result = original(method, params)
            if method == 'config/read':
                result['config']['model_providers']['original_api']['base_url'] = 'https://old.invalid/v1'
            return result
        self.entry.server.request = request
        with patch.object(self.entry, '_account_route', wraps=self.store.route_summary) as route:
            with self.assertRaisesRegex(IPCError, '项目覆盖'):
                self.entry.send(self.identifier, 'must not send', str(uuid.uuid4()))
        route.assert_called_once()
        self.assertEqual(sum(method == 'config/read' for method, _ in self.entry.server.calls), 1)
        self.assertFalse(self.entry.receipts_path.exists())
        self.assertFalse(self.entry.receipts)
        self.assertFalse(any(method == 'turn/start' for method, _ in self.entry.server.calls))

    def test_running_daemon_guard_still_prevents_account_file_write(self):
        before = self.store.files()
        self.store.guard = lambda *_: ['fixture shared daemon remains running']
        with patch.object(worker, '_write', side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(worker.AccountError, 'daemon'):
                self.switch()
        self.assertEqual(self.store.files(), before)
        self.assertFalse(self.entry.server.calls)
