"""Native Desktop rename stays separate from CLI aliases and session activation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from bridge.clients.claude.adapter import Claude
from bridge.clients.claude.mailbox import MUTATIONS
from bridge.clients.claude.model import gateway_id
from bridge.clients.errors import BridgeUnavailable


class ClaudeRename(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.tmp')
        self.addCleanup(self.temp.cleanup)
        self.adapter = Claude(Path(self.temp.name), auto_connect=False)
        self.adapter.desktop = Mock(capabilities={kind: ['mobileRename'] for kind in ('code', 'cowork')})
        self.adapter.desktop.call = AsyncMock()
        for kind in ('code', 'cowork'):
            self.adapter.index[gateway_id(kind, kind + '-id')] = {'backend': kind, 'nativeId': kind + '-id'}

    async def test_both_surfaces_use_verified_native_method_and_gateway_identity(self):
        self.assertIn('mobileRename', MUTATIONS)
        for kind in ('code', 'cowork'):
            sid = gateway_id(kind, kind + '-id')
            self.adapter.desktop.call.return_value = {'status': 'confirmed', 'scope': 'native',
                                                     'result': {'id': kind + '-id', 'title': '新名称'}}
            result = await self.adapter.dispatch('rename', sid, {'title': ' 新名称 '})
            self.assertEqual(result['result'], {'id': sid, 'title': '新名称'})
            self.adapter.desktop.call.assert_awaited_with(kind, 'mobileRename', kind + '-id', {'title': '新名称'})

    async def test_missing_capability_or_invalid_title_never_sends(self):
        sid = gateway_id('code', 'code-id')
        for title in (None, {}, '', 'x' * 121, 'bad\nname', '\nname'):
            with self.assertRaises(ValueError):
                await self.adapter.dispatch('rename', sid, {'title': title})
        self.adapter.desktop.capabilities['code'] = ['updateSession']
        self.assertFalse(self.adapter.session_capabilities('code')['rename'])
        with self.assertRaisesRegex(ValueError, '原生改名'):
            await self.adapter.dispatch('rename', sid, {'title': '新名称'})
        self.adapter.desktop.call.assert_not_awaited()

    async def test_unknown_or_wrong_identity_never_replays(self):
        sid = gateway_id('code', 'code-id')
        for reply in ({'status': 'accepted'}, {'status': 'confirmed', 'result': {'id': 'different', 'title': '新名称'}}):
            self.adapter.desktop.call.reset_mock()
            self.adapter.desktop.call.return_value = reply
            with self.assertRaisesRegex(BridgeUnavailable, '结果待核对'):
                await self.adapter.dispatch('rename', sid, {'title': '新名称'})
            self.assertEqual(self.adapter.desktop.call.await_count, 1)
