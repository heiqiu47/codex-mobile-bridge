"""A native ACK timeout may be confirmed only by persisted, exact submission IDs."""
import copy
import json
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

from bridge.app.service import Bridge
from bridge.features.sessions.store import persisted_submission_ids
from bridge.features.sessions.model import normalize_item
import test_message_management
import test_store_history_paths


class SubmissionRecoveryTests(unittest.TestCase):
    setUp = test_message_management.MessageManagementTests.setUp
    native = test_message_management.MessageManagementTests.native

    def saved(self, identifier=None):
        return {'id': self.thread, 'turns': [{'turnId': 'native-turn', 'status': 'completed', 'items': [
            {'type': 'userMessage', 'clientId': identifier or self.ids[0], 'content': [{'type': 'text', 'text': 'same'}]}]}]}

    def test_only_persisted_exact_uuid_confirms_and_survives_ledger_reload(self):
        b = self.native(); session = b.live[self.thread]; key = self.thread + ':' + self.ids[0]
        b.submissions[key]['status'] = 'unknown'
        session.state = self.saved()  # Prepared live data is not proof, even with a turn ID.
        b._reconcile_submissions(session)
        self.assertEqual(b.submissions[key]['status'], 'unknown')
        for saved in (self.saved(str(uuid.uuid4())), {**self.saved(), 'id': str(uuid.uuid4())},
                      {**self.saved(), 'hostId': 'other'}, self.saved('not-a-uuid')):
            session.history_state = saved; b._reconcile_submissions(session)
            self.assertEqual(b.submissions[key]['status'], 'unknown')
        session.history_state = self.saved(); b._reconcile_submissions(session)
        b.submissions = json.loads(b.ledger_path.read_text())
        self.assertEqual(b.message_management(self.thread, [self.ids[0]])['receipts'][0]['status'], 'accepted')
        b.session.assert_not_called(); b._dispatch.assert_not_called()

    def test_missing_ids_prepared_params_and_non_user_rows_never_confirm(self):
        for item in ({'type': 'agentMessage', 'clientId': self.ids[0]},
                     {'type': 'userMessage', 'content': 'same'},
                     {'type': 'steeringUserMessage', 'status': 'pending', 'clientId': self.ids[0]}):
            saved = self.saved(); saved['turns'][0]['items'] = [item]
            saved['turns'][0]['params'] = {'clientUserMessageId': self.ids[0], 'input': ['same']}
            self.assertEqual(persisted_submission_ids(saved, self.thread), set())
        saved = self.saved(); saved['turns'][0]['turnId'] = None
        self.assertEqual(persisted_submission_ids(saved, self.thread), set())
        self.assertNotIn('requestId', normalize_item({'type': 'userMessage', 'content': []}))

    def test_cancelled_ignored_queued_absent_and_failed_save_remain_unchanged(self):
        b = self.native(); session = b.live[self.thread]; key = self.thread + ':' + self.ids[0]
        session.history_state = self.saved()
        for status in ('cancelled', 'ignored', 'queued', 'accepted'):
            b.submissions[key]['status'] = status
            with patch.object(b, '_save_ledger') as save:
                b._reconcile_submissions(session); save.assert_not_called()
            self.assertEqual(b.submissions[key]['status'], status)
        b.submissions[key]['status'] = 'unknown'
        with patch.object(b, '_save_ledger', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): b._reconcile_submissions(session)
        self.assertEqual(b.submissions[key]['status'], 'unknown')
        del b.submissions[key]; b._reconcile_submissions(session)
        self.assertNotIn(key, b.submissions)

    def test_connected_refresh_is_bounded_coalesced_and_never_replays(self):
        b = self.native(); session = b.live[self.thread]; key = self.thread + ':' + self.ids[0]
        b.store = Mock(); b.closed = threading.Event(); b._saved_history = Mock(return_value={'id': self.thread, 'turns': []})
        b._refresh_saved_async(session, receipts=True); b._saved_history.assert_not_called()
        b.submissions[key]['status'] = 'unknown'
        def refresh_done():
            with session.condition:
                return not session.history_refreshing
        def refresh():
            b._refresh_saved_async(session, receipts=True)
            deadline = time.monotonic() + 2
            while not refresh_done() and time.monotonic() < deadline: time.sleep(.005)
            self.assertTrue(refresh_done())
        refresh()
        for _ in range(10):
            refresh(); b.message_management(self.thread, [self.ids[0]])
        self.assertEqual(b._saved_history.call_count, 1)
        b._saved_history.return_value = self.saved()
        session.state = {'id': self.thread, 'turns': [{'turnId': 'native-turn', 'status': 'completed'}]}
        refresh()
        self.assertEqual(b._saved_history.call_count, 2)
        self.assertEqual(b.submissions[key]['status'], 'accepted')
        self.assertTrue(session.connected)
        b._dispatch.assert_not_called(); b.session.assert_not_called()

    def test_ignore_during_saved_read_is_not_overwritten(self):
        b = self.native(); session = b.live[self.thread]; key = self.thread + ':' + self.ids[0]
        b.store = Mock(); b.closed = threading.Event(); b.submissions[key]['status'] = 'unknown'
        entered, release = threading.Event(), threading.Event()
        def saved(_session):
            entered.set(); release.wait(2); return self.saved()
        b._saved_history = saved
        b._refresh_saved_async(session, receipts=True)
        self.assertTrue(entered.wait(1))
        with b.submit_lock: b.submissions[key]['status'] = 'ignored'
        release.set()
        deadline = time.monotonic() + 2
        while session.history_refreshing and time.monotonic() < deadline: time.sleep(.005)
        self.assertFalse(session.history_refreshing)
        self.assertEqual(b.submissions[key]['status'], 'ignored')

    def test_delayed_persistence_or_read_error_has_only_bounded_backoff_reads(self):
        b = self.native(); session = b.live[self.thread]; key = self.thread + ':' + self.ids[0]
        b.store = Mock(); b.closed = threading.Event(); b.submissions[key]['status'] = 'unknown'
        b._saved_history = Mock(side_effect=[OSError('temporarily unavailable'), {'id': self.thread, 'turns': []}, self.saved()])
        for attempt in range(3):
            session.history_retry_at = 0
            b._refresh_saved_async(session, receipts=True)
            deadline = time.monotonic() + 2
            while session.history_refreshing and time.monotonic() < deadline: time.sleep(.005)
            self.assertFalse(session.history_refreshing)
        self.assertEqual(b.submissions[key]['status'], 'accepted')
        b.submissions[key]['status'] = 'unknown'; session.history_state = None
        session.history_receipt_key = None
        b._saved_history = Mock(return_value={'id': self.thread, 'turns': []})
        for _ in range(8):
            session.history_retry_at = 0
            b._refresh_saved_async(session, receipts=True)
            deadline = time.monotonic() + 2
            while session.history_refreshing and time.monotonic() < deadline: time.sleep(.005)
        self.assertEqual(b._saved_history.call_count, 4)
        self.assertEqual(b.submissions[key]['status'], 'unknown')


class RolloutReceiptTests(unittest.TestCase):
    setUp = test_store_history_paths.StoreHistoryPathTests.setUp
    tearDown = test_store_history_paths.StoreHistoryPathTests.tearDown

    def test_fallback_preserves_native_identity_without_duplicate_display_message(self):
        identifier = str(uuid.uuid4())
        records = [
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'same'}]}},
            {'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': 'thread', 'turn_id': 'turn',
                'item': {'type': 'UserMessage', 'client_id': identifier}}}]
        wrong = copy.deepcopy(records[-1]); wrong['payload']['thread_id'] = 'other'
        wrong['payload']['item']['client_id'] = str(uuid.uuid4()); records.append(wrong)
        self.rollout.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        saved = self.store.history('thread', turn_limit=2, item_limit=40)
        self.assertEqual(persisted_submission_ids(saved, 'thread'), {identifier})
        self.assertEqual(len(saved['turns'][0]['items']), 1)
