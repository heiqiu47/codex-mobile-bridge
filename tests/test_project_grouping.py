"""Only saved native project memberships determine chat list groups."""
import unittest
from pathlib import Path

from bridge.clients.codex.remote import AppHosts


class ProjectGroupingTests(unittest.TestCase):
    def test_unassigned_chats_share_one_group_regardless_of_directory_or_host_platform(self):
        directories = ['D:/Work/Project', 'D:/Other', r'\\?\D:\Work\Project',
                       r'\\server\share\Project', '/work/Project', '/work/project', '']
        for host in ['local', 'ssh']:
            rows = [{'id': str(index), 'cwd': cwd, 'origin': 'desktop', 'model_provider': 'fixture'}
                    for index, cwd in enumerate(directories)]
            self.hosts.decorate(rows, host, host)
            self.assertEqual({row['projectKey'] for row in rows}, {host + '|unassigned'})
            self.assertEqual({row['projectName'] for row in rows}, {'未归类'})
            self.assertEqual([row['cwd'] for row in rows], directories)
            self.assertTrue(all(row['model_provider'] == 'fixture' and row['origin'] == 'desktop' for row in rows))

    def test_empty_native_membership_does_not_infer_a_project_from_its_directory(self):
        row = {'id': 'fixture', 'cwd': 'D:/Work/Project', '_nativeProject': None}
        self.hosts.decorate([row], 'local', 'Local')
        self.assertEqual(row['projectKey'], 'local|unassigned')

    def test_native_assignment_wins_over_saved_legacy_mapping_and_cwd(self):
        row = {'id': 'fixture', 'cwd': 'D:/Work/Project', '_nativeProject': {'id': 'native', 'name': 'Native'}}
        self.hosts.decorate([row], 'local', 'Local')
        self.assertEqual(row['projectKey'], 'local|native')
        self.assertEqual(row['projectName'], 'Native')
        self.assertNotIn('_nativeProject', row)

    def test_explicit_projectless_marker_keeps_thread_outside_inferred_project(self):
        self.saved['projectless-thread-ids'] = ['fixture']
        row = {'id': 'fixture', 'cwd': 'D:/Work/Project', '_nativeProject': None}
        self.hosts.decorate([row], 'local', 'Local')
        self.assertEqual(row['projectKey'], 'local|unassigned')
        self.assertEqual(row['projectName'], '未归类')

    def test_empty_native_membership_preserves_existing_assignment_during_migration(self):
        self.saved['thread-project-assignments'] = {'fixture': {'projectKind': 'local', 'projectId': 'local'}}
        row = {'id': 'fixture', 'cwd': 'D:/Other', '_nativeProject': None}
        self.hosts.decorate([row], 'local', 'Local')
        self.assertEqual(row['projectKey'], 'local|local')
        self.assertEqual(row['projectName'], 'Local')


    def test_native_assignment_wins_over_stale_projectless_marker(self):
        self.saved['projectless-thread-ids'] = ['fixture']
        row = {'id': 'fixture', 'cwd': 'D:/Work/Project', '_nativeProject': {'id': 'native', 'name': 'Native'}}
        self.hosts.decorate([row], 'local', 'Local')
        self.assertEqual(row['projectKey'], 'local|native')

    def test_native_and_existing_memberships_share_one_group_during_migration(self):
        self.saved['app-server-project-id-by-legacy-project-id-by-host'] = {'local:/fixture': {'local': 'native'}}
        self.saved['thread-project-assignments'] = {'older-chat': {'projectId': 'local'}}
        rows = [{'id': 'native-chat', 'cwd': 'D:/Other', '_nativeProject': {'id': 'native', 'name': 'Local'}},
                {'id': 'older-chat', 'cwd': 'D:/Work/Project', '_nativeProject': None}]
        self.hosts.decorate(rows, 'local', 'Local')
        self.assertEqual([row['projectKey'] for row in rows], ['local|local', 'local|local'])

    def setUp(self):
        self.hosts = AppHosts(Path('unused-fixture-home'))
        self.saved = {
            'local-projects': {'local': {'id': 'local', 'name': 'Local', 'rootPaths': ['D:/Work/Project']}},
            'remote-projects': [{'id': 'remote', 'hostId': 'ssh', 'label': 'Remote',
                                 'remotePath': 'C:/Work/Project'}],
        }
        self.hosts.state = lambda: self.saved

    def decorate(self, cwd, host='local', identifier='fixture'):
        row={'id': identifier, 'cwd': cwd, 'origin': 'desktop'}
        return self.hosts.decorate([row], host, host)[0]


    def test_unlabelled_remote_windows_project_uses_directory_name(self):
        self.saved['codex-managed-remote-connections'] = [{'hostId': 'ssh', 'alias': 'fixture'}]
        self.saved['remote-projects'][0].update(remotePath=r'C:\Work\Project')
        self.saved['remote-projects'][0].pop('label')
        self.assertEqual(self.hosts.projects()[1]['name'], 'Project')
        self.saved['thread-project-assignments'] = {'fixture': {'projectId': 'remote', 'hostId': 'ssh'}}
        self.assertEqual(self.decorate(r'C:\Work\Project', 'ssh')['projectName'], 'Project')
        self.saved['remote-projects'][0]['label'] = 'Custom project name'
        self.assertEqual(self.hosts.projects()[1]['name'], 'Custom project name')
        self.assertEqual(self.decorate(r'C:\Work\Project', 'ssh')['projectName'], 'Custom project name')


    def test_explicit_membership_wins_and_never_crosses_hosts(self):
        self.saved['local-projects']['assigned'] = {'id': 'assigned', 'name': 'Assigned', 'rootPaths': ['E:/Other']}
        self.saved['thread-project-assignments'] = {'fixture': {'projectId': 'assigned', 'hostId': 'local'}}
        self.assertEqual(self.decorate('D:/Work/Project')['projectKey'], 'local|assigned')
        self.assertEqual(self.decorate('C:/Work/Project', 'ssh')['projectKey'], 'ssh|unassigned')
        self.assertNotEqual(self.decorate('D:/Work/Project', 'other')['projectKey'], 'local|local')


if __name__ == '__main__':
    unittest.main()
