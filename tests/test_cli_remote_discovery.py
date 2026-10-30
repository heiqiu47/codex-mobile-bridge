import unittest
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from bridge.clients.codex.remote import AppHosts, RemoteStore, RemoteUnavailable, ssh_command


class RemoteDiscoveryTests(unittest.TestCase):
    def test_passive_hosts_cache_invalidates_and_keeps_live_reads_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / '.codex-global-state.json'
            def save(alias):
                path.write_text(json.dumps({'codex-managed-remote-connections': [
                    {'hostId': 'remote:one', 'alias': alias, 'nested': {'name': 'original'}}]}), encoding='utf-8')
            save('first')
            hosts = AppHosts(home)
            with patch.object(hosts, 'state', wraps=hosts.state) as read:
                for _ in range(5):
                    value = hosts.hosts(cached=True)
                    self.assertEqual(value['remote:one']['alias'], 'first')
                    value['remote:one']['nested']['name'] = 'mutated'
                self.assertEqual(read.call_count, 1)
                self.assertEqual(hosts.hosts(cached=True)['remote:one']['nested']['name'], 'original')
                save('second-alias')
                self.assertEqual(hosts.hosts(cached=True)['remote:one']['alias'], 'second-alias')
                self.assertEqual(read.call_count, 2)
                hosts.hosts()
                hosts.hosts()
                self.assertEqual(read.call_count, 4)
                path.unlink()
                self.assertEqual(hosts.hosts(cached=True), {})
                save('replacement')
                self.assertEqual(hosts.hosts(cached=True)['remote:one']['alias'], 'replacement')

    def test_passive_hosts_cache_discards_a_file_replaced_while_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / '.codex-global-state.json'
            def state(alias):
                return json.dumps({'codex-managed-remote-connections': [
                    {'hostId': 'remote:one', 'alias': alias}]})
            path.write_text(state('old'), encoding='utf-8')
            replacement = home / 'replacement.json'
            replacement.write_text(state('replacement'), encoding='utf-8')
            hosts = AppHosts(home)
            read = hosts.state
            def replace_after_read():
                value = read()
                replacement.replace(path)
                return value
            with patch.object(hosts, 'state', side_effect=replace_after_read):
                self.assertEqual(hosts.hosts(cached=True), {})
            self.assertEqual(hosts.hosts(cached=True)['remote:one']['alias'], 'replacement')

    def test_passive_host_resolution_reuses_parse_but_regular_resolution_reads_fresh(self):
        from bridge.app.service import Bridge
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / '.codex-global-state.json').write_text(json.dumps({
                'codex-managed-remote-connections': [{'hostId': 'remote:one', 'alias': 'server'}]}), encoding='utf-8')
            bridge = Bridge.__new__(Bridge)
            bridge.host = 'local'
            bridge.entries = None
            bridge.lock = threading.Lock()
            bridge.hosts = AppHosts(home)
            source = bridge.remote_bridges = {'remote:one': object()}
            with patch.object(bridge.hosts, 'state', wraps=bridge.hosts.state) as read:
                for _ in range(5):
                    self.assertIs(bridge.for_host('remote:one', cached=True), source['remote:one'])
                self.assertEqual(read.call_count, 1)
                for _ in range(3):
                    bridge.for_host('remote:one')
                self.assertEqual(read.call_count, 4)

    def test_managed_aliases_do_not_require_project_references(self):
        hosts = AppHosts(Path('/unused'))
        hosts.state = lambda: {'remote-projects': [{'hostId': 'remote:project'}],
                               'thread-project-membership-host-ids': {'thread': 'remote:member'},
                               'codex-managed-remote-connections': [
            {'hostId': 'remote:one', 'alias': 'saved-host', 'displayName': 'Saved'},
            {'hostId': 'remote:project', 'alias': 'project-host'},
            {'hostId': 'remote:member', 'alias': 'member-host'},
            {'hostId': 'remote:bad', 'alias': '-bad'},
            {'hostId': 'remote:spaces', 'alias': 'host ; command'},
        ]}
        self.assertEqual(set(hosts.hosts()), {'remote:one', 'remote:project', 'remote:member'})
        self.assertEqual(set(hosts.lifecycle_hosts()), {'remote:project', 'remote:member'})

    def test_ssh_login_shell_keeps_strict_options_and_alias_as_argument(self):
        command = ssh_command('saved-host')
        self.assertEqual(command[-2], 'saved-host')
        self.assertIn('"$SHELL" -lc', command[-1])
        self.assertIn('python3 -', command[-1])
        self.assertIn('StrictHostKeyChecking=yes', command)
        self.assertIn('BatchMode=yes', command)
        for alias in ('-bad', 'bad host', 'bad\ncommand', ''):
            with self.assertRaises(RemoteUnavailable):
                ssh_command(alias)

    def test_remote_diagnostics_carries_home_provenance_without_paths(self):
        store = RemoteStore('saved-host')
        with patch('bridge.clients.codex.remote.ssh_read', return_value={'status': 'ok'}) as read:
            result = store.discovery_diagnostics('thread-id')
        self.assertEqual(result, {'status': 'ok'})
        source = read.call_args.args[1]
        self.assertIn('discovery_diagnostics', source)
        self.assertIn('result["homeSource"] = home_source', source)
        self.assertNotIn('saved-host', source)


if __name__ == '__main__':
    unittest.main()
