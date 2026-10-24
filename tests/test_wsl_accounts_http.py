import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import test_bridge
from bridge.app.service import Bridge


class WslAccountsHttpTests(unittest.TestCase):
    setUpClass = classmethod(test_bridge.HttpTests.setUpClass.__func__)
    setUp = test_bridge.HttpTests.setUp
    tearDown = test_bridge.HttpTests.tearDown
    request = test_bridge.HttpTests.request
    login = test_bridge.HttpTests.login

    def manager(self):
        manager = SimpleNamespace(
            read=Mock(return_value={'accounts': [], 'capabilities': {'switch': True}}),
            environments=Mock(return_value={'environments': []}),
            change=Mock(return_value={'accounts': []}))
        self.server.bridge.wsl_accounts = manager
        self.server.bridge.accounts = SimpleNamespace(public=Mock())
        self.server.bridge.cli_access = SimpleNamespace(change=Mock())
        return manager

    def test_reads_are_authenticated_and_explicitly_targeted(self):
        manager = self.manager()
        url = '/api/wsl-accounts?provider=codex&entry=wsl:' + 'a' * 32
        self.assertEqual(self.request('GET', url)[0], 401)
        headers = self.login()
        self.assertEqual(self.request('GET', url, headers=headers)[0], 200)
        manager.read.assert_called_once_with('codex', 'wsl:' + 'a' * 32)
        self.assertEqual(self.request('GET', '/api/wsl-accounts/environments?provider=claude', headers=headers)[0], 200)
        manager.environments.assert_called_once_with('claude')
        for query in ('', '?provider=codex', '?provider=codex&entry=',
                      '?provider=codex&entry=wsl:a&entry=wsl:b',
                      '?provider=codex&entry=wsl:a&host=local'):
            self.assertEqual(self.request('GET', '/api/wsl-accounts' + query, headers=headers)[0], 400)
        self.server.bridge.accounts.public.assert_not_called()

    def test_web_cannot_use_desktop_credential_operations(self):
        manager = self.manager()
        headers = self.login()
        base = {'provider': 'codex', 'entry': 'wsl:' + 'a' * 32}
        for action in ('save-api', 'import-api', 'import-sources', 'import-current', 'delete', 'rename', 'wslAccounts'):
            self.assertEqual(self.request('POST', '/api/wsl-accounts', {**base, 'action': action}, headers)[0], 400)
        model = {**base, 'action': 'models', 'id': 'native'}
        for extra in ({'apiKey': 'not-sent'}, {'baseUrl': 'https://fixture.invalid'}, {'desktop': True}, {'refresh': 'true'}):
            self.assertEqual(self.request('POST', '/api/wsl-accounts', {**model, **extra}, headers)[0], 400)
        manager.change.assert_not_called()
        self.assertEqual(self.request('POST', '/api/wsl-accounts', model, headers)[0], 200)
        manager.change.assert_called_once_with(model, desktop=False)
        self.server.bridge.cli_access.change.assert_not_called()

    def test_switch_requires_auth_csrf_and_password_protection(self):
        manager = self.manager()
        value = {'provider': 'claude', 'entry': 'wsl-claude:' + 'b' * 32,
                 'action': 'switch', 'id': 'native', 'expectedIdentity': 'current'}
        self.assertEqual(self.request('POST', '/api/wsl-accounts', value)[0], 401)
        headers = self.login()
        self.assertEqual(self.request('POST', '/api/wsl-accounts', value, {'Cookie': headers['Cookie']})[0], 403)
        self.server.auth.config['mode'] = 'none'
        self.assertEqual(self.request('POST', '/api/wsl-accounts', value, headers)[0], 403)
        manager.change.assert_not_called()
        status, _, result = self.request('GET', '/api/wsl-accounts?provider=claude&entry=' + value['entry'], headers=headers)
        self.assertEqual(status, 200)
        self.assertFalse(result['capabilities']['switch'])
        self.server.auth.config['mode'] = 'password'
        self.assertEqual(self.request('POST', '/api/wsl-accounts', value, headers)[0], 200)
        manager.change.assert_called_once_with(value, desktop=False)


class WslDesktopControlTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge.__new__(Bridge)
        self.bridge.cli_access = SimpleNamespace(control=Mock(return_value={'local': True}))
        self.bridge.wsl_accounts = SimpleNamespace(change=Mock(), environments=Mock())

    def test_existing_cli_control_keeps_original_request_and_response(self):
        value = {'action': 'list'}
        self.assertEqual(self.bridge.cli_access_control(value), {'local': True})
        self.bridge.cli_access.control.assert_called_once_with(value)
        self.bridge.wsl_accounts.change.assert_not_called()

    def test_explicit_desktop_envelope_cannot_fall_back_to_local_accounts(self):
        entry = 'wsl:' + 'a' * 32
        self.bridge.cli_access_control({'action': 'wslAccounts', 'operation': 'list', 'provider': 'codex', 'entry': entry})
        self.bridge.wsl_accounts.change.assert_called_once_with({'action': 'read', 'provider': 'codex', 'entry': entry}, desktop=True)
        self.bridge.cli_access_control({'action': 'wslAccounts', 'operation': 'environments', 'provider': 'claude'})
        self.bridge.wsl_accounts.environments.assert_called_once_with('claude')
        with self.assertRaises(ValueError):
            self.bridge.cli_access_control({'action': 'wslAccounts', 'operation': 'environments', 'provider': 'codex', 'entry': entry})
        self.bridge.cli_access.control.assert_not_called()
