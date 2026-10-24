"""WSL goal and passive notification integration; no native model execution."""
import copy
import time
import unittest
import uuid
from unittest.mock import patch

from bridge.clients.codex.ipc import IPCError
from tests import test_wsl_entries as fixtures


class WslFeaturesTests(unittest.TestCase):
    setUp = fixtures.WslSessionTests.setUp
    make_entry = fixtures.WslSessionTests.make_entry

    def goals(self, value=None):
        state = {'goal': value, 'lost': False}
        original = self.entry.server.request
        def request(method, params):
            if method.startswith('thread/goal/'):
                self.entry.server.calls.append((method, copy.deepcopy(params)))
                if method == 'thread/goal/set':
                    state['goal'] = {**(state['goal'] or {'createdAt': 1}),
                                     **{k: v for k, v in params.items() if k != 'threadId'}}
                    if state['lost']:
                        raise IPCError('lost write reply')
                if method == 'thread/goal/clear':
                    state['goal'] = None
                return {'goal': copy.deepcopy(state['goal'])}
            return original(method, params)
        self.entry.server.request = request
        return state

    def test_native_goal_capability_is_read_only_and_generation_scoped(self):
        self.goals({'objective': 'fixture', 'status': 'paused'})
        view = self.entry.view(self.identifier)
        self.assertTrue(view['goalRuntimeAvailable'])
        self.assertTrue(view['access']['canUseGoal'])
        self.assertEqual(view['goal']['objective'], 'fixture')
        self.assertFalse(any(m in ('thread/resume', 'turn/start') for m, _ in self.entry.server.calls))
        self.entry.generation = 'replacement'
        view = self.entry.view(self.identifier, attach=False)
        self.assertFalse(view['goalRuntimeAvailable'])

    def test_unsupported_goal_does_not_remove_other_cli_controls(self):
        view = self.entry.view(self.identifier)
        self.assertFalse(view['capabilities']['goal'])
        for capability in ('permissions', 'skills', 'plan', 'queue', 'terminal', 'notifications'):
            self.assertTrue(view['capabilities'][capability])
        self.assertFalse(view['access']['canUseSideChat'])
        self.assertFalse(view['access']['canEditMessages'])

    def test_create_goal_and_activation_are_each_sent_once(self):
        self.goals()
        request = str(uuid.uuid4())
        first = self.entry.send(self.identifier, 'fixture objective', request, work_mode='goal')
        self.assertEqual(first['status'], 'accepted')
        self.assertEqual(first['activation']['status'], 'accepted')
        self.assertEqual(self.entry.send(self.identifier, 'fixture objective', request, work_mode='goal'), first)
        self.assertEqual(sum(m == 'thread/goal/set' for m, _ in self.entry.server.calls), 1)
        self.assertEqual(sum(m == 'turn/start' for m, _ in self.entry.server.calls), 1)

    def test_lost_goal_write_never_replays_or_activates(self):
        state = self.goals(); state['lost'] = True
        request = str(uuid.uuid4())
        with self.assertRaises(IPCError):
            self.entry.send(self.identifier, 'fixture objective', request, work_mode='goal')
        duplicate = self.entry.send(self.identifier, 'fixture objective', request, work_mode='goal')
        self.assertEqual(duplicate['status'], 'unknown')
        self.assertEqual(sum(m == 'thread/goal/set' for m, _ in self.entry.server.calls), 1)
        self.assertFalse(any(m == 'turn/start' for m, _ in self.entry.server.calls))

    def test_lost_activation_is_not_reported_as_complete_or_replayed(self):
        self.goals(); self.entry.server.fail_send = True
        request = str(uuid.uuid4())
        with self.assertRaises(IPCError):
            self.entry.send(self.identifier, 'fixture objective', request, work_mode='goal')
        duplicate = self.entry.send(self.identifier, 'fixture objective', request, work_mode='goal')
        self.assertEqual(duplicate['status'], 'unknown')
        self.assertEqual(duplicate['activation']['status'], 'unknown')
        self.assertEqual(sum(m == 'turn/start' for m, _ in self.entry.server.calls), 1)

    def test_edit_preserves_native_budget_and_expected_identity(self):
        state = self.goals({'objective': 'old', 'status': 'paused', 'tokenBudget': 1234, 'createdAt': 1})
        self.entry.edit_goal(self.identifier, 'new', str(uuid.uuid4()), expected=dict(state['goal']))
        params = next(p for m, p in self.entry.server.calls if m == 'thread/goal/set')
        self.assertEqual(params['tokenBudget'], 1234)
        self.assertEqual(params['origin'], 'user')
        with self.assertRaisesRegex(ValueError, '变化'):
            self.entry.cancel_goal(self.identifier, str(uuid.uuid4()), expected={'objective': 'old', 'status': 'paused'})
        self.assertFalse(any(m == 'turn/start' for m, _ in self.entry.server.calls))

    def test_goal_rejects_nonplain_payload_before_mutation(self):
        self.goals()
        for options in ({'mode': 'queue'}, {'skills': ['id']}, {'attachments': ['id']}):
            with self.assertRaises(ValueError):
                self.entry.send(self.identifier, 'fixture', str(uuid.uuid4()), work_mode='goal', **options)
        self.assertFalse(self.entry.receipts_path.exists())

    def test_passive_notifications_never_resume_unloaded_thread(self):
        self.entry.server.thread['status'] = {'type': 'notLoaded'}
        session = self.entry.notification_session(self.identifier)
        deadline = session.notification_probe_until
        self.entry.notification_session(self.identifier)
        self.assertEqual(deadline, session.notification_probe_until)
        self.assertFalse(session.connected)
        self.assertFalse(any(m in ('thread/resume', 'turn/start') for m, _ in self.entry.server.calls))
        self.entry.release_notification_session(session)
        self.assertFalse(session.watched)

    def test_notification_changes_keep_boundary_and_original_host(self):
        self.entry.store.notification_changes = lambda since: [{'id': self.identifier, 'changed_at': 4}]
        self.assertEqual(self.entry.notification_candidates(), [{'id': self.identifier, 'host': self.row['id']}])
        self.assertEqual(self.entry.notification_candidates(), [])
        session = self.entry.session(self.identifier, attach=False)
        self.entry._event({'method': 'thread/status/changed', 'params': {'threadId': self.identifier,
                          'status': {'type': 'active'}}}, self.entry.generation)
        self.assertEqual(self.entry.notification_updates(), [{'id': self.identifier, 'host': self.row['id']}])
        self.assertEqual(self.entry.notification_updates(), [])
