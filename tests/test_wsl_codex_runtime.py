"""Native handoff safety using synthetic proc trees and mocked kernel syscalls."""
import io
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from bridge.platforms import codex_process_identity as identity
from bridge.platforms.windows import wsl_account_runtime as native
from bridge.features.accounts import wsl_account_worker as worker

ROOT = Path(__file__).resolve().parents[1]


class NativeStopProtocolTests(unittest.TestCase):
    def execute_stop(self, snapshots, ready=True):
        daemon = {'pid': 900001, 'startTicks': '123'}
        system = SimpleNamespace(pidfd_open=Mock(return_value=55), close=Mock())
        signals = SimpleNamespace(SIGTERM=15, pidfd_send_signal=Mock())
        namespace = {'request': {'action': 'stop', 'daemon': daemon}, 'inspect': Mock(side_effect=snapshots),
                     'os': system, 'signal': signals,
                     'select': SimpleNamespace(select=Mock(return_value=([55], [], []) if ready else ([], [], []))),
                     'signal_sent': False}
        body = "action=request['action']" + native._RUNTIME_SOURCE.split("action=request['action']", 1)[1]
        return namespace, body, system, signals

    def test_pid_generation_change_after_pidfd_binding_never_signals(self):
        before = {'daemons': [{'pid': 900001, 'startTicks': '123'}], 'blockers': []}
        changed = {'daemons': [{'pid': 900001, 'startTicks': '456'}], 'blockers': []}
        namespace, body, system, signals = self.execute_stop([before, changed])
        with self.assertRaisesRegex(ValueError, '身份已变化'):
            exec(body, namespace)
        signals.pidfd_send_signal.assert_not_called()
        system.close.assert_called_once_with(55)

    def test_one_sigterm_timeout_has_no_force_fallback(self):
        before = {'daemons': [{'pid': 900001, 'startTicks': '123'}], 'blockers': []}
        namespace, body, system, signals = self.execute_stop([before, before], ready=False)
        with self.assertRaisesRegex(ValueError, '未正常退出'):
            exec(body, namespace)
        signals.pidfd_send_signal.assert_called_once_with(55, 15, None, 0)
        self.assertTrue(namespace['signal_sent'])
        system.close.assert_called_once_with(55)

    def test_verified_exit_returns_only_after_no_remaining_native_client(self):
        before = {'daemons': [{'pid': 900001, 'startTicks': '123'}], 'blockers': []}
        namespace, body, _, signals = self.execute_stop([before, before, {'daemons': [], 'blockers': []}])
        exec(body, namespace)
        self.assertEqual(namespace['result'], {'stopped': True})
        signals.pidfd_send_signal.assert_called_once()

    def test_stop_transport_distinguishes_confirmed_no_signal_from_unknown(self):
        with patch.object(native.wsl, 'read', return_value={'ok': False, 'error': 'identity changed', 'signalSent': False}):
            with self.assertRaises(native.HandoffError) as caught:
                native.stop('Fixture', 'fixture', '/fixture', {})
        self.assertIs(caught.exception.signal_sent, False)

    def test_reused_pid_and_start_ticks_on_another_kernel_never_signals(self):
        before = {'daemons': [{'pid': 900001, 'startTicks': '123', 'bootId': 'old-boot'}], 'blockers': []}
        changed = {'daemons': [{'pid': 900001, 'startTicks': '123', 'bootId': 'new-boot'}], 'blockers': []}
        namespace, body, _, signals = self.execute_stop([changed])
        namespace['request']['daemon'] = before['daemons'][0]
        with self.assertRaisesRegex(ValueError, '身份或任务入口'):
            exec(body, namespace)
        signals.pidfd_send_signal.assert_not_called()

    def test_owned_operation_lock_uses_eof_without_native_lifecycle_signals(self):
        process = Mock()
        process.stdout = io.BytesIO(b'{"locked":true}\n')
        with patch.object(native.wsl, 'command', return_value=['wsl.exe', '--exec', 'python3']), \
                patch.object(native.subprocess, 'Popen', return_value=process) as launch:
            lock = native.OperationLock('Fixture', 'fixture', '/fixture')
            lock.acquire()
            lock.release()
        self.assertEqual(launch.call_args.args[0][:5], ['wsl.exe', '--exec', 'python3', '-u', '-c'])
        process.stdin.close.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()


