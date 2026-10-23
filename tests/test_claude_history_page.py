import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from bridge.clients.claude.adapter import Claude
from bridge.clients.claude.model import gateway_id


class ClaudeHistoryPage(unittest.IsolatedAsyncioTestCase):
    async def test_cursor_binds_session_and_reaches_native_page(self):
        temporary = Path(__file__).resolve().parents[1] / '.tmp'
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as folder:
            adapter = Claude(Path(folder), auto_connect=False)
            sid = gateway_id('code', 'native-one')
            row = {'sessionId': 'native-one', 'cwd': folder, 'isRunning': True}
            adapter.index[sid] = {'backend': 'code', 'nativeId': 'native-one'}
            calls = []

            async def call(kind, method, *args):
                calls.append((kind, method, args))
                return {'session': row, 'transcript': [{'type': 'user', 'uuid': 'u1', 'message': {'role': 'user', 'content': 'hello'}}],
                        'history': {'before': 'u1' if len(calls) == 1 else None, 'hasMore': len(calls) == 1}}

            adapter.desktop = Mock(capabilities={'code': ['mobileDetail', 'mobileHistory']}, call=AsyncMock(side_effect=call))
            first = await adapter.dispatch('detail', sid, {})
            self.assertEqual(first['messages'][0]['text'], 'hello')
            self.assertTrue(first['history']['hasMore'])
            self.assertEqual(calls[0][2][1], {'historyLimit': 40, 'historyBefore': None})
            await adapter.dispatch('detail', sid, {'historyBefore': first['history']['before'], 'historyLimit': 20})
            self.assertEqual(calls[1][2][1], {'historyLimit': 20, 'historyBefore': 'u1'})
            adapter.index[gateway_id('code', 'native-other')] = {'backend': 'code', 'nativeId': 'native-other'}
            with self.assertRaisesRegex(ValueError, '历史游标无效'):
                await adapter.dispatch('detail', gateway_id('code', 'native-other'), {'historyBefore': first['history']['before']})
