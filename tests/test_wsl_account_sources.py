import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bridge.features.accounts.wsl_account_sources import WslAccountSources


class WslAccountSourceTests(unittest.TestCase):
    def setUp(self):
        self.identifier = 'a'*32
        self.row = {'id': self.identifier, 'kind': 'api', 'name': 'Desktop API',
                    'baseUrl': 'https://fixture.invalid/v1', 'model': 'fixture-model'}
        self.accounts = SimpleNamespace(lock=threading.RLock(), index={'accounts': [self.row]},
                                       row=Mock(side_effect=lambda _: self.row),
                                       api_credentials=Mock(return_value=('https://fixture.invalid/v1', 'private-key')))
        self.bridge = SimpleNamespace(accounts=self.accounts)
        self.sources = WslAccountSources(self.bridge)

    def test_explicit_codex_source_identity_cas_and_no_public_secret(self):
        source = self.sources.sources('codex')[0]
        self.assertNotIn('private-key', str(source))
        self.assertEqual(source['source'], 'desktop-codex')
        value = self.sources.import_api('codex', {'sourceId': source['id'], 'sourceIdentity': source['sourceIdentity']})
        self.assertEqual(value['apiKey'], 'private-key')
        self.accounts.api_credentials.return_value = ('https://fixture.invalid/v1', 'changed-key')
        with self.assertRaises(ValueError):
            self.sources.import_api('codex', {'sourceId': source['id'], 'sourceIdentity': source['sourceIdentity']})

    def test_cross_provider_and_official_codex_login_rejected(self):
        source = self.sources.sources('codex')[0]
        with self.assertRaises(ValueError):
            self.sources.import_api('claude', {'sourceId': source['id'], 'sourceIdentity': source['sourceIdentity']})
        self.row['kind'] = 'chatgpt'
        self.assertEqual(self.sources.sources('codex'), [])
        with self.assertRaises(ValueError):
            self.sources.import_api('codex', {'sourceId': source['id'], 'sourceIdentity': source['sourceIdentity']})

    def test_claude_only_verified_saved_current_api_can_be_listed_and_imported(self):
        store = SimpleNamespace(lock=threading.RLock(), public=Mock(return_value={
            'activeId': self.identifier, 'current': {'id': self.identifier, 'kind': 'api', 'saved': True}}))
        self.bridge.desktop_sessions = SimpleNamespace(_account_store=Mock(return_value=store))
        api = {'name': 'Claude API', 'baseUrl': 'https://fixture.invalid', 'apiKey': 'claude-private',
               'model': 'claude-fixture', 'authScheme': 'x-api-key'}
        with patch('bridge.features.accounts.wsl_account_sources.LocalCliSync.import_desktop_claude', return_value=api.copy()) as convert:
            source = self.sources.sources('claude')[0]
            self.assertNotIn('claude-private', str(source))
            value = self.sources.import_api('claude', {'sourceId': source['id'], 'sourceIdentity': source['sourceIdentity']})
            self.assertEqual(value['apiKey'], 'claude-private')
            convert.assert_called_with(self.identifier, store=store)
            store.public.return_value['current']['kind'] = 'official'
            self.assertEqual(self.sources.sources('claude'), [])

    def test_claude_official_conversion_failure_has_no_fallback(self):
        store = SimpleNamespace(lock=threading.RLock(), public=Mock(return_value={
            'activeId': self.identifier, 'current': {'kind': 'api', 'saved': True}}))
        self.bridge.desktop_sessions = SimpleNamespace(_account_store=Mock(return_value=store))
        with patch('bridge.features.accounts.wsl_account_sources.LocalCliSync.import_desktop_claude', side_effect=ValueError('unsupported')):
            self.assertEqual(self.sources.sources('claude'), [])
            with self.assertRaises(ValueError):
                self.sources.import_api('claude', {'sourceId': 'desktop-claude:'+self.identifier, 'sourceIdentity': 'b'*64})


if __name__ == '__main__':
    unittest.main()
