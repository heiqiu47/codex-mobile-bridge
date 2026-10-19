import os
from pathlib import Path
import tempfile
import threading
import unittest

from bridge.features.terminals.completion import complete_path


class DummySession:
    def __init__(self, cwd, shell='/bin/zsh'):
        self.cwd = str(cwd); self.shell = shell; self.done = threading.Event()

    def current_cwd(self): return self.cwd


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.temp.name)
        (self.cwd / '普通 文件.txt').write_text('')
        (self.cwd / 'folder').mkdir()
        (self.cwd / 'folder' / 'inner file').write_text('')
        (self.cwd / 'a$(touch injected)').write_text('')
        self.session = DummySession(self.cwd)

    def tearDown(self): self.temp.cleanup()

    def complete(self, text, cursor=None):
        return complete_path(self.session, text, len(text.encode('utf-16-le')) // 2 if cursor is None else cursor)

    def test_paths_are_escaped_and_completion_never_executes(self):
        value = self.complete('ls 普')
        self.assertEqual(value['cwd'], str(self.cwd))
        self.assertEqual(value['replaceStart'], 3)
        self.assertEqual(value['candidates'][0]['insertText'], "'普通 文件.txt'")
        value = self.complete('ls a')
        self.assertEqual(value['candidates'][0]['insertText'], "'a$(touch injected)'")
        self.assertFalse((self.cwd / 'injected').exists())
        self.assertEqual(self.complete('ls fol')['candidates'][0]['insertText'], 'folder/')
        self.assertEqual(self.complete('ls folder/in')['candidates'][0]['insertText'], "'folder/inner file'")
        self.assertEqual(self.complete('ls '+str(self.cwd)+'/folder/in')['candidates'][0]['insertText'],
                         "'"+str(self.cwd)+"/folder/inner file'")
        self.assertEqual(self.complete('ls "folder/in')['candidates'][0]['insertText'], "'folder/inner file'")

    def test_quotes_utf16_and_unsafe_syntax(self):
        value = self.complete('😀 ls "普', cursor=8)
        self.assertEqual(value['replaceStart'], 6)
        self.assertEqual(value['replaceEnd'], 8)
        for text in ('ls $(whoami)', 'ls `whoami`', 'ls *.txt', 'ls a; pwd', 'ls a | cat', 'ls a\nother'):
            with self.subTest(text=text), self.assertRaises(ValueError): self.complete(text)
        with self.assertRaises(ValueError): self.complete('😀 ls', 1)

    def test_windows_drive_and_basic_quote(self):
        self.session.shell = 'C:\\Windows\\System32\\cmd.exe'
        value = self.complete('dir "普通')
        self.assertEqual(value['candidates'][0]['insertText'], '"普通 文件.txt"')
        for text in ('dir %TEMP%', 'dir a & whoami', 'dir ^x'):
            with self.subTest(text=text), self.assertRaises(ValueError): self.complete(text)

    def test_bounded_results(self):
        for index in range(100): (self.cwd / f'x{index:03}').write_text('')
        result = self.complete('ls x')
        self.assertEqual(len(result['candidates']), 80)
        self.assertTrue(result['truncated'])
        self.assertIsNone(result['commonPrefixInsertText'])

    def test_exhaustive_common_prefix_preserves_quoting_and_utf16_range(self):
        (self.cwd / 'alpha one').write_text('')
        (self.cwd / 'alpha two').write_text('')
        result = self.complete('😀 ls al')
        self.assertEqual((result['replaceStart'], result['replaceEnd']), (6, 8))
        self.assertEqual(result['commonPrefixInsertText'], "'alpha '")
        self.assertIsNone(self.complete("ls 'alpha '")['commonPrefixInsertText'])

    def test_windows_common_prefix_ignores_case(self):
        (self.cwd / 'FolderOne').write_text('')
        (self.cwd / 'folderTwo').write_text('')
        self.session.shell = 'C:\\Windows\\System32\\cmd.exe'
        result = self.complete('dir FOL')
        self.assertEqual(result['commonPrefixInsertText'].casefold(), 'folder')


if __name__ == '__main__': unittest.main()
