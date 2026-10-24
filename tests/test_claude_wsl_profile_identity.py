"""WSL profile identity ignores display theme without crossing account scopes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from bridge.clients.claude import cli_session, remote_worker
from bridge.clients.claude.wsl import WslClaudeCli

ROOT = Path(__file__).resolve().parents[1]


class WslProfileIdentity(unittest.TestCase):
    def setUp(self):
        (ROOT/'.tmp').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory/'settings.json'
        self.settings = {'env': {'ANTHROPIC_AUTH_TOKEN': 'fixture-token',
                                 'ANTHROPIC_BASE_URL': 'https://fixture.invalid'},
                         'model': 'fixture-model', 'permissions': {'defaultMode': 'default'}}
        self.environment = {'CLAUDE_CONFIG_DIR': str(self.directory), 'MOBILE_BRIDGE_WSL_NATIVE': '1'}
        self.status = {'loggedIn': True, 'authMethod': 'oauth_token', 'apiProvider': 'firstParty'}
        self.native = str(uuid.uuid4())
        self.cli = WslClaudeCli()
        self.addCleanup(self.cli.close)

    def origin(self, settings=None, *, wsl=True, status=None, raw=None):
        if raw is not None:
            self.path.write_bytes(raw)
        else:
            self.path.write_text(json.dumps(self.settings if settings is None else settings), encoding='utf-8')
        env = dict(self.environment)
        if not wsl:
            env.pop('MOBILE_BRIDGE_WSL_NATIVE')
        with patch.dict(os.environ, env, clear=True), \
             patch.object(remote_worker.shutil, 'which', return_value='/fixture/claude'), \
             patch.object(remote_worker, 'native_wsl_binary', return_value=True), \
             patch.object(remote_worker, 'auth_status', return_value=self.status if status is None else status):
            return remote_worker.profile()['origin']

    def gateway_id(self, origin):
        return self.cli._row('wsl-claude:fixture', {'alias': 'wsl-claude:fixture',
            'distribution': 'Ubuntu', 'user': 'fixture'}, {'origin': origin, 'nativeId': self.native})['id']

    def test_theme_add_change_remove_preserves_profile_and_gateway_session(self):
        baseline = self.origin()
        for settings in ({**self.settings, 'theme': 'dark'}, {**self.settings, 'theme': 'light'}, self.settings):
            with self.subTest(theme=settings.get('theme')):
                origin = self.origin(settings)
                self.assertEqual(origin, baseline)
                self.assertEqual(self.gateway_id(origin), self.gateway_id(baseline))

    def test_json_key_order_and_whitespace_do_not_change_wsl_identity(self):
        baseline = self.origin()
        reordered = dict(reversed(list(self.settings.items())))
        reordered['env'] = dict(reversed(list(reordered['env'].items())))
        alternate = (json.dumps(reordered, indent=4)+'\n').encode()
        self.assertEqual(self.origin(raw=alternate), baseline)

    def test_credentials_routing_and_non_theme_settings_remain_isolated(self):
        baseline = self.origin()
        alternatives = [
            {**self.settings, 'env': {**self.settings['env'], 'ANTHROPIC_AUTH_TOKEN': 'other-token'}},
            {**self.settings, 'env': {**self.settings['env'], 'ANTHROPIC_BASE_URL': 'https://other.invalid'}},
            {**self.settings, 'env': {**self.settings['env'], 'ANTHROPIC_CUSTOM_HEADERS': 'X-Test: other'}},
            {**self.settings, 'model': 'other-model'},
            {**self.settings, 'permissions': {'defaultMode': 'plan'}},
        ]
        for settings in alternatives:
            with self.subTest(settings=settings):
                origin = self.origin(settings)
                self.assertNotEqual(origin, baseline)
                self.assertNotEqual(self.gateway_id(origin), self.gateway_id(baseline))

    def test_real_account_changes_remain_isolated_and_known_account_rotation_is_stable(self):
        first = {**self.status, 'accountId': 'first-account'}
        second = {**self.status, 'accountId': 'second-account'}
        self.assertNotEqual(self.origin(status=first), self.origin(status=second))
        credentials = self.directory/'.credentials.json'
        credentials.write_text('{"accessToken":"first"}')
        baseline = self.origin(status=first)
        credentials.write_text('{"accessToken":"refreshed"}')
        self.assertEqual(self.origin(status=first), baseline)
        # Without a stable account ID, retain conservative credential isolation.
        unknown = self.origin()
        credentials.write_text('{"accessToken":"different"}')
        self.assertNotEqual(self.origin(), unknown)

    def test_invalid_json_and_non_object_settings_keep_raw_fingerprint(self):
        for raw in (b'{broken', b'\xff', b'["theme","dark"]'):
            with self.subTest(raw=raw):
                self.assertIn(':'+hashlib.sha256(raw).hexdigest()+':', self.origin(raw=raw))
        self.assertNotEqual(self.origin(raw=b'{broken'), self.origin(raw=b'{different'))

    def test_ssh_keeps_raw_digest_and_theme_change_behavior(self):
        raw = (json.dumps(self.settings, indent=2)+'\n').encode()
        origin = self.origin(wsl=False, raw=raw)
        self.assertIn(':'+hashlib.sha256(raw).hexdigest()+':', origin)
        self.assertNotEqual(origin, self.origin({**self.settings, 'theme': 'dark'}, wsl=False))
        self.assertNotEqual(origin, self.origin(wsl=False))

    def test_local_cli_profile_keeps_raw_settings_identity(self):
        raw = (json.dumps({**self.settings, 'theme': 'dark'}, indent=2)+'\n').encode()
        self.path.write_bytes(raw)
        with patch.dict(os.environ, self.environment, clear=True), \
             patch.object(cli_session.shutil, 'which', return_value='/fixture/claude'):
            origin = cli_session._profile()['origin']
        self.assertEqual(origin, 'environment:'+str(self.directory)+':'+hashlib.sha256(raw).hexdigest())


if __name__ == '__main__':
    unittest.main()
