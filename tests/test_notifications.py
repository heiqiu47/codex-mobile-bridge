import http.server
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from bridge.features.notifications.channels import Notifications, publish, publish_bark, publish_pushplus, publish_webhook, settings, save_settings, write_json, read_json, visible_webhook
from bridge.app.service import LiveSession

ROOT = Path(__file__).resolve().parents[1]


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.directory = Path(self.temp.name)
        self.thread = str(uuid.uuid4())
        self.session = LiveSession(self.thread)
        self.session.connected = True
        self.session.state = {'title': 'Private project', 'requests': [
            {'id': 'approval', 'method': 'item/commandExecution/requestApproval', 'params': {'command': 'secret command'}}]}
        session = self.session
        class Source:
            def for_host(self, host):
                if host not in ('local', 'remote'): raise KeyError(host)
                return self
            def session(self, thread, **kwargs):
                return session
        self.source = Source()
        self.manager = Notifications(self.source, self.directory, lambda: ['http://10.0.0.1:8787', 'https://example.com'])
        save_settings(self.directory, {'enabled': True, 'topic': 'test', 'token': 'secret-token'})
        self.manager.watch(self.thread, 'remote', True)

    def test_global_defaults_monitor_unwatched_chats_without_loading_history(self):
        # Discovery finds a chat that was never explicitly watched.
        other = str(uuid.uuid4())
        self.source.notification_candidates = lambda: [{'id': other, 'host': 'local'}]
        self.source.notification_session = lambda identifier: self.session
        self.source.store = type('Store', (), {'get': lambda _, identifier: {}})()
        self.manager.watch(self.thread, 'remote', False)
        with patch.object(self.source, 'session', side_effect=AssertionError('history read')), patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan()
            self.assertEqual(send.call_count, 1)
            self.manager.policy(other, 'local', {'requests': 'off', 'completion': 'on'})
            self.session.state['turns'] = [{'turnId':'old','status':'completed','items':[]}]
            self.manager.scan();self.assertEqual(send.call_count, 1)
            self.session.state['turns'].append({'turnId':'new','status':'inProgress','items':[]})
            self.manager.scan()
            self.session.state['turns'][-1]['status'] = 'completed'
            self.manager.scan();self.assertEqual(send.call_count, 2)
        self.assertEqual(self.manager.policy(other,'local')['requests'], 'off')
        self.assertTrue(self.manager.policy(other,'local')['notifyOnCompletion'])

    def test_global_policy_inheritance_and_explicit_overrides_survive_restart(self):
        other = str(uuid.uuid4())
        self.source.store = type('Store', (), {'get': lambda _, identifier: {}})()
        self.assertTrue(self.manager.policy(other, 'local')['notifyOnRequest'])
        self.manager.defaults({'requests': False, 'completion': True})
        self.assertFalse(self.manager.policy(other, 'local')['notifyOnRequest'])
        self.assertTrue(self.manager.policy(other, 'local')['notifyOnCompletion'])
        self.manager.policy(other, 'local', {'requests': 'on', 'completion': 'off'})
        other_manager = Notifications(self.source, self.directory)
        self.assertTrue(other_manager.policy(other, 'local')['notifyOnRequest'])
        self.assertFalse(other_manager.policy(other, 'local')['notifyOnCompletion'])
        # Legacy explicit choices are independent of the new defaults.
        self.assertFalse(other_manager.policy(self.thread, 'remote')['notifyOnCompletion'])
        other_manager.close()

    def test_pushplus_token_validation_preservation_and_clear(self):
        with self.assertRaises(ValueError):
            save_settings(self.directory, {'pushplusEnabled': True})
        save_settings(self.directory, {'pushplusEnabled': True, 'pushplusToken': 'private-token'})
        self.assertEqual(save_settings(self.directory, {'pushplusToken': ''})['pushplusToken'], 'private-token')
        for token in (123, 'x\ny', 'x y'):
            with self.assertRaises(ValueError):
                save_settings(self.directory, {'pushplusToken': token})
        with self.assertRaises(ValueError):
            save_settings(self.directory, {'clearPushplusToken': True})
        self.assertEqual(save_settings(self.directory, {'pushplusEnabled': False, 'clearPushplusToken': True})['pushplusToken'], '')

    def test_webhook_config_validation_and_secret_preservation(self):
        self.assertFalse(settings(self.directory)['webhookEnabled'])
        first = 'https://receiver.example/private/key?signature=signed'
        save_settings(self.directory, {'webhookEnabled': True, 'webhookUrl': first,
                                       'webhookHeaders': {'Authorization': 'Bearer private'}})
        visible = visible_webhook(settings(self.directory))
        self.assertEqual(visible['webhookUrlDisplay'], 'https://receiver.example')
        self.assertEqual(visible['webhookUrl'], '')
        self.assertEqual(visible['webhookHeaders'], {})
        self.assertTrue(visible['hasWebhookUrl'] and visible['hasWebhookHeaders'])
        self.assertNotIn('private', json.dumps(visible))
        save_settings(self.directory, {'webhookUrl': '', 'webhookHeaders': {}})
        self.assertEqual(settings(self.directory)['webhookUrl'], first)
        self.assertEqual(settings(self.directory)['webhookHeaders'], {'Authorization': 'Bearer private'})
        save_settings(self.directory, {'webhookUrl': 'https://other.example/path?key=second'})
        self.assertEqual(settings(self.directory)['webhookHeaders'], {})
        save_settings(self.directory, {'webhookEnabled': False, 'clearWebhookUrl': True})
        self.assertEqual(settings(self.directory)['webhookUrl'], '')
        for invalid in ('http://remote.example/hook', 'https://u:p@example.com', 'https://example.com/#frag',
                        'ftp://example.com', 'https://example.com/\rInjected', 'https://[broken'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                save_settings(self.directory, {'webhookUrl': invalid})
        for invalid in ({'Host': 'bad'}, {'Content-Length': '3'}, {'X-Test': 'one\r\ntwo'}, {'Bad Header': 'x'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                save_settings(self.directory, {'webhookHeaders': invalid})
        for field, invalid in (('webhookUrl', None), ('webhookUrl', False), ('webhookHeaders', None),
                               ('webhookHeaders', []), ('webhookHeaders', False)):
            with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                save_settings(self.directory, {field: invalid})
        for invalid in ('{"{{event}}": 1}', '{"x": "{{unknown}}"}', '{"x": "{{event"}', '{bad',
                        '{"x": NaN}', '{"x": "\\ud800"}', '[' * 40 + '0' + ']' * 40):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                save_settings(self.directory, {'webhookBodyTemplate': invalid})

    def test_webhook_delivery_dedupe_destination_change_and_title_privacy(self):
        save_settings(self.directory, {'enabled': False, 'webhookEnabled': True,
                                       'webhookUrl': 'https://receiver.example/hook?key=first'})
        with patch('bridge.features.notifications.channels.publish_webhook') as send:
            self.manager.scan(); self.manager.scan()
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.kwargs['event'], 'approval.required')
            self.assertEqual(send.call_args.kwargs['session_name'], '')
            self.assertNotIn('Private project', send.call_args.args[2])
            save_settings(self.directory, {'webhookHeaders': {'Authorization': 'Bearer second'}})
            self.manager.scan()
            self.assertEqual(send.call_count, 2)
        ledger = json.dumps(read_json(self.directory/'notification-delivery.json', {}))
        self.assertNotIn('second', ledger)
        self.assertNotIn('first', ledger)

    def test_webhook_failure_retries_after_restart_only_while_enabled(self):
        save_settings(self.directory, {'enabled': False, 'webhookEnabled': True,
                                       'webhookUrl': 'https://receiver.example/hook'})
        with patch('bridge.features.notifications.channels.publish_webhook', side_effect=OSError('private credential')):
            self.manager.scan()
        status = read_json(self.directory/'notification-status.json', {})
        self.assertNotIn('private credential', json.dumps(status))
        self.manager.close()
        self.manager = Notifications(self.source, self.directory)
        for record in self.manager.ledger.values():
            record['next'] = 0
        save_settings(self.directory, {'webhookEnabled': False})
        with patch('bridge.features.notifications.channels.publish_webhook') as send:
            self.manager.scan()
            send.assert_not_called()
            save_settings(self.directory, {'webhookEnabled': True})
            self.manager.scan()
            send.assert_called_once()

    def test_account_reminder_sends_webhook_without_disrupting_existing_channel(self):
        from bridge.features.accounts.monitor import AccountMonitor
        manager = type('Manager', (), {'root': self.directory,
            'bridge': type('Bridge', (), {'data_dir': self.directory})()})()
        monitor = AccountMonitor(manager)
        monitor.configure = lambda value: monitor.preferences.update(value)
        monitor.preferences['lowQuota'] = True
        save_settings(self.directory, {'webhookEnabled': True, 'webhookUrl': 'https://receiver.example/hook'})
        with patch('bridge.features.accounts.monitor.publish') as ntfy, \
                patch('bridge.features.accounts.monitor.publish_webhook') as webhook:
            self.assertTrue(monitor.deliver('account-1', ('lowQuota', 'window-1', '额度提醒', '请查看')))
            ntfy.assert_called_once()
            webhook.assert_called_once()
            self.assertEqual(webhook.call_args.kwargs['event'], 'account.lowQuota')
            self.assertTrue(monitor.deliver('account-1', ('lowQuota', 'window-1', '额度提醒', '请查看')))
            webhook.assert_called_once()

    def test_webhook_post_template_escaping_and_redirect_rejection(self):
        captured = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append((self.path, self.headers.get('Authorization'),
                                 json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(302 if len(captured) == 2 else 200)
                if len(captured) == 2:
                    self.send_header('Location', '/receiver/private')
                self.end_headers()
                if len(captured) == 2:
                    self.wfile.write(b'Bearer secret')
            def do_GET(self):
                captured.append(('redirect followed', '', {}))
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/receiver/private?signature=abc'
            config = save_settings(self.directory, {'webhookEnabled': True, 'webhookUrl': url,
                'webhookHeaders': {'Authorization': 'Bearer secret'},
                'webhookBodyTemplate': '{"event":"{{event}}","event_id":"{{event_id}}","nested":["{{body}}","{{session_name}}"],"count":"{{count}}"}'})
            publish_webhook(config, '标题', '中文 "引号"\n换行', event='task.completed', session_name='私密聊天', count=2)
            self.assertEqual(captured[0][0:2], ('/receiver/private?signature=abc', 'Bearer secret'))
            self.assertEqual({key: value for key, value in captured[0][2].items() if key != 'event_id'},
                {'event': 'task.completed', 'nested': ['中文 "引号"\n换行', '私密聊天'], 'count': '2'})
            self.assertTrue(captured[0][2]['event_id'])
            with self.assertRaises(RuntimeError) as error:
                publish_webhook(config, 'again', 'again')
            self.assertNotIn('secret', str(error.exception))
            self.assertEqual(len(captured), 2)
        finally:
            server.shutdown(); server.server_close()

    def test_pushplus_delivery_deduplicates_and_new_recipient_gets_alert(self):
        save_settings(self.directory, {'enabled': False, 'pushplusEnabled': True, 'pushplusToken': 'first'})
        with patch('bridge.features.notifications.channels.publish_pushplus') as send:
            self.manager.scan(); self.manager.scan()
            self.assertEqual(send.call_count, 1)
            save_settings(self.directory, {'pushplusToken': 'second'})
            self.manager.scan()
            self.assertEqual(send.call_count, 2)
        ledger = read_json(self.directory/'notification-delivery.json', {})
        self.assertTrue(all(k.startswith('pushplus:') for k in ledger))
        self.assertNotIn('second', json.dumps(ledger))

    def test_pushplus_payload_and_application_errors_are_sanitized(self):
        from unittest.mock import MagicMock
        config = {**settings(self.directory), 'pushplusToken': 'secret-pushplus'}
        response = MagicMock(); response.status = 200; response.read.return_value = b'{"code":200}'
        with patch('bridge.features.notifications.channels.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = response
            publish_pushplus(config, 'Title', 'Body', 'https://example.com/#chat')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://www.pushplus.plus/send')
            self.assertEqual(json.loads(request.data), {'token': 'secret-pushplus', 'title': 'Title', 'content': 'Body\n\nhttps://example.com/#chat', 'template': 'txt'})
            response.read.return_value = b'{"code":401,"msg":"secret-pushplus"}'
            with self.assertRaises(RuntimeError) as error:
                publish_pushplus(config, 'Title', 'Body')
            self.assertNotIn('secret-pushplus', str(error.exception))

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def test_watch_runs_without_viewers_and_deduplicates_after_restart(self):
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan(); self.manager.scan()
            self.assertEqual(send.call_count, 1)
            self.assertTrue(self.session.watched)
            self.assertEqual(self.session.viewers, 0)
            config, title, body, click = send.call_args.args
            self.assertNotIn('secret command', body)
            self.assertNotIn('Private project', body)
            self.assertEqual(click, 'https://example.com/#'+self.thread+'~remote')
            other = Notifications(self.source, self.directory)
            other.scan()
            self.assertEqual(send.call_count, 1)
            other.close()

    def test_new_request_notifies_and_completed_request_does_not_retry(self):
        with patch('bridge.features.notifications.channels.publish', side_effect=OSError('offline')) as send:
            self.manager.scan()
            self.assertEqual(send.call_count, 1)
        for record in self.manager.ledger.values(): record['next'] = 0
        self.session.state['requests'] = []
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan();self.assertFalse(send.called)
            self.session.state['requests'] = [{'id': 'another', 'method': 'item/tool/requestUserInput', 'params': {'questions': []}}]
            self.manager.scan();self.assertEqual(send.call_count, 1)

    def test_disabled_or_offline_history_never_pushes(self):
        with patch('bridge.features.notifications.channels.publish') as send:
            self.session.connected = False
            self.manager.scan();self.assertFalse(send.called)
            save_settings(self.directory, {'enabled': False})
            self.manager.scan();self.assertFalse(self.session.watched)
            self.assertFalse(send.called)

    def test_coalesces_pending_requests_and_unwatch_releases(self):
        self.session.state['requests'].append({'id': 2, 'method': 'item/permissions/requestApproval', 'params': {}})
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan();self.assertEqual(send.call_count, 1)
            self.assertIn('2 项', send.call_args.args[2])
            self.manager.watch(self.thread, 'remote', False)
            self.manager.scan();self.assertFalse(self.session.watched)

    def test_async_question_is_detected(self):
        self.session.state = {'turns': [{'turnId': 't', 'status': 'inProgress', 'items': [
            {'type': 'agentMessage', 'id': 'q', 'questions': [{'title': 'Choose', 'options': None}]}]}]}
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan();self.assertEqual(send.call_count, 1)

    def turns(self, *rows):
        self.session.state = {'title': 'Private project', 'turns': [
            {'turnId': turn_id, 'status': status, 'items': []} for turn_id, status in rows]}

    def test_completion_option_is_per_host_and_defaults_off_for_existing_watches(self):
        write_json(self.directory/'notification-watches.json', [{'id': self.thread, 'host': 'remote'}])
        self.assertFalse(self.manager.watch(self.thread, 'remote')['notifyOnCompletion'])
        self.manager.watch(self.thread, 'local', True)
        self.turns(('run', 'inProgress'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        self.assertTrue(self.manager.watch(self.thread, 'remote', True)['notifyOnCompletion'])
        self.assertFalse(self.manager.watch(self.thread, 'local')['notifyOnCompletion'])
        other = Notifications(self.source, self.directory)
        self.assertTrue(other.watch(self.thread, 'remote')['notifyOnCompletion'])
        with patch('bridge.features.notifications.channels.publish') as send:
            other.scan()
            self.turns(('run', 'completed'))
            other.scan()
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[1], 'Codex 运行已完成')
        other.close()
        self.assertFalse(self.manager.watch(self.thread, 'remote', False)['watching'])
        self.assertFalse(self.manager.watch(self.thread, 'remote', True)['notifyOnCompletion'])
        for invalid in ('true', 1, []):
            with self.assertRaises(ValueError):
                self.manager.watch(self.thread, 'remote', notify_on_completion=invalid)

    def test_completion_of_current_run_deduplicates_after_restart_and_hides_content(self):
        self.turns(('old', 'completed'), ('current', 'inProgress'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan();self.assertFalse(send.called)
            self.turns(('old', 'completed'), ('current', 'completed'))
            self.manager.scan();self.manager.scan()
            self.assertEqual(send.call_count, 1)
            self.assertNotIn('Private project', send.call_args.args[2])
            self.assertIn('1 次运行', send.call_args.args[2])
            self.assertTrue(send.call_args.args[3].endswith('~remote'))
            other = Notifications(self.source, self.directory)
            other.scan();self.assertEqual(send.call_count, 1)
            other.close()

    def test_fast_run_between_scans_notifies_but_paginated_history_does_not(self):
        self.turns(('last', 'completed'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        with patch('bridge.features.notifications.channels.publish') as send:
            self.turns(('older', 'completed'), ('last', 'completed'))
            self.manager.scan();self.assertFalse(send.called)
            self.turns(('older', 'completed'))  # Temporary partial snapshot.
            self.manager.scan();self.assertFalse(send.called)
            self.turns(('older', 'completed'), ('last', 'completed'), ('fast', 'completed'))
            rows = self.session.state.pop('turns')
            self.session.state['turnHistory'] = {'kind': 'canonical', 'history': {
                'entitiesByKey': {t['turnId']: t for t in rows},
                'islands': [{'entries': [{'value': t['turnId']} for t in rows]}]}}
            self.manager.scan();self.assertEqual(send.call_count, 1)
            self.assertIn('1 次运行', send.call_args.args[2])

    def test_empty_chat_can_notify_first_fast_run_and_ignores_failed_or_stopped(self):
        self.turns()
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        with patch('bridge.features.notifications.channels.publish') as send:
            self.turns(('failed', 'failed'), ('stopped', 'interrupted'))
            self.manager.scan();self.assertFalse(send.called)
            self.session.state['turns'].append({'turnId': 'ok', 'status': 'completed'})
            self.manager.scan();self.assertEqual(send.call_count, 1)
            self.assertIn('1 次运行', send.call_args.args[2])

    def test_completion_retries_after_followup_and_restart_but_opt_out_cancels(self):
        self.turns(('run', 'inProgress'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        self.turns(('run', 'completed'))
        with patch('bridge.features.notifications.channels.publish', side_effect=OSError('offline')) as send:
            self.manager.scan();self.manager.scan();self.assertEqual(send.call_count, 1)
        self.turns(('next', 'inProgress'))  # The finished turn has left the live page.
        other = Notifications(self.source, self.directory)
        for record in other.ledger.values(): record['next'] = 0
        with patch('bridge.features.notifications.channels.publish') as send:
            other.scan();self.assertEqual(send.call_count, 1)
            save_settings(self.directory, {'includeTitle': True})
            self.turns(('next', 'completed'))
            other.scan();self.assertEqual(send.call_count, 2)
            self.assertIn('Private project', send.call_args.args[2])
        other.close()
        self.manager = Notifications(self.source, self.directory)
        self.turns(('new', 'inProgress'))
        with patch('bridge.features.notifications.channels.publish'):
            self.manager.scan()
        self.turns(('new', 'completed'))
        with patch('bridge.features.notifications.channels.publish', side_effect=OSError('offline')):
            self.manager.scan()
        self.manager.watch(self.thread, 'remote', notify_on_completion=False)
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan();self.assertFalse(send.called)

    def test_completion_offline_baseline_and_reconnect(self):
        self.session.connected = False
        self.turns(('old', 'completed'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan()
            self.session.connected = True
            self.manager.scan();self.assertFalse(send.called)
            self.turns(('old', 'completed'), ('new', 'inProgress'))
            self.manager.scan()
            self.session.connected = False
            self.turns(('old', 'completed'), ('new', 'completed'))
            self.manager.scan();self.assertFalse(send.called)
            self.session.connected = True
            self.manager.scan();self.assertEqual(send.call_count, 1)

    def test_completion_does_not_replace_pending_approvals_or_replay_after_global_disable(self):
        self.turns(('approval', 'inProgress'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        self.turns(('approval', 'completed'))
        self.session.state['requests'] = [{'id': 'approval', 'method': 'item/tool/requestUserInput', 'params': {}}]
        with patch('bridge.features.notifications.channels.publish') as send:
            self.manager.scan()
            self.assertEqual([c.args[1] for c in send.call_args_list], ['Codex 需要你的确认', 'Codex 运行已完成'])
            save_settings(self.directory, {'enabled': False})
            self.manager.scan()
            self.turns(('approval', 'completed'), ('while-off', 'completed'))
            save_settings(self.directory, {'enabled': True})
            self.manager.scan();self.assertEqual(send.call_count, 2)

    def test_config_token_preservation_and_destination_change(self):
        save_settings(self.directory, {'token': ''})
        self.assertEqual(settings(self.directory)['token'], 'secret-token')
        save_settings(self.directory, {'server': 'https://new.example.com', 'token': ''})
        self.assertEqual(settings(self.directory)['token'], '')
        for change in [{'server': 'https://user:pass@example.com'}, {'topic': '../bad'}, {'token': 'x\nInjected'}, {'enabled': 'yes'}]:
            with self.assertRaises(ValueError): save_settings(self.directory, change)
        with self.assertRaises(KeyError): self.manager.watch(self.thread, 'unknown', True)

    def test_bark_only_subscription_sends_requests_and_opt_in_completion(self):
        self.manager.watch(self.thread, 'remote', False)
        save_settings(self.directory, {'enabled': False, 'topic': '', 'barkEnabled': True, 'barkKey': 'device-key'})
        self.turns(('current', 'inProgress'))
        result = self.manager.watch(self.thread, 'remote', True, True)
        self.assertTrue(result['available'])
        with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_bark') as bark:
            self.turns(('current', 'completed'))
            self.session.state['requests'] = [{'id': 'question', 'method': 'item/tool/requestUserInput', 'params': {}}]
            self.manager.scan();self.manager.scan()
            self.assertFalse(ntfy.called)
            self.assertEqual([c.args[1] for c in bark.call_args_list], ['Codex 需要你的确认', 'Codex 运行已完成'])
            self.assertNotIn('Private project', bark.call_args.args[2])
            self.assertTrue(bark.call_args.args[3].endswith('~remote'))

    def test_pushplus_only_subscription_sends_requests_and_opt_in_completion(self):
        self.manager.watch(self.thread, 'remote', False)
        save_settings(self.directory, {'enabled': False, 'topic': '', 'pushplusEnabled': True, 'pushplusToken': 'pushplus-token'})
        self.turns(('current', 'inProgress'))
        result = self.manager.watch(self.thread, 'remote', True, True)
        self.assertTrue(result['available'])
        with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_pushplus') as bark:
            self.turns(('current', 'completed'))
            self.session.state['requests'] = [{'id': 'question', 'method': 'item/tool/requestUserInput', 'params': {}}]
            self.manager.scan();self.manager.scan()
            self.assertFalse(ntfy.called)
            self.assertEqual([c.args[1] for c in bark.call_args_list], ['Codex 需要你的确认', 'Codex 运行已完成'])
            self.assertNotIn('Private project', bark.call_args.args[2])
            self.assertTrue(bark.call_args.args[3].endswith('~remote'))

    def test_channels_retry_independently_after_restart(self):
        save_settings(self.directory, {'barkEnabled': True, 'barkKey': 'device-key'})
        for failing in ('ntfy', 'bark'):
            with self.subTest(failing=failing):
                self.turns((failing, 'inProgress'))
                self.manager.watch(self.thread, 'remote', notify_on_completion=False)
                self.manager.watch(self.thread, 'remote', notify_on_completion=True)
                self.turns((failing, 'completed'))
                with patch('bridge.features.notifications.channels.publish', side_effect=OSError('secret-token') if failing == 'ntfy' else None) as ntfy, \
                        patch('bridge.features.notifications.channels.publish_bark', side_effect=OSError('device-key') if failing == 'bark' else None) as bark:
                    self.manager.scan();self.manager.scan()
                    self.assertEqual((ntfy.call_count, bark.call_count), (1, 1))
                status = read_json(self.directory/'notification-status.json', {})
                self.assertTrue(status[failing]['error'])
                self.assertFalse(status['ntfy' if failing == 'bark' else 'bark']['error'])
                self.assertNotIn('device-key', json.dumps(status))
                self.manager.close()
                self.manager = Notifications(self.source, self.directory)
                for record in self.manager.ledger.values(): record['next'] = 0
                self.turns(('next-'+failing, 'inProgress'))
                with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_bark') as bark:
                    self.manager.scan();self.manager.scan()
                    self.assertEqual((ntfy.call_count, bark.call_count), (1, 0) if failing == 'ntfy' else (0, 1))

    def test_new_bark_destination_does_not_replay_completed_history(self):
        self.turns(('old', 'completed'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        save_settings(self.directory, {'barkEnabled': True, 'barkKey': 'first-device'})
        with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_bark') as bark:
            self.manager.scan();self.assertFalse(bark.called)
            self.turns(('old', 'completed'), ('new', 'completed'))
            self.manager.scan()
            self.assertEqual((ntfy.call_count, bark.call_count), (1, 1))
            save_settings(self.directory, {'barkKey': 'second-device'})
            self.manager.scan();self.assertEqual(bark.call_count, 1)
            self.turns(('old', 'completed'), ('new', 'completed'), ('running', 'inProgress'))
            self.manager.scan()
            self.turns(('old', 'completed'), ('new', 'completed'), ('running', 'completed'))
            self.manager.scan();self.assertEqual((ntfy.call_count, bark.call_count), (2, 2))

    def test_request_dedup_is_per_channel_destination_and_host(self):
        save_settings(self.directory, {'barkEnabled': True, 'barkKey': 'first-device'})
        with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_bark') as bark:
            self.manager.scan();self.manager.scan()
            self.assertEqual((ntfy.call_count, bark.call_count), (1, 1))
            save_settings(self.directory, {'token': 'new-token', 'barkKey': 'second-device'})
            self.manager.scan();self.assertEqual((ntfy.call_count, bark.call_count), (1, 2))
            save_settings(self.directory, {'topic': 'second-topic'})
            self.manager.scan();self.assertEqual((ntfy.call_count, bark.call_count), (2, 2))
            self.manager.watch(self.thread, 'local', True)
            self.manager.scan();self.assertEqual((ntfy.call_count, bark.call_count), (3, 3))
        self.assertNotIn('second-device', (self.directory/'notification-delivery.json').read_text())

    def test_disabling_bark_cancels_completion_retry_without_disabling_ntfy(self):
        save_settings(self.directory, {'barkEnabled': True, 'barkKey': 'device-key'})
        self.turns(('run', 'inProgress'))
        self.manager.watch(self.thread, 'remote', notify_on_completion=True)
        self.turns(('run', 'completed'))
        with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_bark', side_effect=OSError('offline')) as bark:
            self.manager.scan()
            save_settings(self.directory, {'barkEnabled': False})
            self.manager.scan()
            self.assertTrue(self.session.watched)
            save_settings(self.directory, {'barkEnabled': True})
            for record in self.manager.ledger.values(): record['next'] = 0
            self.manager.scan()
            self.assertEqual((ntfy.call_count, bark.call_count), (1, 1))

    def test_legacy_ntfy_delivery_and_pending_completion_are_migrated_once(self):
        row = {'id': self.thread, 'host': 'remote'}
        write_json(self.directory/'notification-delivery.json', {
            self.manager._delivery_key(row, 'approval'): {'delivered': True, 'time': 1},
            self.manager._delivery_key(row, 'run', completion=True): {'delivered': False, 'next': 0, 'time': 1}})
        write_json(self.directory/'notification-watches.json', [{**row, 'notifyOnCompletion': True}])
        write_json(self.directory/'notification-completions.json', {json.dumps(['remote', self.thread]):
            {'anchor': 'run', 'running': [], 'pending': ['run']}})
        save_settings(self.directory, {'barkEnabled': True, 'barkKey': 'device-key'})
        self.manager.close()
        self.manager = Notifications(self.source, self.directory)
        with patch('bridge.features.notifications.channels.publish') as ntfy, patch('bridge.features.notifications.channels.publish_bark') as bark:
            self.manager.scan()
            self.assertEqual(ntfy.call_count, 1)
            self.assertEqual(ntfy.call_args.args[1], 'Codex 运行已完成')
            self.assertEqual(bark.call_count, 1)
            self.assertEqual(bark.call_args.args[1], 'Codex 需要你的确认')
            self.manager.close()
            self.manager = Notifications(self.source, self.directory)
            self.manager.scan()
            self.assertEqual((ntfy.call_count, bark.call_count), (1, 1))

    def test_bark_key_preservation_validation_and_server_change(self):
        save_settings(self.directory, {'barkEnabled': True, 'barkKey': 'private-key'})
        save_settings(self.directory, {'barkKey': ''})
        self.assertEqual(settings(self.directory)['barkKey'], 'private-key')
        for change in ({'barkEnabled': 'yes'}, {'barkKey': 'https://api.day.app/key'}, {'barkKey': 'a\nb'},
                       {'barkKey': 1}, {'barkServer': 'https://user:pass@example.com'},
                       {'barkServer': 'https://new.example.com', 'barkKey': ''}):
            with self.assertRaises(ValueError): save_settings(self.directory, change)
            self.assertEqual(settings(self.directory)['barkKey'], 'private-key')
        save_settings(self.directory, {'barkEnabled': False, 'barkServer': 'https://new.example.com', 'barkKey': ''})
        self.assertEqual(settings(self.directory)['barkKey'], '')
        save_settings(self.directory, {'barkKey': 'new-key'})
        save_settings(self.directory, {'barkKey': '', 'clearBarkKey': True})
        self.assertEqual(settings(self.directory)['barkKey'], '')

    def test_bark_http_contract_and_rejection_do_not_leak_key_or_follow_redirects(self):
        captured, replies = [], [(200, b'{"code":200}'), (200, b'{"code":400,"message":"private-key"}'),
                                (200, b'not json'), (200, b'[]'), (200, b'{}'), (400, b'private-key'), (302, b'')]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                code, body = replies.pop(0)
                self.send_response(code)
                if code == 302: self.send_header('Location', '/redirected')
                self.end_headers();self.wfile.write(body)
            def do_GET(self):
                captured.append(('unexpected redirect', {}));self.send_response(200);self.end_headers()
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = {'barkServer': 'http://127.0.0.1:'+str(server.server_port)+'/bark/', 'barkKey': 'private-key'}
        try:
            publish_bark(config, '待确认', '请查看聊天', 'https://example.com/#thread~remote')
            self.assertEqual(captured[0], ('/bark/push', {'device_key': 'private-key', 'title': '待确认',
                'body': '请查看聊天', 'group': 'Codex Mobile Bridge', 'url': 'https://example.com/#thread~remote'}))
            for _ in range(6):
                with self.assertRaises(RuntimeError) as error: publish_bark(config, 'test', 'test')
                self.assertNotIn('private-key', str(error.exception))
            self.assertEqual([p for p, _ in captured], ['/bark/push'] * 7)
        finally:
            server.shutdown();server.server_close()

    def test_real_http_payload_and_authorization(self):
        captured = []
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_POST(self):
                captured.append((json.loads(self.rfile.read(int(self.headers['Content-Length']))), self.headers.get('Authorization')))
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers();self.wfile.write(b'{}')
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            publish({'server': 'http://127.0.0.1:'+str(server.server_port), 'topic': 'topic', 'token': 'test-token'}, '待确认', 'Open chat', 'https://example.com/#thread')
            self.assertEqual(captured[0][1], 'Bearer test-token')
            self.assertEqual(captured[0][0]['click'], 'https://example.com/#thread')
            self.assertNotIn('token', captured[0][0])
        finally:
            server.shutdown();server.server_close()
