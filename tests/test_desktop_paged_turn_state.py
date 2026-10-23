import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from bridge.clients.manager import DesktopSessions


class PagedTurnState(unittest.TestCase):
    def test_history_pages_keep_current_session_authority(self):
        root = Path(__file__).resolve().parents[1] / '.tmp'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            manager = DesktopSessions(folder)
            self.addCleanup(manager.close)
            adapter = Mock()
            manager.adapters['deepseek'] = adapter
            current = {'id': 'one', 'status': 'active', 'turnId': 'current',
                       'turnStatus': 'inProgress', 'requests': [{'id': 'approval'}]}
            adapter.call.return_value = {'session': current, 'messages': [],
                                         'turns': [{'turnId': 'older', 'status': 'completed'}],
                                         'history': {'before': 'cursor', 'hasMore': True}}
            recent = manager._read('deepseek', 'detail', 'one')
            self.assertEqual(recent['session'], current)
            adapter.call.return_value['history'] = {'before': None, 'hasMore': False}
            older = manager._read('deepseek', 'detail', 'one', {'historyBefore': 'cursor'})
            self.assertEqual(older['session'], current)
            self.assertEqual(older['session']['requests'], [{'id': 'approval'}])
            self.assertEqual(older['turns'][0]['turnId'], 'older')

    def test_legacy_full_transcript_retains_existing_turn_projection(self):
        root = Path(__file__).resolve().parents[1] / '.tmp'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            manager = DesktopSessions(folder)
            self.addCleanup(manager.close)
            adapter = Mock()
            manager.adapters['deepseek'] = adapter
            adapter.call.return_value = {'session': {'id': 'one'}, 'messages': [],
                                         'turns': [{'turnId': 'full', 'status': 'completed'}]}
            value = manager._read('deepseek', 'detail', 'one')
            self.assertEqual(value['session']['turnId'], 'full')
            self.assertEqual(value['session']['turnStatus'], 'completed')
            adapter.call.return_value = {'session': {'id': 'one'}, 'messages': [],
                                         'turns': [{'turnId': 'full', 'status': 'completed'}],
                                         'history': {'before': None, 'hasMore': False}}
            complete = manager._read('deepseek', 'detail', 'one')
            self.assertEqual(complete['session']['turnStatus'], 'completed')
