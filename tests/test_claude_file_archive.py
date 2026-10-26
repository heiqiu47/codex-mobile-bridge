import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bridge.clients.claude import file_archive as archive
from bridge.clients.claude.cli_session import ClaudeCli, ResumePreflightBlocked


class FileArchiveTests(unittest.TestCase):
    def setUp(self):
        domain = patch.object(archive, '_domain', return_value='synthetic-domain')
        domain.start();self.addCleanup(domain.stop)
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

    def test_copied_bundle_cannot_restore_into_another_profile(self):
        import shutil
        self.archive()
        other=Path(self.temp.name)/'other-profile'
        (other/'projects'/self.project.name).mkdir(parents=True)
        target=other/'bridge-archives'/self.native
        shutil.copytree(self.stored().parent,target)
        with self.assertRaises(ValueError):archive.change(other,target/self.stored().name,self.native,False)
        self.assertFalse((other/'projects'/self.project.name/self.path.name).exists())

    def test_replaced_profile_inode_refused(self):
        import shutil
        self.archive();old=self.directory.with_name('old-config')
        self.directory.rename(old);shutil.copytree(old,self.directory)
        with self.assertRaises(ValueError):archive.state(self.directory,self.stored(),self.native)

    def test_foreign_host_domain_refused(self):
        self.archive()
        with patch.object(archive,'_domain',return_value='other-host-domain'):
            with self.assertRaises(ValueError):archive.state(self.directory,self.stored(),self.native)

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

    def test_incomplete_archive_visible_without_breaking_other_rows(self):
        self.archive();manifest=self.stored().parent/'manifest.json'
        value=json.loads(manifest.read_text());value['phase']='preparing';manifest.write_text(json.dumps(value))
        other=self.project/(str(uuid.uuid4())+'.jsonl');other.write_bytes(self.raw)
        profile={'directory':self.directory,'origin':'synthetic','binary':'/synthetic/claude'}
        cli=ClaudeCli(Path(self.temp.name)/'uploads',profile_resolver=lambda:profile)
        listing=cli.listing()
        self.assertEqual(len(listing['sessions']),2)
        bad=next(row for row in listing['sessions'] if row.get('archiveIncomplete'))
        self.assertEqual(bad['title'],'Claude Code 归档待核对')
        self.assertFalse(bad['runtimeKnown']);self.assertFalse(bad['capabilities']['archive'])
        self.assertFalse(listing['complete'])

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
        with patch.object(archive,'VERIFIED_PICKER_VERSIONS',{}),patch.object(archive.subprocess,'run') as run:
            self.assertFalse(archive.supported('/synthetic/claude',{}))
        run.assert_not_called()

    def test_foreign_live_writer_refused_before_file_mutation(self):
        from bridge.clients.errors import BridgeUnavailable
        profile={'directory':self.directory,'origin':'synthetic','binary':'/synthetic/claude'}
        cli=ClaudeCli(Path(self.temp.name)/'uploads',profile_resolver=lambda:profile)
        sid=cli.listing()['sessions'][0]['id']
        with patch.object(archive,'supported',return_value=True),patch.object(archive,'assert_no_cli'),patch('bridge.clients.claude.cli_session.assert_session_closed',side_effect=BridgeUnavailable('live writer')):
            with self.assertRaises(BridgeUnavailable):cli.call('archive',sid,{'archived':True})
        self.assertTrue(self.path.exists())
        self.assertFalse(self.stored().exists())


    def test_local_cli_archive_routes_identity_and_refuses_resume(self):
        profile={'directory':self.directory,'origin':'synthetic','binary':'/synthetic/claude'}
        cli=ClaudeCli(Path(self.temp.name)/'uploads',profile_resolver=lambda:profile)
        listing=cli.listing();sid=listing['sessions'][0]['id']
        self.assertFalse(cli.call('archive-state',sid,{})['archiveSafe'])
        with patch.object(archive,'supported',return_value=True),patch.object(archive,'assert_no_cli'),patch('bridge.clients.claude.cli_session.assert_session_closed') as guard:
            self.assertTrue(cli.call('archive-state',sid,{})['archiveSafe'])
            cli.call('archive',sid,{'archived':True})
            self.assertGreaterEqual(guard.call_count,2)
            row=cli.listing()['sessions'][0]
            self.assertEqual(row['id'],sid);self.assertEqual(row['nativeId'],self.native)
            self.assertTrue(row['archived'])
            with self.assertRaises(ResumePreflightBlocked):cli.call('resume',sid,{})
            cli.call('archive',sid,{'archived':False})
        self.assertEqual(self.path.read_bytes(),self.raw)


class ProcessCensusTests(unittest.TestCase):
    def census(self, executable, script=None, uid=1000):
        output=SimpleNamespace(returncode=0,stdout=f'{uid} 4321 {executable}\n')
        values=[output]
        if script is not None:values.append(SimpleNamespace(returncode=0,stdout=script))
        return patch.object(archive.subprocess,'run',side_effect=values)

    def test_native_cli_refused(self):
        with patch.object(archive.sys,'platform','darwin'),patch.object(archive.os,'getuid',return_value=1000),self.census('/installed/claude'):
            with self.assertRaises(ValueError):archive.assert_no_cli('/selected/claude')

    def test_other_user_native_cli_not_owned(self):
        with patch.object(archive.sys,'platform','darwin'),patch.object(archive.os,'getuid',return_value=1000),self.census('/installed/claude',uid=1001):
            archive.assert_no_cli('/selected/claude')

    def test_unrelated_node_entry_script_allowed(self):
        with patch.object(archive.sys,'platform','darwin'),patch.object(archive.os,'getuid',return_value=1000),self.census('/usr/bin/node','node /fixture/dev-server.js synthetic-private-operand'):
            archive.assert_no_cli('/selected/claude')

    def test_known_node_claude_entry_script_refused(self):
        with patch.object(archive.sys,'platform','darwin'),patch.object(archive.os,'getuid',return_value=1000),self.census('/usr/bin/node','node /fixture/@anthropic-ai/claude-code/cli.js --resume synthetic'):
            with self.assertRaises(ValueError):archive.assert_no_cli('/selected/claude')

    def test_inaccessible_census_refused(self):
        with patch.object(archive.sys,'platform','darwin'),patch.object(archive.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='')):
            with self.assertRaises(ValueError):archive.assert_no_cli('/selected/claude')


class RuntimeProofTests(unittest.TestCase):
    def test_exact_native_digest_and_version_both_required(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            binary=Path(temporary)/'synthetic-native';binary.write_bytes(b'synthetic program')
            digest=hashlib.sha256(binary.read_bytes()).hexdigest()
            proof={('darwin','fixture-version'):digest}
            with patch.object(archive.sys,'platform','darwin'),patch.object(archive,'VERIFIED_PICKER_VERSIONS',proof),patch.object(archive.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='fixture-version (Claude Code)')) as run:
                self.assertTrue(archive.supported(str(binary),{}))
                run.assert_called_once()
                binary.write_bytes(b'changed unverified distribution')
                run.reset_mock()
                self.assertFalse(archive.supported(str(binary),{}))
                run.assert_not_called()

    def test_mac_proof_does_not_enable_linux(self):
        with patch.object(archive.sys,'platform','linux'),patch.object(archive,'VERIFIED_PICKER_VERSIONS',{('darwin','2.1.292'):'synthetic'}),patch.object(archive.subprocess,'run') as run:
            self.assertFalse(archive.supported('/not-launched',{}))
            run.assert_not_called()
