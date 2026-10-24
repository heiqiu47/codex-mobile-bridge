"""Focused WSL native CLI controls without a distro, model call, or daemon start."""
import copy
import hashlib
import unittest
import uuid
from unittest.mock import patch

from bridge.clients.codex.ipc import IPCError
from tests import test_wsl_entries as fixtures


class WslControlsTests(unittest.TestCase):
    setUp = fixtures.WslSessionTests.setUp
    def make_entry(self):
        entry = fixtures.WslSessionTests.make_entry(self)
        entry.store.history = lambda identifier, **kwargs: {'id': identifier, 'turns': []}
        return entry

    def skills(self):
        original = self.entry.server.request
        def request(method, params):
            if method == 'skills/list':
                self.entry.server.calls.append((method, copy.deepcopy(params)))
                return {'data': [{'cwd': '/other', 'skills': [{'name': 'wrong', 'path': '/wrong'}]},
                    {'cwd': '/home/fixture/project', 'skills': [
                        {'name': 'fixture', 'path': '/home/fixture/.agents/skills/fixture/SKILL.md'},
                        {'name': 'disabled', 'path': '/disabled', 'enabled': False}]}]}
            return original(method, params)
        self.entry.server.request = request
        return hashlib.sha256(b'/home/fixture/.agents/skills/fixture/SKILL.md').hexdigest()

    def test_skills_use_selected_cwd_and_only_trusted_native_paths(self):
        skill = self.skills()
        rows = self.entry.catalog(self.identifier, kind='skills')['skills']
        self.assertEqual([r['id'] for r in rows], [skill])
        self.entry.send(self.identifier, 'fixture', str(uuid.uuid4()), skills=[skill], work_mode='plan')
        sent = [p for m, p in self.entry.server.calls if m == 'turn/start'][0]
        self.assertEqual(sent['input'][1], {'type': 'skill', 'name': 'fixture', 'path': rows[0]['path']})
        self.assertEqual(sent['collaborationMode']['mode'], 'plan')
        self.assertFalse(any(m in ('thread/start', 'config/batchWrite') for m, _ in self.entry.server.calls))

    def test_unknown_skill_path_rejected_before_send_receipt(self):
        self.skills()
        with self.assertRaises(ValueError):
            self.entry.send(self.identifier, 'fixture', str(uuid.uuid4()), skills=['/phone/supplied/path'])
        self.assertFalse(self.entry.receipts_path.exists())
        self.assertFalse(any(m == 'turn/start' for m, _ in self.entry.server.calls))

    def test_queue_waits_until_idle_and_sends_once(self):
        self.entry.server.thread['status'] = {'type': 'active'}
        submission = str(uuid.uuid4())
        self.assertEqual(self.entry.send(self.identifier, 'queued', submission, mode='queue')['status'], 'queued')
        self.entry._dispatch_queued(self.identifier)
        self.assertFalse(any(m == 'turn/start' for m, _ in self.entry.server.calls))
        self.entry.server.thread['status'] = {'type': 'idle'}
        self.entry._dispatch_queued(self.identifier)
        self.entry._dispatch_queued(self.identifier)
        self.assertEqual(sum(m == 'turn/start' for m, _ in self.entry.server.calls), 1)
        self.assertFalse(self.entry._queue(self.identifier))
        self.assertEqual(self.entry.send(self.identifier, 'queued', submission, mode='queue')['status'], 'accepted')

    def test_queue_unknown_write_is_never_replayed_after_restart(self):
        submission = str(uuid.uuid4())
        self.entry.send(self.identifier, 'queued', submission, mode='queue')
        self.entry.server.fail_send = True
        self.entry._dispatch_queued(self.identifier)
        self.entry._dispatch_queued(self.identifier)
        restarted = self.make_entry()
        self.addCleanup(restarted.close)
        restarted._dispatch_queued(self.identifier)
        self.assertEqual(restarted.send(self.identifier, 'queued', submission, mode='queue')['status'], 'unknown')
        self.assertFalse(any(m == 'turn/start' for m, _ in restarted.server.calls))
        self.assertEqual(sum(m == 'turn/start' for m, _ in self.entry.server.calls), 1)

    def test_cancel_and_target_mismatch_prevent_queue_dispatch(self):
        submission = str(uuid.uuid4())
        self.entry.send(self.identifier, 'queued', submission, mode='queue')
        self.entry.server.thread['cwd'] = '/different'
        self.entry.store.get = lambda identifier: {'id': identifier, 'cwd': '/different', 'model_provider': 'magpie'}
        self.entry._dispatch_queued(self.identifier)
        self.assertFalse(any(m == 'turn/start' for m, _ in self.entry.server.calls))
        self.assertEqual(self.entry.cancel_queued(self.identifier, submission)['status'], 'cancelled')
        self.assertFalse(self.entry._queue(self.identifier))

    def test_permission_policy_uses_native_target_and_actual_settings_event(self):
        original = self.entry.server.request
        def request(method, params):
            if method == 'configRequirements/read':
                return {'requirements': {'allowedApprovalsReviewers': ['user', 'guardian_subagent']}}
            if method == 'permissionProfile/list':
                return {'data': [{'id': ':workspace', 'allowed': True}, {'id': ':danger-full-access', 'allowed': True}]}
            if method == 'experimentalFeature/list':
                return {'data': [{'name': 'guardian_approval', 'enabled': True}]}
            if method == 'thread/settings/update':
                self.entry.server.calls.append((method, copy.deepcopy(params)))
                self.entry._event({'method': 'thread/settings/updated', 'params': {'threadId': self.identifier,
                    'threadSettings': {'approvalPolicy': 'on-request', 'approvalsReviewer': params['approvalsReviewer'],
                                       'sandboxPolicy': {'type': 'workspaceWrite'}}}}, self.entry.generation)
                return {}
            return original(method, params)
        self.entry.server.request = request
        result = self.entry.permissions(self.identifier, 'auto-review', expected_runtime='cli')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['permissionMode'], 'auto-review')
        settings = [p for m, p in self.entry.server.calls if m == 'thread/settings/update'][0]
        self.assertEqual(settings['approvalsReviewer'], 'guardian_subagent')
        self.assertFalse(any(m == 'config/batchWrite' for m, _ in self.entry.server.calls))

    def test_permission_inspection_does_not_resume_and_unknown_policy_blocks_write(self):
        with patch.object(self.entry.server, 'request', wraps=self.entry.server.request):
            options = self.entry.linux_permission_options(self.identifier)
        self.assertTrue(all(not row['available'] for row in options['options']))
        with self.assertRaises(ValueError):
            self.entry.permissions(self.identifier, 'ask')
        self.assertFalse(any(m in ('thread/resume', 'thread/settings/update') for m, _ in self.entry.server.calls))