@unittest.skipUnless(os.name == 'posix', 'Synthetic Linux proc ownership fixture')
class NativeUpdaterIdentityTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / '.codex'
        self.state = self.home / 'app-server-daemon'
        self.state.mkdir(parents=True)
        self.state.chmod(0o700)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.boot = self.root / 'boot'
        self.boot.write_text('fixture-boot-id')
        self.binary = self.root / 'codex'
        self.binary.write_bytes(b'fixture-native-executable')
        self.binary.chmod(0o700)
        self.main = self.process('900001', 123, [b'app-server', b'--managed-daemon'])
        self.updater = self.process('900002', 456, [b'app-server', b'daemon', b'pid-update-loop'])
        self.record('daemon.pid', 900001, 123)
        self.record('daemon-updater.pid', 900002, 456)
        self.args = (self.updater / 'cmdline').read_bytes().split(b'\0')
        self.env = {b'CODEX_HOME': os.fsencode(self.home)}
        original = Path
        def selected(value):
            if str(value) == '/proc': return self.proc
            if str(value) == '/proc/sys/kernel/random/boot_id': return self.boot
            return original(value)
        self.paths = patch.object(identity, 'Path', side_effect=selected)
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def process(self, pid, ticks, args):
        process = self.proc / pid
        process.mkdir()
        fields = ['S'] + ['0'] * 18 + [str(ticks)]
        (process / 'stat').write_text(pid + ' (codex) ' + ' '.join(fields))
        (process / 'cmdline').write_bytes(b'\0'.join([os.fsencode(self.binary), *args]) + b'\0')
        (process / 'environ').write_bytes(b'CODEX_HOME=' + os.fsencode(self.home) + b'\0')
        (process / 'exe').symlink_to(self.binary)
        return process

    def record(self, name, pid, ticks):
        path = self.state / name
        path.write_text(json.dumps({'pid': pid, 'processIdentity': {'bootId': 'fixture-boot-id', 'startTicks': ticks}}))
        path.chmod(0o600)

    def check(self, expected=None):
        return identity.codex_updater(self.updater, str(self.binary), self.args, self.env, self.home, expected)

    def test_registered_helper_matches_live_same_inode_home_uid_and_pid_generation(self):
        proof = self.check()
        self.assertEqual(proof['pid'], 900002)
        self.assertEqual(proof['startTicks'], 456)
        shutil.rmtree(self.main)
        self.assertIsNone(self.check())
        self.assertEqual(self.check(proof), proof)

    def test_stale_pid_record_unregistered_process_or_foreign_binary_never_exempts(self):
        self.record('daemon-updater.pid', 900002, 999)
        self.assertIsNone(self.check())
        self.record('daemon-updater.pid', 900002, 456)
        (self.state / 'daemon-updater.pid').chmod(0o666)
        self.assertIsNone(self.check())
        (self.state / 'daemon-updater.pid').chmod(0o644)
        alternate = self.root / 'other' / 'codex'
        alternate.parent.mkdir()
        alternate.write_bytes(b'other native executable')
        (self.main / 'exe').unlink()
        (self.main / 'exe').symlink_to(alternate)
        self.assertIsNone(self.check())

    def test_group_writable_state_directory_never_exempts(self):
        self.state.chmod(0o770)
        self.assertIsNone(self.check())

    def test_extra_arguments_and_foreign_home_are_not_native_updater_authorization(self):
        self.args.append(b'--other-role')
        self.assertIsNone(self.check())
        self.args.pop()
        self.env[b'CODEX_HOME'] = b'/different/home'
        self.assertIsNone(self.check())

    def test_native_default_home_is_verified_from_each_process_own_home(self):
        self.env = {b'HOME': os.fsencode(self.root)}
        (self.main / 'environ').write_bytes(b'HOME=' + os.fsencode(self.root) + b'\0')
        proof = self.check()
        self.assertEqual(proof['home'], str(self.home))
        self.env[b'HOME'] = b'relative-home'
        self.assertIsNone(self.check())
