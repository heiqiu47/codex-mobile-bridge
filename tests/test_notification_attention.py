"""Native terminal errors become attention alerts without replaying a task."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bridge.app.service import LiveSession
from bridge.clients.claude.model import turns as claude_turns
from bridge.clients.deepseek.adapter import turns as dsh_turns
from bridge.features.notifications.channels import Notifications, save_settings
from bridge.features.notifications.push import payload

ROOT = Path(__file__).resolve().parents[1]
CAPACITY = 'Selected model is at capacity. Please try a different model.'


class AttentionNotifications(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.session = LiveSession('fixture')
        self.session.connected = True
        self.session.state = {'turns': [], 'requests': [], 'title': 'private title'}
        self.source = Mock()
        self.source.notification_candidates.return_value = [{'id': 'fixture', 'host': 'local'}]
        self.source.notification_updates.return_value = []
        self.source.for_host.return_value = self.source
        self.source.notification_session.return_value = self.session
        self.source.release_notification_session.return_value = False
        self.manager = Notifications(self.source, self.directory)
        self.addCleanup(self.manager.close)
        save_settings(self.directory, {'mobileEnabled': True, 'webhookEnabled': True,
                                      'webhookUrl': 'https://receiver.invalid/events'})
        self.row = {'id': 'fixture', 'host': 'local'}

    def scan(self):
        with patch('bridge.features.notifications.channels.publish_webhook') as send:
            self.manager.scan()
            return self.manager.mobile.read()['events'], send

    def fail(self, identifier='turn-1', **extra):
        self.session.state['turns'] = [{'turnId': identifier, 'status': 'failed',
                                        'error': {'message': CAPACITY}, **extra}]

    def test_native_capacity_failure_reaches_both_channels_once_without_content_leak(self):
        self.scan()
        self.fail()
        events, send = self.scan()
        self.assertEqual([e['kind'] for e in events], ['attention'])
        self.assertEqual(events[0]['title'], 'Codex 需要你处理')
        self.assertEqual(send.call_args.kwargs['event'], 'task.attention')
        self.assertNotIn(CAPACITY, str(events))
        self.assertNotIn('private title', str(events))
        self.assertEqual(send.call_args.kwargs['host'], 'local')
        events, send = self.scan()
        self.assertEqual(len(events), 1)
        send.assert_not_called()
        self.source.session.assert_not_called()
        reopened = Notifications(self.source, self.directory)
        self.addCleanup(reopened.close)
        with patch('bridge.features.notifications.channels.publish_webhook') as send:
            reopened.scan()
        send.assert_not_called()
        self.assertEqual(len(reopened.mobile.read()['events']), 1)

    def test_historical_failure_is_baselined_but_resumed_same_turn_can_fail_again(self):
        self.fail()
        self.assertEqual(self.scan()[0], [])
        self.session.state['turns'][0]['status'] = 'inProgress'
        self.scan()
        self.fail()
        self.assertEqual(len(self.scan()[0]), 1)
        self.session.state['turns'][0]['status'] = 'inProgress'
        self.scan()
        self.fail()
        self.assertEqual(len(self.scan()[0]), 2)

    def test_automatic_retry_is_silent_until_explicit_terminal_failure(self):
        self.scan()
        self.fail(willRetry=True)
        self.assertEqual(self.scan()[0], [])
        self.fail(willRetry=False)
        self.assertEqual(len(self.scan()[0]), 1)

    def test_request_policy_off_blocks_failure_even_with_completion_on(self):
        self.manager.defaults({'requests': False, 'completion': True})
        self.scan()
        self.fail()
        events, send = self.scan()
        self.assertEqual(events, [])
        send.assert_not_called()
        self.manager.defaults({'requests': True, 'completion': True})
        self.assertEqual(self.scan()[0], [])

    def test_recovery_cancels_third_party_retry_and_restart_does_not_repeat(self):
        self.scan()
        self.fail()
        with patch('bridge.features.notifications.channels.publish_webhook', side_effect=OSError('offline')):
            self.manager.scan()
        self.session.state['turns'][0]['status'] = 'inProgress'
        for entry in self.manager.ledger.values():
            entry['next'] = 0
        _, send = self.scan()
        send.assert_not_called()
        replacement = Notifications(self.source, self.directory)
        self.addCleanup(replacement.close)
        with patch('bridge.features.notifications.channels.publish_webhook') as send:
            replacement.scan()
        send.assert_not_called()

    def test_pending_retry_is_cancelled_when_request_policy_disabled(self):
        self.scan()
        self.fail()
        self.manager.scan(deliver=False)
        self.manager.defaults({'requests': False, 'completion': False})
        with patch('bridge.features.notifications.channels.publish_webhook') as send:
            self.manager.deliver_pending()
        send.assert_not_called()
        self.assertEqual(self.manager._mobile_snapshot(0)['events'], [])

    def test_dsh_terminal_reason_and_sequence_survive_page_truncation(self):
        row = {'id': 'native', 'host': 'desktop:deepseek'}
        def records(turn, sequence, reason):
            return dsh_turns([{'event': {'type': 'turn/end', 'seq': sequence,
                                         'data': {'turn': turn, 'reason': {'kind': reason}}}}])
        self.assertEqual(self.manager._attention_pending(row, records(0, 10, 'error'), 'target'), [])
        keys = self.manager._attention_pending(row, records(1, 20, 'blocked'), 'target')
        self.assertEqual(len(keys), 1)
        self.assertEqual(self.manager._attention_pending(row, records(0, 10, 'error'), 'target'), [])
        self.assertEqual(self.manager._attention_pending(row, records(1, 20, 'blocked'), 'target'), keys)
        self.assertEqual(self.manager._attention_pending(row, records(1, 20, 'blocked'), 'new-target'), [])
        # A later native terminal sequence proves another episode even if its
        # intervening turn/start happened between two scanner polls.
        repeated = self.manager._attention_pending(row, records(1, 25, 'blocked'), 'target')
        self.assertEqual(len(repeated), 1)
        self.assertNotEqual(repeated, keys)
        for reason in ('forked', 'aborted', 'interrupted', 'completed'):
            self.assertEqual(self.manager._attention_pending(row, records(2, 30, reason), 'target'), [])

    def test_failed_inbox_write_retries_after_subscription_becomes_dormant(self):
        self.scan()
        self.fail()
        self.source.release_notification_session.return_value = True
        with patch.object(self.manager.mobile, 'append', side_effect=OSError('disk unavailable')):
            self.scan()
        self.assertTrue(self.manager.dormant)
        for entry in self.manager.ledger.values():
            entry['next'] = 0
        self.assertEqual(len(self.scan()[0]), 1)

    def test_claude_result_error_is_attention_but_intermediate_assistant_error_is_not(self):
        row = {'id': 'native', 'host': 'desktop:claude'}
        self.manager._attention_pending(row, [], 'target')
        intermediate = [{'type': 'assistant', 'uuid': 'retry', 'isApiErrorMessage': True,
                         'message': {'content': CAPACITY}}]
        self.assertEqual(self.manager._attention_pending(row, claude_turns(intermediate), 'target'), [])
        terminal = {'type': 'result', 'uuid': 'result-1', 'subtype': 'error_during_execution',
                    'is_error': True, 'num_turns': 0, 'errors': [CAPACITY]}
        self.assertEqual(len(self.manager._attention_pending(row, claude_turns([terminal]), 'target')), 1)

    def test_push_payload_preserves_source_and_attention_copy(self):
        event = {'kind': 'attention', 'threadId': 'fixture', 'host': 'desktop:claude', 'sequence': 4}
        for kind in ('fcm', 'apns'):
            body = payload({'kind': kind, 'origin': 'https://test.invalid', 'token': 'fixture', 'sourceIcon': True}, event)
            self.assertIn('运行遇到问题，需要你处理', str(body))
            self.assertIn('desktop:claude', str(body))


if __name__ == '__main__':
    unittest.main()
