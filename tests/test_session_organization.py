"""Native moves preserve execution identity and reject stale or unknown destinations."""
import copy
import unittest
import uuid
import threading
import tempfile
from bridge.app.lifecycle import private_json
from bridge.features.sessions.organization_commands import OrganizationCommands
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge.features.sessions.organization import organization
from bridge.app.service import Bridge
from bridge.features.endpoints.wsl import WslEntry
from bridge.clients.codex.remote import RemoteStore
import test_bridge


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.identifier = str(uuid.uuid4())
        self.thread = {'id': self.identifier, 'cwd': '/original', 'modelProvider': 'original',
                       'projectId': 'p1', 'section': None}
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/read':
            return {'thread': copy.deepcopy(self.thread)}
        if method == 'project/list':
            return {'data': [{'id': 'p1', 'name': 'One'}, {'id': 'p2', 'name': 'Two'}], 'nextCursor': None}
        if method == 'threadSection/list':
            return {'data': [{'id': 's1', 'name': 'Section'}], 'nextCursor': None}
        if method == 'thread/metadata/update':
            self.thread['projectId'] = params['projectId'] or None
        elif method == 'thread/section/move':
            self.thread['section'] = {'id': params['sectionId']} if params['sectionId'] else None
        else:
            self.fail('Unexpected native method: ' + method)
        return {}

    def move(self, kind='project', target='p2', expected='p1'):
        return organization(self.request, self.identifier,
                            {'kind': kind, 'targetId': target, 'expectedId': expected}, expected_cwd='/original')

    def writes(self):
        return [item for item in self.calls if item[0] in ('thread/metadata/update', 'thread/section/move')]

    def test_read_is_metadata_only(self):
        result = organization(self.request, self.identifier)
        self.assertEqual(result['projectId'], 'p1')
        self.assertFalse(self.writes())

    def test_project_move_and_clear_preserve_execution_settings(self):
        self.assertEqual(self.move()['projectId'], 'p2')
        self.assertEqual(self.move(target=None, expected='p2')['projectId'], None)
        self.assertEqual(self.writes()[-1][1], {'threadId': self.identifier, 'projectId': ''})
        self.assertEqual(self.thread['cwd'], '/original')
        self.assertEqual(self.thread['modelProvider'], 'original')

    def test_section_move_and_clear(self):
        self.assertEqual(self.move('section', 's1', None)['sectionId'], 's1')
        self.assertIsNone(self.move('section', None, 's1')['sectionId'])
        self.assertEqual(self.writes()[-1][1]['sectionId'], None)

    def test_repeat_of_confirmed_assignment_does_not_dispatch(self):
        self.move()
        self.move()
        self.assertEqual(len(self.writes()), 1)

    def test_stale_or_missing_destination_never_dispatches(self):
        for target, expected in [('gone', 'p1'), ('p2', 'old')]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.move(target=target, expected=expected)
        self.assertFalse(self.writes())

    def test_changed_cwd_is_rejected_before_listing_or_writing(self):
        self.thread['cwd'] = '/different'
        with self.assertRaisesRegex(ValueError, '工作目录'):
            self.move()
        self.assertEqual(len(self.calls), 1)

    def test_windows_extended_paths_match_rpc_without_using_gateway_path_rules(self):
        for stored, native in [(r'\\?\D:\Work\Project', r'D:\Work\Project'),
                               (r'\\?\UNC\server\share\Project', r'\\server\share\Project')]:
            with self.subTest(stored=stored):
                self.thread['cwd'] = native
                self.assertEqual(organization(self.request, self.identifier, expected_cwd=stored)['id'], self.identifier)
        self.thread['cwd'] = '/work/project'
        with self.assertRaisesRegex(ValueError, '工作目录'):
            organization(self.request, self.identifier, expected_cwd='/work/Project')

    def test_empty_body_is_invalid(self):
        with self.assertRaises(ValueError):
            organization(self.request, self.identifier, {})
        self.assertFalse(self.writes())

    def test_unknown_write_is_never_replayed(self):
        def request(method, params):
            if method == 'thread/metadata/update':
                self.request(method, params)
                raise TimeoutError('reply lost')
            return self.request(method, params)
        with self.assertRaises(TimeoutError):
            organization(request, self.identifier, {'kind': 'project', 'targetId': 'p2', 'expectedId': 'p1'})
        self.assertEqual(len(self.writes()), 1)

    def test_unknown_write_survives_restart_and_new_request_id_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = OrganizationCommands(directory, private_json)
            change = {'id': str(uuid.uuid4()), 'kind': 'project', 'targetId': 'p2', 'expectedId': 'p1'}
            read = lambda: organization(self.request, self.identifier)
            sent = []
            def dispatch(_change):
                sent.append(_change)
                raise TimeoutError('sent, reply lost; read replica still old')
            with self.assertRaisesRegex(ValueError, '不会重复提交'):
                commands.perform(self.identifier, change, read, dispatch)
            for request_id in [change['id'], str(uuid.uuid4())]:
                commands = OrganizationCommands(directory, private_json)
                with self.assertRaisesRegex(ValueError, '不会重复提交'):
                    commands.perform(self.identifier, {**change, 'id': request_id}, read, dispatch)
            self.assertEqual(len(sent), 1)
            self.assertEqual(commands.native_memberships(), set())
            self.thread['projectId'] = 'p2'
            result = commands.perform(self.identifier, change, read, dispatch)
            self.assertEqual(result['status'], 'confirmed')
            self.assertEqual(commands.native_memberships(), {self.identifier})
            self.assertEqual(len(sent), 1)
            self.thread['projectId'] = 'p1'
            commands.perform(self.identifier, change, read, dispatch)
            self.assertEqual(len(sent), 1, 'old confirmed receipt cannot move a later assignment back')

    def test_receipts_validate_destination_identity_and_prevent_id_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = OrganizationCommands(directory, private_json)
            change = {'id': str(uuid.uuid4()), 'kind': 'project', 'targetId': 'gone', 'expectedId': 'p1'}
            read = lambda: organization(self.request, self.identifier)
            dispatch = lambda body: organization(self.request, self.identifier, body)
            with self.assertRaisesRegex(ValueError, '移除'):
                commands.perform(self.identifier, change, read, dispatch)
            self.assertFalse(commands.path.exists())
            change['targetId'] = 'p2'
            commands.perform(self.identifier, change, read, dispatch)
            with self.assertRaisesRegex(ValueError, '不同操作'):
                commands.perform(self.identifier, {**change, 'targetId': None}, read, dispatch)
            self.assertEqual(len(self.writes()), 1)

    def test_unconfirmed_result_is_rejected(self):
        def request(method, params):
            return {} if method == 'thread/metadata/update' else self.request(method, params)
        with self.assertRaisesRegex(ValueError, '待核对'):
            organization(request, self.identifier, {'kind': 'project', 'targetId': 'p2', 'expectedId': 'p1'})

    def test_pagination_is_bounded_and_repeated_cursor_is_rejected(self):
        def request(method, params):
            if method == 'project/list':
                return {'data': [], 'nextCursor': 'same'}
            return self.request(method, params)
        with self.assertRaises(ValueError):
            organization(request, self.identifier)

    def test_change_during_listing_is_rejected_before_dispatch(self):
        def request(method, params):
            value = self.request(method, params)
            if method == 'threadSection/list':
                self.thread['projectId'] = 'external'
            return value
        with self.assertRaisesRegex(ValueError, '其他客户端'):
            organization(request, self.identifier, {'kind': 'project', 'targetId': 'p2', 'expectedId': 'p1'})
        self.assertFalse(self.writes())

    def test_bridge_uses_original_home_and_preserves_thread_identity(self):
        bridge = SimpleNamespace(store=Mock(), session=Mock(return_value=SimpleNamespace(action_lock=threading.RLock())),
                                 catalog_reader=SimpleNamespace(executable='original-runtime'), codex_home=Path('/original-home'), host='local')
        bridge.store.get.return_value = {'cwd': '/original'}
        with patch('bridge.features.sessions.create._runtime_operation', side_effect=lambda exe,home,cwd,run,**kw:run(self.request)) as runtime:
            result = Bridge.organization.__wrapped__(bridge, self.identifier)
        self.assertEqual(result['id'], self.identifier)
        self.assertEqual(result['host'], 'local')
        self.assertEqual(runtime.call_args.args[:3], ('original-runtime', Path('/original-home'), str(Path('/original-home'))))
        bridge.session.assert_called_once_with(self.identifier, attach=False, background=True)

    def test_wsl_connects_original_runtime_without_start_or_activation(self):
        entry = SimpleNamespace(store=Mock(), runtime=Mock(return_value=SimpleNamespace(request=self.request)), host='wsl:fixture')
        entry.store.get.return_value = {'cwd': '/original'}
        self.assertEqual(WslEntry.organization.__wrapped__(entry, self.identifier)['host'], 'wsl:fixture')
        entry.runtime.assert_called_once_with(allow_start=False)
        self.assertFalse(self.writes())

    def test_ssh_uses_the_selected_host_and_self_contained_source(self):
        store = Mock(spec=RemoteStore)
        store.get.return_value = {'cwd': '/original'}
        store.alias, store.cache, store.lock = 'selected-host', {'old': {}}, threading.RLock()
        bridge = SimpleNamespace(store=store, session=Mock(return_value=SimpleNamespace(action_lock=threading.RLock())), host='remote')
        result = organization(self.request, self.identifier)
        result.update(projectId='p2')
        change = {'id': str(uuid.uuid4()), 'kind': 'project', 'targetId': 'p2', 'expectedId': 'p1'}
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        bridge.organization_commands = OrganizationCommands(temporary.name, private_json)
        before = organization(self.request, self.identifier)
        with patch('bridge.app.service.ssh_read', side_effect=[before, result]) as read:
            self.assertEqual(Bridge.organization.__wrapped__(bridge, self.identifier, change)['host'], 'remote')
        self.assertEqual(read.call_args.args[0], 'selected-host')
        compile(read.call_args.args[1], '<remote-organization>', 'exec')
        self.assertIn('def organization(', read.call_args.args[1])
        self.assertIn('def _runtime_operation(', read.call_args.args[1])
        self.assertEqual(store.cache, {})

    def test_native_ssh_error_is_visible_and_never_retried(self):
        store = Mock(spec=RemoteStore)
        store.get.return_value = {'cwd': '/original'}
        store.alias = 'selected-host'
        bridge = SimpleNamespace(store=store, session=Mock(return_value=SimpleNamespace(action_lock=threading.RLock())), host='remote')
        with patch('bridge.app.service.ssh_read', return_value={'error': 'native unavailable'}) as read:
            with self.assertRaisesRegex(ValueError, 'native unavailable'):
                Bridge.organization.__wrapped__(bridge, self.identifier)
        read.assert_called_once()


class OrganizationHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = test_bridge.password_record('correct password test')

    setUp = test_bridge.HttpTests.setUp
    tearDown = test_bridge.HttpTests.tearDown
    request = test_bridge.HttpTests.request
    login = test_bridge.HttpTests.login

    def test_native_organization_is_authenticated_host_scoped_and_csrf_protected(self):
        target = '/api/sessions/' + test_bridge.THREAD + '/organization?host=local'
        self.server.bridge.organization = Mock(return_value={'status': 'confirmed'})
        self.assertEqual(self.request('GET', target)[0], 401)
        self.server.bridge.organization.assert_not_called()
        headers = self.login()
        self.assertEqual(self.request('GET', target, headers=headers)[0], 200)
        self.server.bridge.organization.assert_called_once_with(test_bridge.THREAD, None)
        self.server.bridge.organization.reset_mock()
        body = {'kind': 'section', 'targetId': None, 'expectedId': 's1'}
        self.assertEqual(self.request('POST', target, body, {'Cookie': headers['Cookie']})[0], 403)
        self.server.bridge.organization.assert_not_called()
        self.assertEqual(self.request('POST', target, body, headers)[0], 200)
        self.server.bridge.organization.assert_called_once_with(test_bridge.THREAD, body)
        self.assertEqual(self.request('GET', target.replace('host=local', 'host=missing'), headers=headers)[0], 404)


if __name__ == '__main__':
    unittest.main()
