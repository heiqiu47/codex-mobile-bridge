"""Canonical native branch identities without invoking a desktop runtime."""
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bridge.clients.claude.adapter import Claude
from bridge.clients.claude.model import session, gateway_id
from bridge.clients.deepseek.adapter import messages


class ClaudeFork(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.adapter = Claude(Path(self.temp.name)/'claude', auto_connect=False)
        self.native = {'sessionId': 'parent', 'turnRunning': False}
        self.row = session('code', self.native)
        self.adapter.index = {self.row['id']: self.row}
        self.adapter.desktop = SimpleNamespace(connected=True, capabilities={'code': ['mobileFork', 'mobileDetail']}, call=AsyncMock())

    async def test_adapter_preserves_canonical_identity_and_native_child(self):
        rid = str(uuid.uuid4())
        self.adapter.desktop.call.side_effect = [self.native, {'sessionId': 'local_'+rid}]
        with patch.object(self.adapter, 'prepare'), patch.object(self.adapter, 'connect'), patch.object(self.adapter, 'reconnect'):
            result = await self.adapter.dispatch('fork', self.row['id'], {'id': rid, 'messageId': 'native-row'})
        self.assertEqual(result, {'status': 'ready', 'result': {'id': gateway_id('code', 'local_'+rid)}})
        self.adapter.desktop.call.assert_awaited_with('code', 'mobileFork', 'parent', {'id': rid, 'messageId': 'native-row'})

    async def test_only_verified_primary_uuid_gets_a_branch_action(self):
        raw = [{'type': 'assistant', 'uuid': 'main-row', 'message': {'content': 'Main'}},
               {'type': 'assistant', 'uuid': 'child-row', 'isSidechain': True, 'message': {'content': 'Child'}},
               {'type': 'assistant', 'message': {'id': 'sdk-only', 'content': 'No canonical row'}}]
        self.adapter.desktop.call.return_value = {'session': self.native, 'transcript': raw}
        with patch.object(self.adapter, 'prepare'), patch.object(self.adapter, 'connect'), patch.object(self.adapter, 'reconnect'):
            result = await self.adapter.dispatch('detail', self.row['id'], {})
        self.assertEqual([m.get('forkMessageId') for m in result['messages']], ['main-row', None, None])


class DeepSeekFork(unittest.TestCase):
    def test_only_final_assistant_of_a_completed_native_turn_gets_end_sequence(self):
        def record(seq, kind, data):
            return {'event': {'seq': seq, 'type': kind, 'data': data}}
        rows = [record(1, 'turn/start', {'turn': 1}),
                record(2, 'assistant/message', {'message': {'content': [{'type': 'text', 'text': 'Interim'}]}}),
                record(3, 'assistant/message', {'message': {'content': [{'type': 'text', 'text': 'Final'}]}}),
                record(4, 'turn/end', {'turn': 1, 'reason': {'kind': 'completed'}}),
                record(5, 'turn/start', {'turn': 2}),
                record(6, 'assistant/message', {'message': {'content': 'Interrupted'}}),
                record(7, 'turn/end', {'turn': 2, 'reason': {'kind': 'aborted'}})]
        self.assertEqual([m.get('forkMessageId') for m in messages(rows)], [None, '4', None])
        self.assertFalse(any('forkMessageId' in m for m in messages(rows[:3])))
