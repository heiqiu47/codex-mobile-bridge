"""Project display uses the execution host's path syntax without changing cwd."""
import builtins
import copy
import contextlib
import io
import json
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.clients.codex.remote import AppHosts, RemoteStore


class ProjectGroupingTests(unittest.TestCase):
    def setUp(self):
        self.hosts = AppHosts(Path('unused-fixture-home'))
        self.saved = {
            'local-projects': {'local': {'id': 'local', 'name': 'Local', 'rootPaths': ['D:/Work/Project']}},
            'remote-projects': [{'id': 'remote', 'hostId': 'ssh', 'label': 'Remote',
                                 'remotePath': 'C:/Work/Project'}],
        }
        self.hosts.state = lambda: self.saved

    def decorate(self, cwd, host='local', identifier='fixture', target_style=None):
        row={'id': identifier, 'cwd': cwd, 'origin': 'desktop'}
        if target_style is not None:
            row['_targetPathStyle']=target_style
        return self.hosts.decorate([row], host, host)[0]

    def test_local_and_ssh_windows_prefixes_separators_case_and_subdirectories(self):
        before = copy.deepcopy(self.saved)
        for host, drive, project in [('local', 'D', 'local'), ('ssh', 'C', 'remote')]:
            for cwd in [f'{drive}:\\WORK\\project', f'{drive.lower()}:/work/PROJECT/',
                        f'\\\\?\\{drive}:\\Work\\Project', f'//?/{drive}:/Work/Project/child',
                        f'\\\\.\\{drive}:\\Work\\Project\\child']:
                with self.subTest(host=host, cwd=cwd):
                    row = self.decorate(cwd, host)
                    self.assertEqual(row['projectKey'], host + '|' + project)
                    self.assertEqual(row['cwd'], cwd)
                    self.assertEqual(row['id'], 'fixture')
                    self.assertEqual(row['host'], host)
                    self.assertEqual(row['origin'], 'desktop')
        self.assertEqual(self.saved, before)

    def test_sibling_and_independent_directories_remain_separate(self):
        for cwd in ['D:/Work/Project2', 'D:/Other/independent']:
            self.assertNotEqual(self.decorate(cwd)['projectKey'], 'local|local')

    def test_unregistered_windows_directories_use_leaf_names_on_either_gateway_os(self):
        self.saved = {}
        for gateway_os in ('nt', 'posix'):
            for host in ('local', 'ssh'):
                for cwd in [r'C:\Users\fixture\Work\Project', r'\\?\C:\Users\fixture\Work\Project',
                            r'\\server\share\Project' + '\\', r'\\?\UNC\server\share\Project']:
                    for origin in ('cli', 'desktop'):
                        with self.subTest(gateway_os=gateway_os, host=host, cwd=cwd, origin=origin), \
                                patch('bridge.clients.codex.remote.os.name', gateway_os):
                            original = {'id': 'fixture', 'cwd': cwd, 'origin': origin,
                                        'model_provider': 'fixture-provider', '_targetPathStyle': 'windows'}
                            row = self.hosts.decorate([dict(original)], host, host)[0]
                            self.assertEqual(row['projectName'], 'Project')
                            self.assertEqual(row['cwd'], cwd)
                            self.assertEqual(row['origin'], origin)
                            self.assertEqual(row['model_provider'], 'fixture-provider')
                            self.assertTrue(row['projectKey'].startswith(host + '|'))
                            self.assertNotIn('_targetPathStyle', row)
        self.assertEqual(self.saved, {})

    def test_unlabelled_remote_windows_project_uses_directory_name(self):
        self.saved['codex-managed-remote-connections'] = [{'hostId': 'ssh', 'alias': 'fixture'}]
        self.saved['remote-projects'][0].update(remotePath=r'C:\Work\Project')
        self.saved['remote-projects'][0].pop('label')
        self.assertEqual(self.hosts.projects()[1]['name'], 'Project')
        self.assertEqual(self.decorate(r'C:\Work\Project', 'ssh')['projectName'], 'Project')
        self.saved['remote-projects'][0]['label'] = 'Custom project name'
        self.assertEqual(self.hosts.projects()[1]['name'], 'Custom project name')
        self.assertEqual(self.decorate(r'C:\Work\Project', 'ssh')['projectName'], 'Custom project name')

    def test_unregistered_posix_directory_names_keep_literal_backslashes_and_case(self):
        self.saved = {}
        for gateway_os in ('nt', 'posix'):
            for host in ('local', 'ssh'):
                with patch('bridge.clients.codex.remote.os.name', gateway_os):
                    row = self.decorate(r'/work/Project\notes', host, target_style='posix')
                    self.assertEqual(row['projectName'], r'Project\notes')
                    self.assertEqual(row['cwd'], r'/work/Project\notes')
                    self.assertEqual(row['projectKey'], host + r'|/work/Project\notes')

    def test_longest_root_and_all_saved_roots_are_considered(self):
        self.saved['local-projects']['local']['rootPaths'].append('E:/Second')
        self.saved['local-projects']['nested'] = {'id': 'nested', 'name': 'Nested',
                                                  'rootPaths': ['D:/Work/Project/child']}
        self.assertEqual(self.decorate('\\\\?\\D:\\Work\\Project\\child\\src')['projectKey'], 'local|nested')
        self.assertEqual(self.decorate('\\\\?\\E:\\SECOND\\src')['projectKey'], 'local|local')

    def test_explicit_membership_wins_and_never_crosses_hosts(self):
        self.saved['local-projects']['assigned'] = {'id': 'assigned', 'name': 'Assigned', 'rootPaths': ['E:/Other']}
        self.saved['thread-project-assignments'] = {'fixture': {'projectId': 'assigned', 'hostId': 'local'}}
        self.assertEqual(self.decorate('D:/Work/Project')['projectKey'], 'local|assigned')
        self.assertEqual(self.decorate('C:/Work/Project', 'ssh')['projectKey'], 'ssh|remote')
        self.assertNotEqual(self.decorate('D:/Work/Project', 'other')['projectKey'], 'local|local')

    def test_plain_forward_slash_unc_uses_target_platform_and_preserves_boundaries(self):
        self.saved['local-projects']['local']['rootPaths']=['//server/share/Project']
        self.saved['local-projects']['nested']={'id':'nested','name':'Nested','rootPaths':['//server/share/Project/child']}
        self.saved['remote-projects']=[{'id':'remote','hostId':'ssh','label':'Remote','remotePath':'//server/share/Project'},
                                       {'id':'nested','hostId':'ssh','label':'Nested','remotePath':'//server/share/Project/child'}]
        before=copy.deepcopy(self.saved)
        for host in ('local','ssh'):
            # A local Windows target and remote Windows target behave alike,
            # even when the gateway for SSH runs on a POSIX platform.
            with patch('bridge.clients.codex.remote.os.name','nt' if host=='local' else 'posix'):
                for cwd,project in [('//SERVER/share/project','local' if host=='local' else 'remote'),
                                    ('//SERVER/SHARE/PROJECT/CHILD/src','nested')]:
                    row=self.decorate(cwd,host,target_style='windows')
                    self.assertEqual(row['projectKey'],host+'|'+project)
                    self.assertEqual(row['cwd'],cwd)
                    self.assertNotIn('_targetPathStyle',row)
                self.assertNotIn(self.decorate('//server/share/Project2',host,target_style='windows')['projectKey'],
                                 [host+'|local',host+'|remote',host+'|nested'])
        self.assertEqual(self.saved,before)

    def test_double_slash_posix_and_unknown_remote_paths_keep_case(self):
        self.saved['local-projects']['local']['rootPaths']=['//server/share/Project']
        self.saved['remote-projects'][0]['remotePath']='//server/share/Project'
        for host,style,gateway_os in [('local',None,'posix'),('ssh','posix','nt'),('ssh',None,'nt')]:
            with patch('bridge.clients.codex.remote.os.name',gateway_os):
                expected=host+'|'+('local' if host=='local' else 'remote')
                self.assertEqual(self.decorate('//server/share/Project/src',host,target_style=style)['projectKey'],expected)
                self.assertNotEqual(self.decorate('//server/share/project/src',host,target_style=style)['projectKey'],expected)
                self.assertEqual(self.decorate('/work/Project',host,target_style=style)['cwd'],'/work/Project')

    def test_ssh_target_style_is_created_remotely_and_survives_list_cache(self):
        source='from pathlib import Path\nimport json\nclass SessionStore:\n def __init__(self,home): pass\n def list(self,**kwargs): return [{"id":"fixture","cwd":"//SERVER/share/project"}]\n'
        for target_os,style in [('nt','windows'),('posix','posix')]:
            def remote_import(name,*args,**kwargs):
                if name=='os':
                    return types.SimpleNamespace(name=target_os,environ={})
                return builtins.__import__(name,*args,**kwargs)
            def read(alias,script,**kwargs):
                namespace={'__builtins__':{**vars(builtins),'__import__':remote_import}}
                output=io.StringIO()
                with contextlib.redirect_stdout(output):
                    exec(script,namespace)
                return json.loads(output.getvalue())
            store=RemoteStore('fixture-ssh')
            with patch('bridge.clients.codex.remote.source_text',return_value=source), \
                    patch('bridge.clients.codex.remote.ssh_read',side_effect=read):
                rows=store.list()
            self.assertEqual(rows[0]['_targetPathStyle'],style)
            self.hosts.decorate(rows,'ssh','ssh')
            cached=store.list()
            self.assertEqual(cached[0]['_targetPathStyle'],style)

    def test_windows_host_hint_does_not_fold_single_slash_posix_paths(self):
        self.saved['local-projects']['local']['rootPaths']=['/work/Project']
        self.saved['remote-projects'][0]['remotePath']='/work/Project'
        for host,style in [('local',None),('ssh','windows'),('ssh','posix')]:
            with patch('bridge.clients.codex.remote.os.name','nt'):
                expected=host+'|'+('local' if host=='local' else 'remote')
                self.assertEqual(self.decorate('/work/Project/src',host,target_style=style)['projectKey'],expected)
                self.assertNotEqual(self.decorate('/work/project/src',host,target_style=style)['projectKey'],expected)
                self.assertEqual(self.decorate('/other/Case',host,target_style=style)['projectKey'],host+'|/other/Case')

    def test_unc_namespaces_match_without_touching_posix_case(self):
        for host in ['local', 'ssh']:
            expected = 'local|local' if host == 'local' else 'ssh|remote'
            if host == 'local':
                self.saved['local-projects']['local']['rootPaths'] = ['//server/share/Project']
            else:
                self.saved['remote-projects'][0]['remotePath'] = '//server/share/Project'
            for cwd in ['\\\\SERVER\\share\\project\\child', '\\\\?\\UNC\\SERVER\\share\\project']:
                with self.subTest(host=host, cwd=cwd):
                    self.assertEqual(self.decorate(cwd, host)['projectKey'], expected)
        self.saved['local-projects']['local']['rootPaths'] = ['/work/Project']
        self.saved['remote-projects'][0]['remotePath'] = '/work/Project'
        for host in ['local', 'ssh']:
            expected = 'local|local' if host == 'local' else 'ssh|remote'
            self.assertEqual(self.decorate('/work/Project/src', host)['projectKey'], expected)
            self.assertNotIn(self.decorate('/work/project/src', host)['projectKey'], ['local|local', 'ssh|remote'])


if __name__ == '__main__':
    unittest.main()
