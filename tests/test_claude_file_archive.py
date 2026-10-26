import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from bridge.clients.claude import file_archive as archive
from bridge.clients.claude.cli_session import ClaudeCli, ResumePreflightBlocked


class FileArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'config'
        self.project = self.directory/'projects'/'synthetic-project'
        self.project.mkdir(parents=True)
        self.native = str(uuid.uuid4())
        self.path = self.project/(self.native+'.jsonl')
        self.raw = (json.dumps({'type':'user','cwd':str(self.project),
                    'sessionId':self.native,'permissionMode':'default',
                    'message':{'role':'user','content':'Synthetic only'}})+'\r\n').encode()
        self.path.write_bytes(self.raw)
        self.sidecar = self.project/self.native/'tool-results'/'result.txt'
        self.sidecar.parent.mkdir(parents=True)
        self.sidecar.write_bytes(b'original\x00\r\n')
        self.shared = self.project/'memory'/'shared.md'
        self.shared.parent.mkdir()
        self.shared.write_bytes(b'shared')

    def archive(self):
        return archive.change(self.directory,self.path,self.native,True)

    def stored(self):
        return self.directory/'bridge-archives'/self.native/(self.native+'.jsonl')

    def test_roundtrip_raw_bytes_identity_and_private_snapshot(self):
        self.assertEqual(self.archive(),{'archived':True})
        self.assertFalse(self.path.exists())
        self.assertEqual(archive.archive_paths(self.directory),[self.stored()])
        self.assertEqual(self.sidecar.read_bytes(),b'original\x00\r\n')
        self.sidecar.unlink()  # Simulate native retention of orphaned sidecar.
        self.assertEqual(archive.change(self.directory,self.stored(),self.native,False),{'archived':False})
        self.assertEqual(self.path.read_bytes(),self.raw)
        self.assertEqual(self.sidecar.read_bytes(),b'original\x00\r\n')
        self.assertEqual(self.shared.read_bytes(),b'shared')
        self.assertEqual(archive.archive_paths(self.directory),[])

    def test_restore_conflicting_original_never_overwrites(self):
        self.archive();self.path.write_bytes(b'new native session')
        with self.assertRaises(ValueError):archive.change(self.directory,self.stored(),self.native,False)
        self.assertEqual(self.path.read_bytes(),b'new native session')
        self.assertEqual(self.stored().read_bytes(),self.raw)

    def test_restore_conflicting_sidecar_never_overwrites(self):
        self.archive();self.sidecar.write_bytes(b'changed')
        with self.assertRaises(ValueError):archive.change(self.directory,self.stored(),self.native,False)
        self.assertEqual(self.sidecar.read_bytes(),b'changed')
        self.assertFalse(self.path.exists())

    def test_restored_transcript_can_grow_and_archive_again(self):
        self.archive();archive.change(self.directory,self.stored(),self.native,False)
        self.path.write_bytes(self.raw+b'\n')
        self.sidecar.write_bytes(b'new result')
        self.assertFalse(archive.state(self.directory,self.path,self.native)['archived'])
        self.archive();archive.change(self.directory,self.stored(),self.native,False)
        self.assertEqual(self.path.read_bytes(),self.raw+b'\n')
        self.assertEqual(self.sidecar.read_bytes(),b'new result')

    def test_shared_hardlink_refused(self):
        os.link(self.path,self.project/'other.jsonl')
        with self.assertRaises(ValueError):self.archive()
        self.assertEqual(self.path.read_bytes(),self.raw)

    def test_symlink_sidecar_refused(self):
        try:(self.sidecar.parent/'link').symlink_to(self.shared)
        except OSError as exc:self.skipTest('Native symlink creation unavailable: '+str(exc))
        with self.assertRaises(ValueError):self.archive()
        self.assertTrue(self.path.exists())

    def test_tampered_backup_refused(self):
        self.archive()
        backup=self.stored().parent/'sidecars'/'0'/'tool-results'/'result.txt'
        backup.write_bytes(b'tampered')
        self.sidecar.unlink()
        with self.assertRaises(ValueError):archive.change(self.directory,self.stored(),self.native,False)
        self.assertFalse(self.sidecar.exists())

    def test_interrupted_journal_no_auto_replay(self):
        self.archive();manifest=self.stored().parent/'manifest.json'
        value=json.loads(manifest.read_text());value['phase']='preparing';manifest.write_text(json.dumps(value))
        with self.assertRaises(ValueError):archive.state(self.directory,self.stored(),self.native)
        self.assertTrue(self.stored().exists())

    def test_failed_source_unlink_rolls_back_without_overwrite(self):
        original=Path.unlink
        def fail(path,*args,**kwargs):
            if path==self.path:raise OSError('synthetic unlink failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail),self.assertRaises(OSError):self.archive()
        self.assertTrue(self.path.exists());self.assertFalse(self.stored().exists())
        self.assertFalse(archive.state(self.directory,self.path,self.native)['archived'])

    def test_unknown_runtime_disabled_without_launch(self):
        with patch.object(archive.subprocess,'run') as run:
            self.assertFalse(archive.supported('/synthetic/claude',{}))
        run.assert_not_called()

    def test_foreign_live_writer_refused_before_file_mutation(self):
        from bridge.clients.errors import BridgeUnavailable
        profile={'directory':self.directory,'origin':'synthetic','binary':'/synthetic/claude'}
        cli=ClaudeCli(Path(self.temp.name)/'uploads',profile_resolver=lambda:profile)
        sid=cli.listing()['sessions'][0]['id']
        with patch.object(archive,'supported',return_value=True),patch.object(archive,'recorded_writer',return_value=True),patch('bridge.clients.claude.cli_session.assert_session_closed',side_effect=BridgeUnavailable('live writer')):
            with self.assertRaises(BridgeUnavailable):cli.call('archive',sid,{'archived':True})
        self.assertTrue(self.path.exists())
        self.assertFalse(self.stored().exists())

    def test_missing_writer_registry_is_unknown(self):
        self.assertFalse(archive.recorded_writer(self.directory,self.native))

    def test_local_cli_archive_routes_identity_and_refuses_resume(self):
        profile={'directory':self.directory,'origin':'synthetic','binary':'/synthetic/claude'}
        cli=ClaudeCli(Path(self.temp.name)/'uploads',profile_resolver=lambda:profile)
        listing=cli.listing();sid=listing['sessions'][0]['id']
        self.assertFalse(cli.call('archive-state',sid,{})['archiveSafe'])
        with patch.object(archive,'supported',return_value=True),patch.object(archive,'recorded_writer',return_value=True),patch('bridge.clients.claude.cli_session.assert_session_closed') as guard:
            self.assertTrue(cli.call('archive-state',sid,{})['archiveSafe'])
            cli.call('archive',sid,{'archived':True})
            self.assertGreaterEqual(guard.call_count,2)
            row=cli.listing()['sessions'][0]
            self.assertEqual(row['id'],sid);self.assertEqual(row['nativeId'],self.native)
            self.assertTrue(row['archived'])
            with self.assertRaises(ResumePreflightBlocked):cli.call('resume',sid,{})
            cli.call('archive',sid,{'archived':False})
        self.assertEqual(self.path.read_bytes(),self.raw)
