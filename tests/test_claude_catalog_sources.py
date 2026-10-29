import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bridge.clients.manager import DesktopSessions
from bridge.clients.errors import BridgeUnavailable

ROOT = Path(__file__).resolve().parents[1]
HISTORY = '客户端尚未提供当前可选模型，历史模型仅供查看'


class ClaudeCatalogSources(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.addCleanup(temp.cleanup)
        self.manager = DesktopSessions(Path(temp.name))
        self.addCleanup(self.manager.close)
        self.manager.adapters['claude'].index['session'] = {'backend': 'cowork'}
        self.store = Mock(lock=threading.RLock())
        self.store._current.return_value = ('api', 'current', {})
        for name, value in [('_account_store', self.store), ('_model_identity', 'session-account'),
                            ('_account_model_identity', 'api-account'), ('_model_live', True)]:
            mocked = patch.object(self.manager, name, return_value=value)
            mocked.start(); self.addCleanup(mocked.stop)
        self.account = {'models': [{'id': 'shared', 'efforts': []}, {'id': 'upstream'}],
                        'groups': [{'source': 'upstream-api', 'models': [{'id': 'shared'}, {'id': 'upstream'}]}]}
        self.native = {'models': [{'id': 'shared', 'efforts': ['high']}, {'id': 'historical'}],
                       'source': 'session-history', 'notice': HISTORY,
                       'capabilities': {'models': True, 'manualModels': True, 'manualEffort': True}}

    def test_fresh_merge_tracks_sources_and_replaces_history_only_notice(self):
        with patch.object(self.manager, '_account_models', return_value=self.account), \
             patch.object(self.manager, '_read', return_value=self.native):
            result = self.manager._catalog_models('claude', 'session', {'refresh': True})
        rows = {row['id']: row for row in result['models']}
        self.assertEqual(rows['shared']['source'], 'upstream-api')
        self.assertEqual(rows['shared']['efforts'], ['high'])
        self.assertEqual(rows['historical']['source'], 'session-history')
        self.assertNotEqual(result.get('notice'), HISTORY)
        self.assertIn('历史', result['notice'])
        cached = self.manager.model_store.read('session-account')[1]
        self.assertEqual(cached['source'], result['source'])
        self.assertEqual(cached['modelSourcesVersion'], 1)

    def test_existing_cache_is_repaired_without_network_or_refreshing_its_timestamp(self):
        self.manager.model_store.write('api-account', self.account)
        old = {key: value for key, value in self.native.items() if key != 'source'}
        stamp = self.manager.model_store.write('session-account', old)
        with patch.object(self.manager, '_read', side_effect=AssertionError('native read')), \
             patch.object(self.manager, '_account_models', side_effect=AssertionError('network query')):
            result = self.manager._catalog_models('claude', 'session', {})
        self.assertEqual(result['cache']['updatedAt'], stamp)
        self.assertNotEqual(result.get('notice'), HISTORY)
        self.assertEqual(next(row for row in result['models'] if row['id'] == 'shared')['source'], 'upstream-api')
        self.assertTrue(result['capabilities']['manualModels'])
        self.assertEqual(self.manager.model_store.read('session-account'), (stamp, old))

    def test_old_cache_without_matching_account_evidence_does_not_invent_provenance(self):
        self.manager.model_store.write('other-account', self.account)
        self.manager.model_store.write('session-account', {key: value for key, value in self.native.items() if key != 'source'})
        result = self.manager._catalog_models('claude', 'session', {})
        self.assertEqual({row['source'] for row in result['models']}, {'cached-unverified'})
        self.assertNotEqual(result.get('notice'), HISTORY)
        self.assertEqual([row['id'] for row in result['models']], ['shared', 'historical'])

    def test_genuine_history_only_result_keeps_warning_when_discovery_fails(self):
        with patch.object(self.manager, '_account_models', side_effect=BridgeUnavailable('offline')), \
             patch.object(self.manager, '_read', return_value=self.native):
            result = self.manager._catalog_models('claude', 'session', {'refresh': True})
        self.assertEqual(result['notice'], HISTORY)
        self.assertEqual({row['source'] for row in result['models']}, {'session-history'})

    def test_configured_models_are_not_claimed_as_upstream_results(self):
        self.account['groups'][0].update(source='desktop-config', notice='配置来源提示')
        with patch.object(self.manager, '_account_models', return_value=self.account), \
             patch.object(self.manager, '_read', return_value=self.native):
            result = self.manager._catalog_models('claude', 'session', {'refresh': True})
        self.assertEqual(result['models'][0]['source'], 'desktop-config')
        self.assertIn('配置来源提示', result['notice'])

    def test_all_models_confirmed_by_upstream_remove_history_warning_and_survive_cache(self):
        self.native['models'] = [self.native['models'][0]]
        with patch.object(self.manager, '_account_models', return_value=self.account), \
             patch.object(self.manager, '_read', return_value=self.native):
            fresh = self.manager._catalog_models('claude', 'session', {'refresh': True})
        with patch.object(self.manager, '_read', side_effect=AssertionError('native query')), \
             patch.object(self.manager, '_account_models', side_effect=AssertionError('upstream query')):
            cached = self.manager._catalog_models('claude', 'session', {})
        self.assertNotIn('notice', fresh)
        self.assertNotIn('notice', cached)
        self.assertEqual(cached['source'], 'upstream-api')
        self.assertEqual(cached['models'], fresh['models'])
        self.assertTrue(cached['capabilities']['manualEffort'])

    def test_account_change_during_legacy_cache_repair_is_rejected(self):
        self.manager.model_store.write('api-account', self.account)
        self.manager.model_store.write('session-account', self.native)
        with patch.object(self.manager, '_account_model_identity', side_effect=['api-account', 'changed']):
            with self.assertRaises(BridgeUnavailable):
                self.manager._catalog_models('claude', 'session', {})

    def test_official_account_never_borrows_api_catalog(self):
        self.store._current.return_value = ('official', 'current', None)
        with patch.object(self.manager, '_account_models', side_effect=AssertionError('API catalog')), \
             patch.object(self.manager, '_read', return_value=self.native):
            result = self.manager._catalog_models('claude', 'session', {'refresh': True})
        self.assertEqual(result['notice'], HISTORY)

