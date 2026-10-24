import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge.features.endpoints.wsl_terminal import WslTerminals
from bridge.features.terminals.manager import TerminalSessionMissing


class WslTerminalTests(unittest.TestCase):
    def setUp(self):
        self.terminals = WslTerminals()
        self.thread, self.identifier = str(uuid.uuid4()), str(uuid.uuid4())
        self.entry = SimpleNamespace(host='wsl:fixture', row={'distribution': 'Ubuntu', 'user': 'fixture'},
                                     store=Mock())
        self.entry.store.get.return_value = {'cwd': '/home/fixture/项目'}
        self.session = Mock()
        self.session.done.is_set.return_value = False
        self.session.read.return_value = {'output': '中文', 'running': True}

    def call(self, action, owner='phone', **params):
        return self.terminals.terminal(self.entry, self.thread, owner, action,
                                       {'id': self.identifier, **params})

    def open(self):
        with patch('bridge.features.endpoints.wsl_terminal.RemoteTerminalSession', return_value=self.session) as factory:
            self.call('open', cols=80, rows=24)
        return factory

    def test_open_uses_wsl_user_python_and_linux_cwd_without_windows_path_validation(self):
        factory = self.open()
        args, kwargs = factory.call_args
        self.assertEqual(args, (None, '/home/fixture/项目', 80, 24))
        with patch('bridge.features.endpoints.wsl_terminal.wsl.command', return_value=['wsl.exe', 'python3']) as command:
            self.assertEqual(kwargs['transport']('UTF8 中文'), ['wsl.exe', 'python3', '-u', '-c', 'UTF8 中文'])
        command.assert_called_once_with('Ubuntu', 'fixture')
        self.assertEqual(self.call('poll')['output'], '中文')

    def test_owner_isolation(self):
        self.open()
        with self.assertRaises(TerminalSessionMissing): self.call('input', owner='other', inputId='x', data='secret')
        self.session.write.assert_not_called()

    def test_unknown_input_result_is_not_replayed(self):
        self.open()
        self.session.write.side_effect = TimeoutError('unknown')
        with self.assertRaises(TimeoutError): self.call('input', inputId='input-id', data='echo 中文\r')
        self.session.write.assert_called_once_with('input-id', 'echo 中文\r')

    def test_resize_completion_close_and_lifecycle(self):
        self.open()
        self.call('resize', cols=100, rows=30)
        self.session.resize.assert_called_once_with(100, 30)
        self.call('complete', text='cat 项', selectionStart=5)
        self.session.complete.assert_called_once_with('cat 项', 5)
        self.assertEqual(self.call('close'), {'closed': True})
        self.session.stop.assert_called_once_with()
        self.session.done.wait.return_value = True
        self.terminals.close()
        self.assertEqual(self.session.stop.call_args.args, ('网关已停止',))

    def test_invalid_root_and_poll_parameters(self):
        self.entry.store.get.return_value = {'cwd': 'C:\\project'}
        with self.assertRaises(ValueError): self.call('open', cols=80, rows=24)
        self.entry.store.get.return_value = {'cwd': '/tmp/project'}
        self.open()
        with self.assertRaises(ValueError): self.call('poll', after=True)
        with self.assertRaises(ValueError): self.call('poll', waitMs=1001)
