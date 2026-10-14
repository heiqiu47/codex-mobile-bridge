import json
import time
import unittest
import uuid
import copy
from unittest.mock import patch

import test_account
import test_account_info
from bridge.features.accounts.account import Account
from bridge.features.accounts.info import CURRENT_LOGIN_ID
from bridge.features.accounts.accounts import private_json


class CurrentLoginTests(unittest.TestCase):
    setUp = test_account_info.InfoTests.setUp
    tearDown = test_account_info.InfoTests.tearDown

    def login(self):
        rpc = test_account.FakeRPC()
        rpc.config = {'model_provider': 'custom'}
        rpc.auth['workspaceRouting'] = {'backendOrigin': 'https://chatgpt.com', 'chatgptAccountId': 'fixture'}
        rpc.auth['account']['email'] = 'fixture@example.test'
        context = Account.login_context(rpc)
        info = self.manager.info
        info.identity = {'kind': 'api', 'name': 'API · custom', 'login': {'context': context, 'owner': None}}
        info.stamp = info.source_stamp()
        info.checked_at = time.time()
        return rpc, context

    def saved_login(self):
        rpc, context = self.login()
        row, auth = test_account_info.InfoTests.official(self)
        private_json(self.home / 'auth.json', auth)
        self.manager.info.identity['login']['owner'] = row['tokenOwner']
        self.manager.info.stamp = self.manager.info.source_stamp()
        self.bridge.account.subscription = lambda *args, **kwargs: {'source': 'login', 'observedAt': time.time()}
        subscription = patch('bridge.features.accounts.account.subscription_period',
                             return_value={'source': 'login', 'observedAt': time.time()})
        subscription.start()
        self.addCleanup(subscription.stop)
        return row, auth, rpc, context

    def test_importing_logged_in_account_twice_merges_identity_and_preserves_current_connection(self):
        row, _, rpc, _ = self.saved_login()
        self.manager.index['accounts'] = []
        before = self.manager.snapshot_files()
        with patch('bridge.features.accounts.accounts.ManagedRPC', return_value=rpc):
            candidates = self.manager.scan({})['discovery']['candidates']
        candidate = next(row for row in candidates if row['kind'] == 'chatgpt')
        for _ in range(2):
            self.manager.import_account({'candidateId': candidate['id'], 'name': 'My account'})
        value = self.manager.public()
        self.assertEqual(len(value['accounts']), 1)
        self.assertEqual(value['loginAccount']['id'], value['accounts'][0]['id'])
        self.assertEqual(value['loginAccount']['name'], 'My account')
        self.assertEqual(value['current']['name'], 'API · custom')
        self.assertIsNone(self.manager.index['activeId'])
        self.assertEqual(self.manager.snapshot_files(), before)

    def test_imported_current_account_uses_fresh_native_credentials_for_usage_and_reset(self):
        row, _, rpc, context = self.saved_login()
        identity = copy.deepcopy(self.manager.info.identity)
        private_json(self.manager.directory(row['id']) / 'auth.json', {'tokens': {'account_id': 'expired-import'}})
        before = self.manager.snapshot_files()
        homes = []
        def native_rpc(target):
            homes.append(target.home)
            self.assertEqual(target.home, self.home)
            return rpc
        with patch.object(self.manager.info, 'read_identity', return_value=identity), \
                patch('bridge.features.accounts.account.Account.rpc', native_rpc), \
                patch('bridge.features.accounts.accounts.ManagedRPC', return_value=rpc) as managed:
            self.manager.account({'id': row['id'], 'operation': 'read', 'refresh': False})
            self.manager.account({'id': row['id'], 'operation': 'consume', 'confirmed': True,
                                  'requestId': str(uuid.uuid4()), 'accountKey': context['accountKey'], 'creditId': 'card-1'})
            self.manager.info.read(row, 'usage')
            self.assertEqual(managed.call_args.args[0], self.home)
        self.assertEqual(homes, [self.home, self.home])
        self.assertEqual(self.manager.info.entries[row['id']]['usage']['status'], 'ready')
        self.assertEqual(self.manager.snapshot_files(), before)
        self.assertIsNone(self.manager.index['activeId'])

    def test_same_email_different_workspace_uses_saved_credentials_and_keeps_login_separate(self):
        row, auth, _, _ = self.saved_login()
        other = {**row, 'id': 'b' * 32, 'name': 'Other workspace', 'tokenOwner': ['other-org', *row['tokenOwner'][1:]]}
        other_auth = copy.deepcopy(auth)
        other_auth['tokens']['account_id'] = 'other-org'
        self.manager.index['accounts'].append(other)
        private_json(self.manager.directory(other['id']) / 'auth.json', other_auth)
        identity = copy.deepcopy(self.manager.info.identity)
        before = self.manager.snapshot_files()
        rpc = test_account.FakeRPC()
        rpc.auth['account']['email'] = row['email']
        def saved_rpc(target):
            self.assertEqual(target.home, self.manager.directory(other['id']))
            return rpc
        with patch.object(self.manager.info, 'read_identity', return_value=identity), \
                patch('bridge.features.accounts.account.Account.rpc', saved_rpc):
            result = self.manager.account({'id': other['id'], 'operation': 'read'})
        self.assertTrue(result['visible'])
        self.assertEqual(self.manager.public()['loginAccount']['id'], row['id'])
        self.assertEqual(len(self.manager.public()['accounts']), 2)
        self.assertEqual(self.manager.snapshot_files(), before)

    def test_deleting_imported_login_keeps_native_card_and_login_credentials(self):
        row, _, _, _ = self.saved_login()
        before = self.manager.snapshot_files()
        value = self.manager.control({'action': 'delete', 'id': row['id']})
        self.assertEqual(value['accounts'], [])
        self.assertEqual(value['loginAccount']['id'], CURRENT_LOGIN_ID)
        self.assertTrue(value['loginAccount']['transient'])
        self.assertEqual(self.manager.snapshot_files(), before)

    def test_official_model_query_keeps_saved_official_catalog_separate_from_aggregation(self):
        row, _, _, _ = self.saved_login()
        identity = copy.deepcopy(self.manager.info.identity)
        with patch.object(self.manager.info, 'read_identity', return_value=identity), \
                patch('bridge.features.accounts.accounts.ManagedRPC') as managed:
            managed.return_value.__enter__.return_value = test_account_info.InfoTests.rpc(self)
            self.manager.info.read(row, 'models')
            self.assertEqual(managed.call_args.args[0], self.manager.directory(row['id']))
        self.assertEqual(self.manager.info.entries[row['id']]['models']['status'], 'ready')

    def test_proxy_connection_and_native_login_are_displayed_without_enrollment(self):
        _, context = self.login()
        value = self.manager.public()
        self.assertEqual(value['accounts'], [])
        self.assertEqual(value['current']['kind'], 'api')
        self.assertEqual(value['loginAccount']['email'], 'fixture@example.test')
        self.assertTrue(value['loginAccount']['transient'])
        self.assertEqual(value['loginAccount']['accountKey'], context['accountKey'])
        self.assertFalse(self.manager.directory('a' * 32).exists())
        self.assertNotIn('owner', json.dumps(value))

    def test_usage_reads_native_login_and_preserves_configuration_and_saved_list(self):
        rpc, _ = self.login()
        before = self.manager.snapshot_files()
        with patch('bridge.features.accounts.account.Account.rpc', return_value=rpc):
            self.manager.info.read(self.manager.info.current_login(), 'usage')
        value = self.manager.public()
        usage = value['loginAccount']['details']['usage']
        self.assertEqual(usage['limits'][0]['windows'][0]['remainingPercent'], 75)
        self.assertEqual(usage['resetCredits']['availableCount'], 3)
        self.assertEqual(self.manager.snapshot_files(), before)
        self.assertEqual(value['accounts'], [])
        self.assertFalse(any(method.endswith('/consume') for method, _ in rpc.calls))

    def test_proxy_shaped_metadata_and_changed_identity_are_rejected(self):
        rpc, _ = self.login()
        for origin in ('https://proxy.test', None):
            rpc.auth['workspaceRouting']['backendOrigin'] = origin
            self.assertIsNone(Account.login_context(rpc))
        rpc.auth['workspaceRouting']['backendOrigin'] = 'https://chatgpt.com'
        rpc.auth['account']['email'] = 'other@example.test'
        with patch('bridge.features.accounts.account.Account.rpc', return_value=rpc):
            with self.assertRaises(ValueError):
                self.manager.account({'id': CURRENT_LOGIN_ID, 'operation': 'read'})

    def test_reset_is_confirmed_identity_bound_and_idempotent_on_proxy_connection(self):
        rpc, context = self.login()
        value = {'id': CURRENT_LOGIN_ID, 'operation': 'consume', 'confirmed': True,
                 'requestId': str(uuid.uuid4()), 'accountKey': context['accountKey'], 'creditId': 'card-1'}
        with patch('bridge.features.accounts.account.Account.rpc', return_value=rpc):
            with self.assertRaises(ValueError):
                self.manager.account({**value, 'confirmed': False})
            self.manager.account(value)
            self.manager.account(value)
            rpc.auth['account']['email'] = 'changed@example.test'
            with self.assertRaises(ValueError):
                self.manager.account({**value, 'requestId': str(uuid.uuid4())})
        self.assertEqual(sum(method.endswith('/consume') for method, _ in rpc.calls), 1)
        self.assertEqual(self.manager.index['accounts'], [])

    def test_changed_login_cannot_display_previous_quota_or_pending_reset(self):
        _, context = self.login()
        self.manager.info.entries[CURRENT_LOGIN_ID] = {'usage': {'accountKey': context['accountKey'], 'limits': ['old']}}
        self.assertTrue(self.manager.public()['loginAccount']['details'])
        self.manager.info.identity['login']['context'] = {**context, 'accountKey': 'b' * 64}
        self.assertEqual(self.manager.public()['loginAccount']['details'], {})
        (self.home / 'auth.json').write_text('{}')
        self.assertIsNone(self.manager.public()['loginAccount'])


if __name__ == '__main__':
    unittest.main()
