import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from bridge.features.sessions.store import SessionStore


ROOT = Path(__file__).resolve().parents[1]


class StoreHistoryPathTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.sessions = self.home / 'sessions'
        self.sessions.mkdir(parents=True)
        self.rollout = self.sessions / 'rollout.jsonl'
        self.rollout.write_text(json.dumps({'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant', 'content': [{'text': 'SAVED_REPLY'}]}}) + '\n')
        self.database = self.home / 'state_5.sqlite'
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE threads(id TEXT, originator TEXT, source TEXT, archived INT, cwd TEXT, rollout_path TEXT)')
            db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?)',
                       ('thread', 'codex-tui', 'vscode', 0, str(self.root), str(self.rollout)))
            db.commit()
        self.store = SessionStore(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def set_rollout(self, path):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE threads SET rollout_path=? WHERE id=?', (str(path), 'thread'))
            db.commit()

    def assert_readable(self):
        self.assertEqual(self.store.discovery_diagnostics('thread')['target']['reason'], 'readable')
        self.assertIn('SAVED_REPLY', str(self.store.history('thread')))

    def assert_outside(self):
        self.assertEqual(self.store.discovery_diagnostics('thread')['target']['reason'], 'rollout_outside_home')
        with self.assertRaises(ValueError):
            self.store.history('thread')

    def test_native_file_change_event_is_preserved_in_saved_history(self):
        records = [
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'native-turn'}},
            {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {
                'type': 'FileChange', 'id': 'patch', 'changes': {
                    '/repo/file.py': {'type': 'update', 'unified_diff': '@@ -1 +1 @@\n-old\n+new'}}}}},
            {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'native-turn'}}]
        self.rollout.write_text('\n'.join(json.dumps(record) for record in records) + '\n')
        from bridge.features.sessions.model import normalize_state
        result = normalize_state(self.store.history('thread'))
        self.assertEqual(result['turns'][0]['fileChanges'][0]['path'], '/repo/file.py')
        self.assertEqual(result['turns'][0]['fileChanges'][0]['added'], 1)
        self.assertEqual(result['turns'][0]['fileChanges'][0]['removed'], 1)
        # Full native patch projection is retained by the existing history read,
        # even when the display window omits the patch item itself.
        saved = self.store.history('thread')
        saved['turns'][0]['items'].append({'type':'agentMessage','id':'last','text':'Done'})
        recent = normalize_state(saved,item_limit=1)
        self.assertEqual(recent['turns'][0]['fileChanges'][0]['path'],'/repo/file.py')


    def test_native_index_partial_turn_cannot_publish_partial_file_totals(self):
        db = self.home / 'thread_history_1.sqlite'
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('CREATE TABLE thread_items(thread_id,turn_id,rollout_ordinal,item_json)')
            conn.execute('CREATE TABLE thread_turns(thread_id,turn_id,status,error_json,started_at,first_user_item_id)')
            conn.execute('CREATE TABLE thread_history_projection_state(thread_id,next_rollout_byte_offset)')
            conn.execute('INSERT INTO thread_history_projection_state VALUES(?,?)',('thread',self.rollout.stat().st_size))
            conn.execute('INSERT INTO thread_turns VALUES(?,?,?,?,?,?)',('thread','t','completed',None,1,'user'))
            for ordinal,path in enumerate(('omitted.py','tail.py')):
                item={'id':str(ordinal),'type':'fileChange','changes':[{'path':path,'diff':'+new'}]}
                conn.execute('INSERT INTO thread_items VALUES(?,?,?,?)',('thread','t',ordinal,json.dumps(item)))
        from bridge.features.sessions.model import normalize_state
        with patch.object(self.store,'_history',side_effect=AssertionError('no full-turn scan')):
            partial=self.store.history('thread',item_limit=1)
            self.assertFalse(partial['turns'][0]['_itemsComplete'])
            self.assertEqual(normalize_state(partial)['turns'][0]['fileChanges'],[])
            complete=self.store.history('thread',item_limit=2)
            self.assertTrue(complete['turns'][0]['_itemsComplete'])
            self.assertEqual(len(normalize_state(complete)['turns'][0]['fileChanges']),2)

    def test_ordinary_path_remains_readable_without_identity_fallback(self):
        with patch.object(Path, 'samefile', side_effect=AssertionError('unneeded fallback')):
            self.assert_readable()

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-length paths')
    def test_windows_extended_path_uses_same_existing_rollout(self):
        extended = Path('\\\\?\\' + str(self.rollout))
        self.set_rollout(extended)
        self.assert_readable()
        # Some Python versions remove the extended prefix during resolve().
        # Retain it here to exercise the identity fallback when it is needed.
        original_resolve = Path.resolve

        def retain_extended(path, *args, **kwargs):
            return path if path == extended else original_resolve(path, *args, **kwargs)

        self.assertNotIn(self.sessions.resolve(), extended.parents)
        with patch.object(Path, 'resolve', retain_extended), \
             patch.object(Path, 'samefile', side_effect=PermissionError('identity unavailable')) as samefile:
            self.assert_outside()
        samefile.assert_called()

    def test_outside_and_prefix_similar_directories_stay_rejected(self):
        outside = self.root / 'outside.jsonl'
        outside.write_bytes(self.rollout.read_bytes())
        near = self.home / 'sessions-other'
        near.mkdir()
        near_rollout = near / 'rollout.jsonl'
        near_rollout.write_bytes(self.rollout.read_bytes())
        for path in (outside, near_rollout):
            with self.subTest(path=path):
                self.set_rollout(path)
                self.assert_outside()
                if os.name == 'nt':
                    self.set_rollout('\\\\?\\' + str(path))
                    self.assert_outside()

    def test_symlink_to_outside_stays_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'rollout.jsonl').write_bytes(self.rollout.read_bytes())
        link = self.sessions / 'link'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Directory symlink unavailable: {exc}')
        self.set_rollout(link / 'rollout.jsonl')
        self.assert_outside()
