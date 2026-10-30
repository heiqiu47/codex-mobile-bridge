import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from bridge.app.lifecycle import private_json
from bridge.clients.manager import DesktopSessions
from bridge.features.sessions.display_metadata import DisplayMetadata, RenameCommands
from bridge.features.sessions.organization import OrganizationNotSent
import test_bridge


def change(kind, **values):
    return {'id': str(uuid.uuid4()), 'kind': kind, **values}


class DisplayMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.tmp')
        self.addCleanup(self.temp.cleanup)
        self.store = DisplayMetadata(self.temp.name, private_json)

    def test_persistent_project_section_and_alias_do_not_change_native_identity(self):
        project = self.store.change('one', 'chat', change('create-project', title='工程'))
        section = self.store.change('one', 'chat', change('create-section', title='待办'))
        self.store.change('one', 'chat', change('rename', title='显示名称'))
        original = {'id': 'chat', 'title': 'Native', 'cwd': '/original', 'owner': 'owner', 'provider': 'upstream'}
        row = DisplayMetadata(self.temp.name, private_json).decorate('one', original)
        self.assertEqual(row['title'], '显示名称')
        self.assertEqual(row['projectId'], project['projectId'])
        self.assertEqual(row['sectionId'], section['sectionId'])
        self.assertEqual(row['projectName'], '工程')
        for field in ('cwd', 'owner', 'provider'):
            self.assertEqual(row[field], original[field])
        self.assertEqual(self.store.decorate('two', original), original)
        self.assertEqual(original['title'], 'Native')

    def test_idempotent_create_conflict_and_stale_assignment(self):
        body = change('create-project', title='项目')
        first = self.store.change('one', 'chat', body)
        self.assertEqual(self.store.change('one', 'chat', body), first)
        self.assertEqual(len(self.store.snapshot('one', 'chat')['projects']), 1)
        with self.assertRaises(ValueError):
            self.store.change('one', 'other', body)
        with self.assertRaises(ValueError):
            self.store.change('one', 'chat', change('project', targetId=None, expectedId='stale'))
        self.store.change('one', 'chat', change('project', targetId=None, expectedId=first['projectId']))
        self.assertIsNone(self.store.snapshot('one', 'chat')['projectId'])

    def test_native_rename_unknown_blocks_new_request_after_restart(self):
        commands = RenameCommands(self.temp.name, private_json)
        read = Mock(return_value={'identity': {'id': 'chat', 'cwd': '/project'}, 'title': 'old'})
        dispatch = Mock(side_effect=TimeoutError)
        body = {'id': str(uuid.uuid4()), 'title': 'new'}
        with self.assertRaisesRegex(ValueError, '待核对'):
            commands.perform('chat', body, read, dispatch)
        with self.assertRaisesRegex(ValueError, '待核对'):
            RenameCommands(self.temp.name, private_json).perform('chat', {**body, 'id': str(uuid.uuid4())}, read, dispatch)
        dispatch.assert_called_once()
        read.return_value['title'] = 'new'
        result = RenameCommands(self.temp.name, private_json).perform('chat', body, read, dispatch)
        self.assertEqual(result['status'], 'confirmed')
        dispatch.assert_called_once()

    def test_explicit_not_sent_can_be_corrected(self):
        commands = RenameCommands(self.temp.name, private_json)
        read = Mock(return_value={'identity': {'id': 'chat'}, 'title': 'old'})
        body = {'id': str(uuid.uuid4()), 'title': 'new'}
        with self.assertRaises(OrganizationNotSent):
            commands.perform('chat', body, read, lambda title: {'notSent': True})
        def dispatch(title):
            read.return_value['title'] = title
        self.assertEqual(commands.perform('chat', body, read, dispatch)['status'], 'confirmed')


class ManagerMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.tmp')
        self.addCleanup(self.temp.cleanup)
        self.manager = DesktopSessions(self.temp.name)
        self.addCleanup(self.manager.close)
        self.manager.config['enabled'] = {'claude': True, 'deepseek': True}
        self.row = {'id': 'chat', 'title': 'old', 'cwd': '/original', 'host': 'local', 'backend': 'cli'}
        self.calls = []
        self.project = None
        self.manager._adapter_call = self.adapter_call

    def adapter_call(self, provider, action, sid, body):
        self.calls.append((action, body))
        if action == 'list':
            return {'sessions': [dict(self.row)], 'connected': True}
        if action == 'detail':
            return {'session': dict(self.row)}
        if action == 'rename':
            self.row['title'] = body['title']
            return {'status': 'confirmed'}
        if action == 'organization':
            if body['operation'] == 'set-project':
                self.project = body['projectId']
            return {'scope': 'native', 'status': 'confirmed', 'projectId': self.project,
                    'projects': [{'id': 'p', 'title': 'Original'}], 'identity': {'id': 'chat', 'cwd': '/original'}}
        self.fail('Unexpected action: ' + action)

    def test_cli_rename_and_categories_only_write_gateway_metadata(self):
        self.manager.call('claude', 'rename', 'chat', {'id': str(uuid.uuid4()), 'title': 'Alias'})
        self.manager.call('claude', 'organization', 'chat', change('create-project', title='Project'))
        rows = self.manager.call('claude', 'list')['sessions']
        self.assertEqual(rows[0]['title'], 'Alias')
        self.assertEqual(rows[0]['projectName'], 'Project')
        self.assertEqual(self.row['title'], 'old')
        self.assertTrue(all(action == 'list' for action, body in self.calls))

    def test_native_rename_readback_and_bridge_alias_removal(self):
        self.manager.call('deepseek', 'rename', 'chat', {'id': str(uuid.uuid4()), 'title': 'Alias'})
        self.row['capabilities'] = {'rename': True}
        result = self.manager.call('deepseek', 'rename', 'chat', {'id': str(uuid.uuid4()), 'title': 'Native'})
        self.assertEqual(result['title'], 'Native')
        self.assertEqual(self.manager.call('deepseek', 'list')['sessions'][0]['title'], 'Native')
        self.assertEqual(self.row['cwd'], '/original')

    def test_native_project_and_local_section_preserve_mixed_scope(self):
        self.row['capabilities'] = {'organization': True}
        result = self.manager.call('deepseek', 'organization', 'chat', change('project', targetId='p', expectedId=None))
        self.assertEqual(result['projectId'], 'p')
        result = self.manager.call('deepseek', 'organization', 'chat', change('create-section', title='Todo'))
        self.assertEqual(result['projectId'], 'p')
        self.assertEqual(result['sections'][0]['title'], 'Todo')
        self.assertEqual(result['sectionScope'], 'bridge')
        self.assertEqual(result['projectScope'], 'native')
        self.assertEqual(sum(body.get('operation') == 'set-project' for _, body in self.calls), 1)


class MetadataHttpTests(unittest.TestCase):
    setUpClass = classmethod(test_bridge.HttpTests.setUpClass.__func__)
    setUp = test_bridge.HttpTests.setUp
    tearDown = test_bridge.HttpTests.tearDown
    request = test_bridge.HttpTests.request
    login = test_bridge.HttpTests.login

    def test_rename_and_organization_preserve_auth_csrf_and_opaque_session_id(self):
        manager = self.server.desktop_sessions = Mock()
        manager.call.return_value = {'status': 'confirmed'}
        for provider in ('claude', 'deepseek'):
            route = '/api/desktop-sessions/' + provider + '/organization'
            self.assertEqual(self.request('GET', route + '?sessionId=code%2Fnative')[0], 401)
            headers = self.login()
            self.assertEqual(self.request('GET', route + '?sessionId=code%2Fnative', headers=headers)[0], 200)
            manager.call.assert_called_with(provider, 'organization', 'code/native', {})
            for action, values in (('rename', {'title': '新名称'}), ('organization', {'kind': 'create-section', 'title': '待办'})):
                body = {'sessionId': 'code/native', 'id': str(uuid.uuid4()), **values}
                target = '/api/desktop-sessions/' + provider + '/' + action
                self.assertEqual(self.request('POST', target, body, {'Cookie': headers['Cookie']})[0], 403)
                self.assertEqual(self.request('POST', target, body, headers)[0], 200)
                manager.call.assert_called_with(provider, action, 'code/native', {key: value for key, value in body.items() if key != 'sessionId'})


if __name__ == '__main__':
    unittest.main()
