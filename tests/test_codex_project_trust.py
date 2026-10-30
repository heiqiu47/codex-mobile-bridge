"""Explicit native project consent, exact host identity and scoped App import."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.app.lifecycle import private_json
from bridge.app.service import Bridge
from bridge.clients.codex.remote import AppHosts
from bridge.features.sessions.create import project_trust, project_directory, CreationError, CreationUnavailable

ROOT = Path(__file__).resolve().parents[1]


class ProjectTrust(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=ROOT/'.tmp'); self.addCleanup(tmp.cleanup)
        name = "a.b ' project" if os.name == 'nt' else 'a.b " project'
        self.root = Path(tmp.name).resolve(); self.cwd = self.root/name; self.cwd.mkdir()
        self.identity = project_directory(str(self.cwd)); self.trusted = False; self.calls = []
        self.layers = [{'name': {'type': 'user', 'file': str(self.root/'config.toml')}, 'version': 'v1'}]

    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == 'config/read':
            return {'config': {'projects': {str(self.cwd): {'trust_level': 'trusted' if self.trusted else 'untrusted'}}}, 'layers': self.layers}
        if method == 'config/batchWrite':
            self.trusted = True
            return {'status': 'ok'}
        self.fail('Unexpected write: '+method)

    def run_trust(self, confirmed=False):
        def runtime(executable, home, cwd, operation, **kwargs):
            self.assertEqual(cwd, str(self.root)); return operation(self.rpc)
        with patch('bridge.features.sessions.create._runtime_operation', side_effect=runtime):
            return project_trust('fixture', self.root, self.identity, confirmed)

    def test_read_and_confirm_only_write_exact_quoted_project_key(self):
        self.assertFalse(self.run_trust()['trusted']); self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.run_trust(True)['trusted'])
        writes = [p for m,p in self.calls if m == 'config/batchWrite']
        self.assertEqual(writes, [{'edits': [{'keyPath': 'projects.'+json.dumps(str(self.cwd), ensure_ascii=False)+'.trust_level',
            'value': 'trusted', 'mergeStrategy': 'replace'}], 'filePath': None,
            'expectedVersion': 'v1', 'reloadUserConfig': True}])
        self.run_trust(True)
        self.assertEqual(sum(m == 'config/batchWrite' for m,p in self.calls), 1)

    def test_missing_base_version_and_replaced_directory_do_not_write(self):
        self.layers = []
        with self.assertRaises(CreationUnavailable): self.run_trust(True)
        self.assertFalse(self.trusted)
        self.cwd.rename(self.root/'old'); self.cwd.mkdir()
        with self.assertRaisesRegex(ValueError, '已变化'): self.run_trust(True)
        self.assertFalse(self.trusted)

    def test_unknown_write_is_not_retried(self):
        original = self.rpc
        def rpc(method, params):
            if method == 'config/batchWrite':
                self.calls.append((method, params)); raise CreationError('unknown')
            return original(method, params)
        self.rpc = rpc
        with self.assertRaisesRegex(CreationError, 'unknown'): self.run_trust(True)
        self.assertEqual(sum(m == 'config/batchWrite' for m,p in self.calls), 1)

    def test_confirmation_bound_to_registered_identity_and_host(self):
        bridge = Bridge(self.root, self.root/'data'); self.addCleanup(bridge.close)
        bridge.hosts.hosts = lambda: {'ssh': {'alias': 'chosen', 'displayName': 'Chosen'}}
        project = bridge.directory_projects.save('ssh', 'Chosen', self.identity, type='desktop', hostIdentity='chosen')
        with patch.object(bridge, 'projects', side_effect=AssertionError('Trust must not enumerate hosts')), \
             patch('bridge.app.service.ssh_read', return_value={'trusted': False, 'path': str(self.cwd)}) as rpc:
            state = bridge.project_trust(project['key'])
            self.assertTrue(state['required']); self.assertEqual(rpc.call_args.args[0], 'chosen')
            bridge.project_trust(project['key'], True, state['confirmation'])
            with self.assertRaisesRegex(ValueError, '已变化'): bridge.project_trust(project['key'], True, 'stale')
            bridge.hosts.hosts = lambda: {'ssh': {'alias': 'different'}}
            with self.assertRaisesRegex(ValueError, '主机配置已变化'): bridge.project_trust(project['key'])

    def test_project_host_uses_exact_metadata_not_ambiguous_prefix(self):
        bridge = Bridge(self.root, self.root/'data'); self.addCleanup(bridge.close)
        hosts = {'local|backup': {'alias': 'backup'}, 'ssh:a': {'alias': 'a'}, 'ssh:a|b': {'alias': 'b'}}
        bridge.hosts.hosts = lambda: hosts
        bridge.hosts.projects = lambda: [{'key': 'ssh:a|b|native', 'host': 'ssh:a|b'}]
        for host in hosts:
            project = bridge.directory_projects.save(host, host, self.identity, type='desktop')
            self.assertEqual(bridge.project_host(project['key']), host)
            self.assertEqual(bridge.project_host('cli|' + host + '|' + 'a' * 20), host)
        self.assertEqual(bridge.project_host('ssh:a|b|native'), 'ssh:a|b')
        for key in ('ssh:a|missing', 'cli|unknown|' + 'a' * 20, 'cli|ssh:a|bad-hash'):
            with self.assertRaises(ValueError): bridge.project_host(key)


class NativeImport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=ROOT/'.tmp'); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.hosts = AppHosts(self.root)
        self.state = {'codex-managed-remote-connections': [{'hostId': 'ssh', 'alias': 'selected'}],
                      'remote-connection-max-retry-attempts': 7, 'remote-projects': []}
        (self.root/'.codex-global-state.json').write_text(json.dumps(self.state))
        self.project = {'host': 'ssh', 'hostIdentity': 'selected', 'cwd': '/home/test/project', 'name': 'Test'}

    def test_import_preserves_live_global_state_and_retry_settings(self):
        state = (self.root/'.codex-global-state.json').read_bytes()
        prepared = self.hosts.project_import(self.project)
        self.hosts.write_project_import(prepared, private_json)
        config = json.loads((self.root/'codex-app/config.json').read_text())
        self.assertEqual(config, {'version': 1, 'remoteConnectionMaxRetryAttempts': 7,
            'remoteConnections': [{'sshAlias': 'selected', 'projects': [{'remotePath': '/home/test/project', 'label': 'Test'}]}]})
        self.assertEqual((self.root/'.codex-global-state.json').read_bytes(), state)

    def test_other_hosts_pending_projects_and_concurrent_config_changes_are_not_applied(self):
        path = self.root/'codex-app/config.json'; path.parent.mkdir()
        for rows in [[{'sshAlias': 'other'}], [{'sshAlias': 'selected', 'projects': [{'remotePath': '/pending'}]}]]:
            path.write_text(json.dumps({'remoteConnections': rows}))
            with self.assertRaisesRegex(ValueError, '其他待应用'): self.hosts.project_import(self.project)
        path.unlink(); prepared = self.hosts.project_import(self.project)
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, '配置已变化'): self.hosts.write_project_import(prepared, private_json)
        self.assertEqual(path.read_text(), '{}')
