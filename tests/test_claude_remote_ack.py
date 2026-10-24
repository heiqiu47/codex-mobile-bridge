"""Durable remote user UUID acknowledgement without replay/echo events."""
import copy
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge.clients.claude.remote import RemoteClaudeCli
from bridge.clients.claude.wsl import WslClaudeCli
from bridge.clients.errors import BridgeUnavailable


class RemoteDurableAckTests(unittest.TestCase):
    def adapter(self, kind, *, save=True, finished=False):
        host_id = 'ssh:fixture' if kind is RemoteClaudeCli else 'wsl-claude:fixture'
        host = {'alias': 'fixture', 'distribution': 'Fixture Ubuntu', 'user': 'fixture'}
        hosts = SimpleNamespace(hosts=lambda: {host_id: host})
        cli = kind(hosts)
        self.addCleanup(cli.close)
        cli._command = Mock(return_value=['fixture-only'])
        cli._process_options = Mock(return_value={})
        process = Mock(); process.poll.return_value = None
        owner = SimpleNamespace(process=process, origin='fixture-origin', native=str(uuid.uuid4()),
            cwd='/fixture/project', condition=threading.Condition(), preflight={'status': 'ready'},
            active=False, pending={}, finished=False, error=None, model=None, permission=None,
            events=[], catalog={}, control=Mock(return_value={}), close=Mock())
        saved = {'events': [], 'overrides': {}}
        def write(frame):
            if save:
                saved['events'].append({'type': 'user', 'uuid': frame['uuid'], 'cwd': owner.cwd,
                                        'message': copy.deepcopy(frame['message'])})
            owner.finished = finished
        owner.write = Mock(side_effect=write)
        def remote(alias, request, **kwargs):
            if request['operation']=='projects':
                return {'profile': {'origin': owner.origin}, 'authReady': True}
            if request['operation']=='detail':
                return {'nativeId': owner.native, 'origin': owner.origin, 'cwd': owner.cwd,
                        'model': '', 'permissionMode': 'default', 'permissionKnown': True,
                        'stamp': [1, 2, 3, 4, 5], **saved['overrides']}
            if request['operation']=='history':
                return {'events': copy.deepcopy(saved['events']), 'stamp': [1, 2, 3, 4, 5],
                        'history': {'before': None, 'hasMore': False}}
            self.fail('Unexpected read operation: '+request['operation'])
        cli._remote = Mock(side_effect=remote)
        return cli, owner, process, host_id, host, saved

    def test_create_accepts_saved_uuid_without_echo_for_ssh_and_wsl(self):
        for kind in (RemoteClaudeCli, WslClaudeCli):
            with self.subTest(kind=kind.transport_kind):
                cli, owner, process, host_id, _, _ = self.adapter(kind)
                def new_owner(proc, origin, native, cwd):
                    owner.origin, owner.native, owner.cwd = origin, native, cwd
                    return owner
                with patch('bridge.clients.claude.remote.subprocess.Popen', return_value=process), \
                     patch('bridge.clients.claude.remote._Owned', side_effect=new_owner):
                    result = cli.create(host_id, 'fixture', owner.origin, owner.cwd, 'first request')
                self.assertEqual(result['status'], 'ready')
                owner.write.assert_called_once()
                self.assertFalse(hasattr(owner, 'user_acks'))

    def test_send_accepts_saved_uuid_without_echo_for_ssh_and_wsl(self):
        for kind in (RemoteClaudeCli, WslClaudeCli):
            with self.subTest(kind=kind.transport_kind):
                cli, owner, _, host_id, host, _ = self.adapter(kind)
                row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
                cli.index[row['id']] = row; cli.owned[row['id']] = owner
                self.assertEqual(cli.call('send', row['id'], {'text': 'once'}), {'status': 'accepted'})
                owner.write.assert_called_once()
                self.assertFalse(hasattr(owner, 'user_acks'))

    def test_unconfirmed_send_remains_unknown_and_does_not_replay(self):
        for kind in (RemoteClaudeCli, WslClaudeCli):
            with self.subTest(kind=kind.transport_kind):
                cli, owner, _, host_id, host, _ = self.adapter(kind, save=False, finished=True)
                row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
                cli.index[row['id']] = row; cli.owned[row['id']] = owner
                with self.assertRaisesRegex(BridgeUnavailable, '结果不明'):
                    cli.call('send', row['id'], {'text': 'once'})
                with self.assertRaisesRegex(BridgeUnavailable, '请等待'):
                    cli.call('send', row['id'], {'text': 'once'})
                owner.write.assert_called_once()

    def test_create_unconfirmed_write_keeps_original_owner_and_does_not_retry(self):
        cli, owner, process, host_id, _, _ = self.adapter(RemoteClaudeCli, save=False, finished=True)
        def new_owner(proc, origin, native, cwd):
            owner.origin, owner.native, owner.cwd = origin, native, cwd
            return owner
        with patch('bridge.clients.claude.remote.subprocess.Popen', return_value=process), \
             patch('bridge.clients.claude.remote._Owned', side_effect=new_owner):
            with self.assertRaisesRegex(BridgeUnavailable, '结果不明'):
                cli.create(host_id, 'fixture', owner.origin, owner.cwd, 'first request')
        owner.write.assert_called_once()
        owner.close.assert_not_called()
        self.assertEqual(list(cli.owned.values()), [owner])
        self.assertEqual(cli.index, {})

    def test_durable_uuid_cannot_confirm_another_native_origin_or_cwd(self):
        for key in ('nativeId', 'origin', 'cwd'):
            with self.subTest(key=key):
                cli, owner, _, host_id, host, saved = self.adapter(RemoteClaudeCli)
                row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
                cli.index[row['id']] = row; cli.owned[row['id']] = owner
                saved['overrides'][key] = 'changed'
                with self.assertRaisesRegex(BridgeUnavailable, '身份或工作目录已变化'):
                    cli.call('send', row['id'], {'text': 'once'})
                owner.write.assert_called_once()
                self.assertFalse(any(c.args[1]['operation']=='history' for c in cli._remote.call_args_list))

    def test_uuid_confirmation_walks_existing_history_pages_without_resending(self):
        cli, owner, _, host_id, host, saved = self.adapter(RemoteClaudeCli)
        row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
        cli.index[row['id']] = row; cli.owned[row['id']] = owner
        original = cli._remote.side_effect
        def older_page(alias, request, **kwargs):
            result = original(alias, request, **kwargs)
            if request['operation']=='history' and request['historyBefore'] is None:
                result.update(events=[], history={'before': 'older', 'hasMore': True})
            return result
        cli._remote.side_effect = older_page
        self.assertEqual(cli.call('send', row['id'], {'text': 'once'}), {'status': 'accepted'})
        history = [c.args[1] for c in cli._remote.call_args_list if c.args[1]['operation']=='history']
        self.assertEqual([p['historyBefore'] for p in history], [None, 'older'])
        self.assertTrue(all(p['scope']==row['id'] for p in history))
        owner.write.assert_called_once()

    def test_replaced_history_cannot_confirm_uuid_against_different_file(self):
        cli, owner, _, host_id, host, saved = self.adapter(RemoteClaudeCli, finished=True)
        row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
        cli.index[row['id']] = row; cli.owned[row['id']] = owner
        original = cli._remote.side_effect
        def changed_file(alias, request, **kwargs):
            result = original(alias, request, **kwargs)
            if request['operation']=='history':
                result['stamp'] = [1, 9, 3, 4, 5]
            return result
        cli._remote.side_effect = changed_file
        with self.assertRaisesRegex(BridgeUnavailable, '结果不明'):
            cli.call('send', row['id'], {'text': 'once'})
        owner.write.assert_called_once()

    def test_normal_append_acknowledges_immediately_without_echo(self):
        for kind in (RemoteClaudeCli, WslClaudeCli):
            with self.subTest(kind=kind.transport_kind):
                cli, owner, _, host_id, host, _ = self.adapter(kind, finished=True)
                row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
                cli.index[row['id']] = row; cli.owned[row['id']] = owner
                original = cli._remote.side_effect
                def appended(alias, request, **kwargs):
                    result = original(alias, request, **kwargs)
                    if request['operation']=='history':
                        result['stamp'] = [1, 2, 300, 400, 500]
                    return result
                cli._remote.side_effect = appended
                with patch('bridge.clients.claude.remote.time.sleep') as sleep:
                    self.assertEqual(cli.call('send', row['id'], {'text': 'once'}), {'status': 'accepted'})
                sleep.assert_not_called()
                owner.write.assert_called_once()

    def test_matching_uuid_in_another_cwd_does_not_acknowledge(self):
        cli, owner, _, host_id, host, saved = self.adapter(RemoteClaudeCli, finished=True)
        row = cli._row(host_id, host, cli._remote('fixture', {'operation': 'detail'}))
        cli.index[row['id']] = row; cli.owned[row['id']] = owner
        original = owner.write.side_effect
        def wrong_cwd(frame):
            original(frame)
            saved['events'][0]['cwd'] = '/changed/project'
        owner.write.side_effect = wrong_cwd
        with self.assertRaisesRegex(BridgeUnavailable, '结果不明'):
            cli.call('send', row['id'], {'text': 'once'})
        owner.write.assert_called_once()
