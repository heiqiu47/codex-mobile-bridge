"""Native membership is separate from cwd; no fixture starts a model."""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from bridge.app.service import Bridge
from bridge.clients.claude.adapter import Claude
from bridge.clients.errors import BridgeUnavailable
from bridge.features.sessions.create import CreationError, CreationUnavailable, create_empty

ROOT = Path(__file__).resolve().parents[1]


class NativeCodexProjects(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        self.cwd = str(Path(temporary.name).resolve())
        self.thread_id = str(uuid.uuid4())
        self.calls = []
        self.pages = [{'data': [], 'nextCursor': None}]
        self.confirmed = 'native-project'

    def request(self, method, params):
        self.calls.append((method, params))
        if method == 'project/list':
            return self.pages.pop(0)
        if method == 'project/create':
            return {'project': {'id': 'native-project'}}
        if method in ('thread/start', 'thread/read'):
            return {'thread': {'id': self.thread_id, 'projectId': self.confirmed}}
        if method == 'thread/name/set':
            return {}
        self.fail('Unexpected runtime operation: ' + method)

    def create(self, project=None, supported=True):
        with patch('bridge.features.sessions.create._native_project_support', return_value=supported), \
             patch('bridge.features.sessions.create._runtime_operation', side_effect=lambda a,b,c,run: run(self.request)):
            return create_empty('fixture', self.cwd, self.cwd, 'A chat', project=project)

    def test_runtime_only_project_does_not_claim_native_sidebar_registration(self):
        with self.assertRaisesRegex(CreationUnavailable, '电脑 App 项目与运行时'):
            self.create({'name': 'Project', 'required': True})
        self.assertEqual(self.calls, [('project/list', {'cursor': None, 'limit': 100})])

    def test_reuses_paginated_native_project_with_canonical_root_without_mutating_it(self):
        alias = Path(self.cwd)/'alias'
        alias.symlink_to(self.cwd, target_is_directory=True)
        self.pages = [{'data': [], 'nextCursor': 'second'},
                      {'data': [{'id': 'native-project', 'name': 'Original', 'roots': [{'path': str(alias)}]}]}]
        self.create({'name': 'Original', 'required': True})
        self.assertEqual(self.calls[1], ('project/list', {'cursor': 'second', 'limit': 100}))
        self.assertNotIn('project/create', [method for method, _ in self.calls])
        self.assertEqual(self.calls[2][1]['projectId'], 'native-project')

    def test_ambiguous_same_directory_projects_never_start_a_thread(self):
        self.pages = [{'data': [{'id': value, 'name': value, 'roots': [{'path': self.cwd}]} for value in ('one', 'two')]}]
        with self.assertRaisesRegex(CreationError, '多个原生项目'):
            self.create({'name': 'Unmatched', 'required': True})
        self.assertEqual([method for method, _ in self.calls], ['project/list'])

    def test_unconfirmed_assignment_keeps_uncertain_outcome_without_retry(self):
        self.confirmed = None
        self.pages = [{'data': [{'id': 'native-project', 'name': 'Project', 'roots': [{'path': self.cwd}]}]}]
        with self.assertRaisesRegex(CreationError, '不要重复创建'):
            self.create({'name': 'Project', 'required': True})
        self.assertEqual(sum(method == 'thread/start' for method, _ in self.calls), 1)

    def test_independent_and_old_saved_project_can_keep_existing_runtime_path(self):
        for project in (None, {'name': 'Saved', 'required': False}):
            self.calls.clear()
            self.create(project, supported=False)
            self.assertEqual(self.calls[0], ('thread/start', {'cwd': self.cwd, 'ephemeral': False}))

    def test_old_runtime_rejects_new_directory_before_runtime_start(self):
        from bridge.features.sessions.create import _native_project_support
        with patch('bridge.features.sessions.create.subprocess.run', return_value=Mock(returncode=0)), \
             patch('bridge.features.sessions.create._runtime_operation') as runtime:
            with self.assertRaisesRegex(CreationUnavailable, '原生项目关联'):
                create_empty('old-runtime', self.cwd, self.cwd, 'New', project={'required': True})
            runtime.assert_not_called()
            self.assertFalse(_native_project_support('old-runtime', False))


class NativeProjectSelection(unittest.TestCase):
    def test_gateway_and_native_canonical_root_are_one_choice_with_existing_project_fallback(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        alias = root/'alias'
        alias.symlink_to(root, target_is_directory=True)
        bridge = Bridge(root, root/'data')
        self.addCleanup(bridge.close)
        bridge.hosts.projects = lambda: [{'key': 'local|native', 'host': 'local',
            'name': 'Original native project', 'cwd': str(alias)}]
        bridge.hosts.hosts = lambda: {}
        bridge.store.list = lambda **kwargs: []
        registered = bridge.register_project(str(root))
        choices = bridge.projects()
        self.assertEqual(len(choices), 1)
        self.assertTrue(choices[0]['nativeProject'])
        bridge.ipc.connect = Mock()
        with patch('bridge.app.service.create_empty', return_value=str(uuid.uuid4())) as create, \
             patch('bridge.app.service.open_in_desktop'):
            bridge.create_chat(registered['key'], 'Selected chat', str(uuid.uuid4()))
        self.assertFalse(create.call_args.kwargs['project']['required'])


class NativeSidebarRegistration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bridge = Bridge(self.root, self.root/'data')
        self.addCleanup(self.bridge.close)
        self.native = []
        self.bridge.hosts.projects = lambda: list(self.native)
        self.bridge.hosts.hosts = lambda: {}
        self.bridge.store.list = lambda **kwargs: []
        self.bridge.ipc.connect = Mock()
        self.project = self.bridge.register_project(str(self.root))
        self.rid = str(uuid.uuid4())
        self.tid = str(uuid.uuid4())

    def register_native(self, cwd):
        self.native.append({'key': 'local|native-ui', 'host': 'local', 'name': 'Native UI', 'cwd': cwd})

    def test_explicit_create_confirms_sidebar_registration_before_thread_creation(self):
        with patch('bridge.app.service.open_project_in_desktop', side_effect=self.register_native) as launch, \
             patch('bridge.app.service.open_in_desktop'), \
             patch('bridge.app.service.create_empty', return_value=self.tid) as create:
            self.bridge.projects()
            launch.assert_not_called()
            self.bridge.create_chat(self.project['key'], 'Chat', self.rid)
            launch.assert_called_once_with(str(self.root))
            self.assertEqual(create.call_args.kwargs['project'], {'name': 'Native UI', 'required': False})
            self.assertEqual(self.bridge.creations[self.rid]['id'], self.tid)

    def test_late_native_registration_and_unknown_thread_never_replay_either_write(self):
        with patch('bridge.app.service.open_project_in_desktop') as launch, \
             patch('bridge.app.service.time.monotonic', side_effect=[0, 13]), \
             patch('bridge.app.service.create_empty') as create:
            with self.assertRaisesRegex(CreationError, '尚未创建聊天'):
                self.bridge.create_chat(self.project['key'], 'Chat', self.rid)
            launch.assert_called_once()
            create.assert_not_called()
        self.assertEqual(self.bridge.creations[self.rid]['phase'], 'registering-project')
        self.register_native(str(self.root))
        self.assertTrue(self.bridge.projects()[0]['nativeProject'])
        with patch('bridge.app.service.open_project_in_desktop') as relaunch, \
             patch('bridge.app.service.create_empty', side_effect=CreationError('read timed out after thread/start')) as create:
            with self.assertRaisesRegex(CreationError, 'read timed out'):
                self.bridge.create_chat(self.project['key'], 'Chat', self.rid)
            self.assertEqual(self.bridge.creations[self.rid]['phase'], 'creating-thread')
            with self.assertRaisesRegex(CreationError, '上次创建结果尚不确定'):
                self.bridge.create_chat(self.project['key'], 'Chat', self.rid)
            create.assert_called_once()
            relaunch.assert_not_called()

    def test_unconfirmed_registration_never_launches_twice_or_creates_thread(self):
        with patch('bridge.app.service.open_project_in_desktop', side_effect=OSError('unknown launch')) as launch, \
             patch('bridge.app.service.create_empty') as create:
            for _ in range(2):
                with self.assertRaisesRegex(CreationError, '尚未创建聊天'):
                    self.bridge.create_chat(self.project['key'], 'Chat', self.rid)
            launch.assert_called_once()
            create.assert_not_called()

    def test_native_project_url_has_only_path_and_uses_existing_platform_launcher(self):
        from urllib.parse import parse_qs, urlsplit
        from bridge.features.sessions.create import open_project_in_desktop
        cwd = '/fixture/quoted " directory $()'
        with patch('bridge.features.sessions.create.sys.platform', 'darwin'), \
             patch('bridge.features.sessions.create.subprocess.run') as launch:
            open_project_in_desktop(cwd)
        args = launch.call_args.args[0]
        self.assertEqual(args[0], 'open')
        url = urlsplit(args[1])
        self.assertEqual((url.scheme, url.netloc, url.path), ('codex', 'threads', '/new'))
        self.assertEqual(parse_qs(url.query), {'path': [cwd]})
        self.assertNotIn('prompt', url.query)
        self.assertNotIn('message', url.query)



class ClaudeProjectTrust(unittest.IsolatedAsyncioTestCase):
    async def test_native_trust_rejection_is_actionable_and_preserves_scope(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        adapter = Claude(Path(temporary.name))
        adapter.desktop = Mock(capabilities={'code': ['start']})
        adapter.desktop.call = AsyncMock(side_effect=BridgeUnavailable(
            "Error invoking remote method '$eipc_message$_5c55def3-2e9e-44fa-af10-a18b58800855_$_claude.web_$_LocalSessions_$_start': WorkspaceTrustError: Workspace requires trust approval before starting a session. [ccdErrorCategory:trust_required]"))
        with patch.object(adapter, 'status', return_value={'connected': True}):
            result = await adapter.dispatch('create', None, {'title': 'My chat', 'firstMessage': 'My draft',
                'directoryProject': {'surface': 'code', 'cwd': temporary.name}})
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['code'], 'workspace-trust-required')
        self.assertEqual(result['workspace'], temporary.name)
        self.assertIn('Claude Desktop', result['message'])
        adapter.desktop.call.assert_awaited_once_with('code', 'start', {
            'title': 'My chat', 'message': 'My draft', 'cwd': temporary.name, 'useWorktree': False})

    async def test_unverified_trust_markers_remain_uncertain(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        adapter = Claude(Path(temporary.name))
        adapter.desktop = Mock()
        for text in ('WorkspaceTrustError: trust_required', 'trust_required',
                     'Workspace requires trust approval before starting a session. Then timed out',
                     'Workspace requires trust approval before starting a session. [ccdErrorCategory:timeout]',
                     'Workspace requires trust approval before starting a session. [ccdErrorCategory:trust_required] Then timed out'):
            adapter.desktop.call = AsyncMock(side_effect=BridgeUnavailable(text))
            with self.subTest(error=text), self.assertRaises(BridgeUnavailable):
                await adapter._start_desktop_project({'surface': 'code', 'cwd': temporary.name}, {'message': 'draft'})

    async def test_disconnect_is_still_uncertain_and_not_a_trust_retry(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        adapter = Claude(Path(temporary.name))
        adapter.desktop = Mock()
        adapter.desktop.call = AsyncMock(side_effect=BridgeUnavailable('Claude Desktop 响应超时'))
        with self.assertRaisesRegex(BridgeUnavailable, '响应超时'):
            await adapter._start_desktop_project({'surface': 'code', 'cwd': temporary.name}, {'message': 'draft'})
        adapter.desktop.call.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
