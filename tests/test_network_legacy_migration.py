"""Legacy selections are pinned once on explicit startup, not status reads."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import run
from bridge.app.desktop import Desktop
from bridge.features.network.adaptation import migrate_legacy_interfaces

ROOT = Path(__file__).resolve().parents[1]


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config_path = self.directory/'config.json'
        self.profile_path = self.directory/'desktop.json'
        self.rows = [{'id': 'wifi', 'name': 'Wi-Fi', 'addresses': ['192.168.1.7']},
                     {'id': 'ethernet', 'name': 'Ethernet', 'addresses': ['10.0.0.7']}]
        self.legacy = ['192.168.1.7', '10.0.0.7']
        self.config = {'auth': {'mode': 'password', 'hash': 'unchanged'},
                       'origins': ['https://fixed.example'], 'lanAddresses': self.legacy}
        self.profile = {'lan': True, 'port': 8787, 'lanAddresses': self.legacy,
                        'codexHome': str(self.directory), 'connections': []}
        self.config_path.write_text(json.dumps(self.config))
        self.profile_path.write_text(json.dumps(self.profile))
        (self.directory/'trusted-devices.json').write_text('{"binding":"untouched"}')

    def read(self, path):
        return json.loads(path.read_text())

    def test_two_adapters_survive_dhcp_and_restart_without_losing_old_fields(self):
        result = migrate_legacy_interfaces(self.config_path, self.rows)
        self.assertEqual(result, {**self.config, 'lanInterfaces': ['wifi', 'ethernet']})
        self.assertEqual(self.read(self.profile_path), {**self.profile, 'lanInterfaces': ['wifi', 'ethernet']})
        self.rows[0]['addresses'] = ['192.168.1.8']
        self.rows[1]['addresses'] = ['10.0.0.8']
        again = migrate_legacy_interfaces(self.config_path, self.rows)
        self.assertEqual(again, result)
        desktop = Desktop(self.directory)
        with patch('bridge.app.desktop.interfaces.enumerate_interfaces', side_effect=AssertionError('not needed')):
            self.assertEqual(desktop.preferences()['lanInterfaces'], ['wifi', 'ethernet'])
        self.assertEqual((self.directory/'trusted-devices.json').read_text(), '{"binding":"untouched"}')

    def test_read_only_preferences_do_not_migrate_on_disk(self):
        desktop = Desktop(self.directory)
        before = [path.read_bytes() for path in (self.config_path, self.profile_path)]
        with patch('bridge.app.desktop.interfaces.enumerate_interfaces', return_value=self.rows):
            self.assertEqual(desktop.preferences()['lanInterfaces'], ['wifi', 'ethernet'])
        self.assertEqual([path.read_bytes() for path in (self.config_path, self.profile_path)], before)

    def test_missing_or_ambiguous_owner_is_not_persisted_or_opened(self):
        for rows in ([], [self.rows[0], {**self.rows[0], 'id': 'duplicate'}, self.rows[1]]):
            with self.subTest(rows=rows):
                self.assertEqual(migrate_legacy_interfaces(self.config_path, rows), self.config)
                self.assertEqual(self.read(self.profile_path), self.profile)

    def test_explicit_existing_identity_is_never_overwritten(self):
        self.config['lanInterfaces'] = ['existing']
        self.profile['lanInterfaces'] = ['another-existing']
        self.config_path.write_text(json.dumps(self.config))
        self.profile_path.write_text(json.dumps(self.profile))
        migrate_legacy_interfaces(self.config_path, self.rows)
        self.assertEqual(self.read(self.config_path), self.config)
        self.assertEqual(self.read(self.profile_path), self.profile)

    def test_interrupted_migration_can_resume_after_ip_has_changed(self):
        self.config['lanInterfaces'] = ['wifi', 'ethernet']
        self.config_path.write_text(json.dumps(self.config))
        self.rows[0]['addresses'] = ['192.168.1.8']
        self.rows[1]['addresses'] = ['10.0.0.8']
        migrate_legacy_interfaces(self.config_path, self.rows)
        self.assertEqual(self.read(self.profile_path)['lanInterfaces'], ['wifi', 'ethernet'])

    def test_peer_with_different_legacy_scope_is_not_borrowed(self):
        self.config['lanInterfaces'] = ['wifi']
        self.config['lanAddresses'] = ['192.168.1.7']
        self.config_path.write_text(json.dumps(self.config))
        migrate_legacy_interfaces(self.config_path, [])
        self.assertNotIn('lanInterfaces', self.read(self.profile_path))

    def test_cli_only_config_does_not_create_desktop_profile(self):
        self.profile_path.unlink()
        migrate_legacy_interfaces(self.config_path, self.rows)
        self.assertFalse(self.profile_path.exists())
        self.assertEqual(self.read(self.config_path)['lanInterfaces'], ['wifi', 'ethernet'])

    def test_automatic_scope_remains_automatic_without_network_query(self):
        self.config['lanAddresses'] = None
        self.profile['lanAddresses'] = None
        self.config_path.write_text(json.dumps(self.config))
        self.profile_path.write_text(json.dumps(self.profile))
        with patch('bridge.features.network.interfaces.enumerate_interfaces', side_effect=AssertionError('not needed')):
            migrate_legacy_interfaces(self.config_path)
        self.assertEqual(self.read(self.config_path), self.config)
        self.assertEqual(self.read(self.profile_path), self.profile)

    def test_desktop_start_persists_selection_before_spawning_child(self):
        desktop = Desktop(self.directory)
        desktop.status = lambda: {'running': False, 'portOccupied': False}
        with patch('bridge.features.network.interfaces.enumerate_interfaces', return_value=self.rows), \
                patch('bridge.app.desktop.socket.socket'), \
                patch('bridge.app.desktop.subprocess.Popen', return_value=MagicMock(pid=123)) as spawn:
            result = desktop.start()
        self.assertTrue(result['started'])
        spawn.assert_called_once()
        self.assertEqual(self.read(self.config_path)['lanInterfaces'], ['wifi', 'ethernet'])
        self.assertEqual(self.read(self.profile_path)['lanInterfaces'], ['wifi', 'ethernet'])

    def test_direct_cli_persists_before_start_without_saving_no_auth_override(self):
        with patch('bridge.features.network.interfaces.enumerate_interfaces', return_value=self.rows), \
                patch('sys.argv', ['run.py', '--config', str(self.config_path), '--lan', '--no-auth']), \
                patch.object(run, 'Bridge', side_effect=RuntimeError('fixture-stop')):
            with self.assertRaisesRegex(RuntimeError, 'fixture-stop'):
                run.main()
        self.assertEqual(self.read(self.config_path)['lanInterfaces'], ['wifi', 'ethernet'])
        self.assertEqual(self.read(self.config_path)['auth']['mode'], 'password')

    def test_empty_legacy_scope_never_inherits_automatic_peer_scope(self):
        self.config.update(lanAddresses=[], lanInterfaces=None)
        self.profile['lanAddresses'] = []
        self.config_path.write_text(json.dumps(self.config))
        self.profile_path.write_text(json.dumps(self.profile))
        migrate_legacy_interfaces(self.config_path, self.rows)
        self.assertEqual(self.read(self.profile_path)['lanInterfaces'], [])
