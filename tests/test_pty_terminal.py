import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from bridge.platforms.posix.terminal import TerminalSession, RemoteTerminalSession, default_shell, dimensions
from bridge.features.terminals.manager import TerminalManager
from bridge.features.terminals.completion import complete_path


@unittest.skipIf(os.name == 'nt', 'POSIX PTY requires Unix')
class PtyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.tmp')
        self.root = Path(self.temp.name); self.sessions = []
        self.env = patch.dict(os.environ, {'ZDOTDIR':'.', 'HISTFILE':str(self.root/'history')}); self.env.start()
        # Keep distro-wide interactive setup (e.g. compinit prompts) out of the fixture.
        (self.root/'.zshenv').write_text('unsetopt GLOBAL_RCS\n')
        (self.root/'.zshrc').write_text("PROMPT='fixture% '\nexport BRIDGE_STARTUP_TEST=loaded\n")
        (self.root/'.bashrc').write_text("PS1='fixture$ '\nexport BRIDGE_STARTUP_TEST=loaded\n")
    def tearDown(self):
        for session in self.sessions: session.stop(); self.assertTrue(session.done.wait(5))
        self.env.stop(); self.temp.cleanup()
    def session(self):
        session = TerminalSession(self.root); self.sessions.append(session); return session
    def send(self, session, data, identifier=None):
        session.write(identifier or str(uuid.uuid4()), data)
    def wait_output(self, session, marker):
        deadline = time.monotonic()+7
        while time.monotonic()<deadline:
            if marker in session.read()['output']: return session.read()['output']
            time.sleep(.02)
        self.fail('Missing terminal output '+marker+' in '+session.read()['output'][-1000:])
    def test_default_shell_uses_account_setting_not_inherited_shell(self):
        import pwd
        from types import SimpleNamespace
        for actual, inherited in (('/bin/zsh', '/bin/bash'), ('/bin/bash', '/bin/zsh')):
            with self.subTest(actual=actual), patch.object(pwd,'getpwuid',return_value=SimpleNamespace(pw_shell=actual)), patch.dict(os.environ,{'SHELL':inherited}), patch('bridge.platforms.posix.terminal.os.access',return_value=True):
                self.assertEqual(default_shell(),actual)
    def test_real_tty_startup_cd_environment_and_interactive_read(self):
        shell = shutil.which('zsh') or shutil.which('bash')
        if not shell:
            self.skipTest('interactive startup fixture requires zsh or bash')
        if Path(shell).name == 'bash':
            launcher = self.root/'fixture-shell'
            launcher.write_text('#!/bin/sh\nexec '+shlex.quote(shell)+' --noprofile --rcfile '+shlex.quote(str(self.root/'.bashrc'))+' -i\n')
            launcher.chmod(0o700)
            shell = str(launcher)
        with patch('bridge.platforms.posix.terminal.default_shell',return_value=shell): s=self.session()
        self.send(s,"printf 'STARTUP:%s\\n' \"$BRIDGE_STARTUP_TEST\"; test -t 0 && echo PTY_OK\r")
        self.wait_output(s,'STARTUP:loaded'); self.wait_output(s,'PTY_OK\r\n')
        (self.root/'nested').mkdir()
        self.send(s,'cd nested; export BRIDGE_VALUE=kept\r')
        self.send(s,"printf 'STATE:%s:%s\\n' \"${PWD##*/}\" \"$BRIDGE_VALUE\"\r")
        self.wait_output(s,'STATE:nested:kept')
        self.send(s,"printf 'READ_%s\\n' ready; read reply; printf 'ANSWER:%s\\n' \"$reply\"\r")
        self.wait_output(s,'READ_ready')
        self.send(s,'hello input\r'); self.wait_output(s,'ANSWER:hello input')

    def test_completion_uses_live_shell_cwd_after_cd(self):
        s=self.session(); (self.root/'nested').mkdir(); (self.root/'nested'/'目标 文件').write_text('')
        self.wait_output(s, 'fixture')
        self.send(s,'cd nested\r'); self.wait_output(s,'cd nested')
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            try:
                if s.current_cwd()==str(self.root/'nested'): break
            except ValueError: pass
            time.sleep(.02)
        self.assertEqual(s.current_cwd(),str(self.root/'nested'))
        result=complete_path(s,'ls 目',4)
        self.assertEqual(result['cwd'],str(self.root/'nested'))
        self.assertEqual(result['candidates'][0]['insertText'],"'目标 文件'")

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS ls color defaults')
    def test_ll_colors_file_types_without_coloring_piped_output(self):
        (self.root/'directory').mkdir()
        (self.root/'plain.txt').write_text('')
        (self.root/'executable').write_text('#!/bin/sh\n')
        (self.root/'executable').chmod(0o700)
        (self.root/'link').symlink_to('plain.txt')
        with (self.root/'.zshrc').open('a') as rc: rc.write("alias ll='/bin/ls -l'\n")
        with patch.dict(os.environ), patch('bridge.platforms.posix.terminal.default_shell', return_value='/bin/zsh'):
            for key in ('CLICOLOR', 'CLICOLOR_FORCE', 'LSCOLORS'): os.environ.pop(key, None)
            s=self.session()
        self.wait_output(s,'fixture')
        self.send(s,"printf '__LIST_%s__\\n' begin; ll; printf '__LIST_%s__\\n' end\r")
        output=self.wait_output(s,'__LIST_end__').split('__LIST_begin__\r\n',1)[1].split('__LIST_end__',1)[0]
        self.assertRegex(output,r'\x1b\[[0-9;]*mdirectory')
        self.assertRegex(output,r'\x1b\[[0-9;]*mexecutable')
        self.assertRegex(output,r'\x1b\[[0-9;]*mlink')
        self.send(s,"printf '__PIPE_%s__\\n' begin; ll | cat; printf '__PIPE_%s__\\n' end\r")
        piped=self.wait_output(s,'__PIPE_end__').split('__PIPE_begin__\r\n',1)[1].split('__PIPE_end__',1)[0]
        self.assertNotIn('\x1b[',piped)

    def test_explicit_terminal_color_setting_is_inherited(self):
        with patch.dict(os.environ, {'CLICOLOR':'custom'}): s=self.session()
        self.send(s,"printf 'COLOR_SETTING:%s\\n' \"$CLICOLOR\"\r")
        self.wait_output(s,'COLOR_SETTING:custom')

    def test_terminal_shell_uses_utf8_when_gateway_locale_is_c(self):
        with patch.dict(os.environ, {'LANG':'C', 'LC_ALL':'C', 'LC_CTYPE':'C'}):
            s = self.session()
        self.send(s,"locale charmap\r")
        output = self.wait_output(s, 'locale charmap')
        deadline = time.monotonic() + 5
        while 'UTF-8' not in output and time.monotonic() < deadline:
            time.sleep(.02); output = s.read()['output']
        self.assertIn('UTF-8', output)
        self.send(s,"printf '中文输出\\n'\r")
        self.wait_output(s, '中文输出\r\n')

    def test_terminal_preserves_existing_utf8_locale(self):
        with patch.dict(os.environ, {'LANG':'zh_CN.UTF-8', 'LC_ALL':'zh_CN.UTF-8', 'LC_CTYPE':'zh_CN.UTF-8'}):
            s = self.session()
        self.send(s,"printf 'LOCALE:%s:%s:%s\\n' \"$LANG\" \"$LC_ALL\" \"$LC_CTYPE\"\r")
        self.wait_output(s, 'LOCALE:zh_CN.UTF-8:zh_CN.UTF-8:zh_CN.UTF-8')

    def test_long_poll_wakes_on_output_and_is_bounded(self):
        s=self.session(); self.wait_output(s,'fixture'); time.sleep(.1)
        cursor=s.read()['cursor']; started=time.monotonic(); self.assertEqual(s.read(cursor,80)['output'],'')
        self.assertGreaterEqual(time.monotonic()-started,.06)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(s.read,cursor,1000)
            self.send(s,'echo WAKE_MARKER\r')
            result=pending.result(timeout=2)
        self.assertTrue(result['output']); self.wait_output(s,'WAKE_MARKER')
    def test_resize_and_ctrl_c_keep_shell_alive(self):
        s=self.session(); s.resize(93,31)
        self.send(s,"stty size\r"); self.wait_output(s,'31 93')
        # Wait for the target foreground job, not output from the preceding stty.
        self.send(s,"sh -c 'echo $$ > interrupt.pid; exec sleep 90'\r")
        child_file = self.root/'interrupt.pid'; deadline = time.monotonic()+5
        while (not child_file.exists() or not child_file.read_text().strip()) and time.monotonic()<deadline: time.sleep(.02)
        child = int(child_file.read_text())
        self.assertEqual(os.tcgetpgrp(s.master), child)
        self.send(s,'\x03')
        deadline = time.monotonic()+5
        while os.tcgetpgrp(s.master) != s.process.pid and time.monotonic()<deadline: time.sleep(.02)
        self.assertEqual(os.tcgetpgrp(s.master), s.process.pid)
        self.send(s,"printf 'AFTER_%s\\n' interrupt\r")
        self.wait_output(s,'AFTER_interrupt'); self.assertFalse(s.done.is_set())
        self.send(s,'exit\r'); self.assertTrue(s.done.wait(5))
    def test_input_retry_is_exactly_once_and_conflicts_rejected(self):
        s=self.session(); identifier=str(uuid.uuid4());data="printf x >> exactly-once\r"
        self.send(s,data,identifier);self.send(s,data,identifier)
        self.send(s,"printf 'ACK_%s\\n' ready\r");self.wait_output(s,'ACK_ready')
        self.assertEqual((self.root/'exactly-once').read_text(),'x')
        with self.assertRaises(ValueError):self.send(s,'echo different\r',identifier)
    def test_close_kills_foreground_process(self):
        # The child reports readiness itself: a parent-written PID can race
        # zsh's forked child before it has installed its signal disposition.
        s=self.session(); self.send(s,"sh -c 'echo $$ > child.pid; exec sleep 90' & wait\r")
        deadline=time.monotonic()+5
        while (not (self.root/'child.pid').exists() or not (self.root/'child.pid').read_text().strip()) and time.monotonic()<deadline:time.sleep(.02)
        child=int((self.root/'child.pid').read_text());s.stop();self.assertTrue(s.done.wait(5))
        # The child may briefly be a zombie while reaped by the OS, but cannot run.
        result=subprocess.run(['ps','-p',str(child),'-o','stat='],capture_output=True,text=True)
        self.assertTrue(not result.stdout.strip() or result.stdout.strip().startswith('Z'))
    def test_remote_protocol_persists_state_and_acknowledges_input(self):
        original=subprocess.Popen
        def launch(args,**kwargs):
            self.assertEqual(args[:2],['ssh','-T'])
            return original([sys.executable,'-u','-c',shlex.split(args[-1])[-1]],**kwargs)
        with patch('bridge.platforms.posix.terminal.subprocess.Popen',side_effect=launch): s=RemoteTerminalSession('fixture',self.root)
        self.sessions.append(s)
        self.send(s,'export REMOTE_VALUE=kept\r')
        self.send(s,"printf 'REMOTE:%s\\n' \"$REMOTE_VALUE\"\r")
        self.wait_output(s,'REMOTE:kept'); self.assertTrue(s.shell.startswith('/'))
        s.resize(91,29);self.send(s,'stty size\r');self.wait_output(s,'29 91')

    def test_remote_source_shell_uses_utf8_when_remote_locale_is_c(self):
        original = subprocess.Popen
        def launch(args, **kwargs):
            return original([sys.executable, '-u', '-c', shlex.split(args[-1])[-1]], **kwargs)
        with patch.dict(os.environ, {'LANG':'C', 'LC_ALL':'C', 'LC_CTYPE':'C'}), \
             patch('bridge.platforms.posix.terminal.subprocess.Popen', side_effect=launch):
            s = RemoteTerminalSession('fixture', self.root)
        self.sessions.append(s)
        self.send(s, 'locale charmap\r')
        self.wait_output(s, 'UTF-8\r\n')
    def test_manager_scopes_retries_and_does_not_resurrect_closed_terminal(self):
        m=TerminalManager();self.addCleanup(m.close); identifier=str(uuid.uuid4())
        m.open_session('a','thread',identifier,self.root,80,24);s=m.session('a','thread',identifier)
        m.open_session('a','thread',identifier,self.root,80,24);self.assertIs(s,m.session('a','thread',identifier))
        with self.assertRaises(KeyError):m.session('b','thread',identifier)
        with self.assertRaises(KeyError):m.session('a','other',identifier)
        s.stop();self.assertTrue(s.done.wait(5));self.assertFalse(m.open_session('a','thread',identifier,self.root,80,24)['running'])
        for pair in ((0,24),(80,999),(True,20)):
            with self.assertRaises(ValueError):dimensions(*pair)
