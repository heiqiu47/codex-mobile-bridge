import tempfile
import unittest
from pathlib import Path

from bridge.features.workspace.files import code_comment_references, file_citation_references, workspace_references


class CodeCommentFilesTests(unittest.TestCase):
    def test_only_complete_valid_unfenced_directives(self):
        good = '::code-comment{title="Issue" body="Fix this" file="src/a.py" start=2 end=4 priority=1}'
        self.assertEqual(list(code_comment_references(good)), ['src/a.py'])
        for value in ['```python\n'+good+'\n```', '~~~\n'+good+'\n~~~', '`'+good+'`', '\\'+good, '    '+good, '> ```\n> '+good+'\n> ```', '- ```\n  '+good+'\n  ```', good[:-1], good.replace('end=4', 'end=1'), good.replace('start=2', 'start=0'), good.replace('priority=1', 'priority=5'), good.replace('start=2', 'start="2"'), good.replace('title="Issue"', 'title="Issue" title="Again"')]:
            self.assertEqual(list(code_comment_references(value)), [], value)
        self.assertEqual(list(code_comment_references(good.replace('src/a.py', r'C:\work\src\a.py'))), [r'C:\work\src\a.py'])
        windows = good.replace('src/a.py', r'C:\\work\\src\\a.py')
        self.assertEqual(list(code_comment_references(windows)), [r'C:\work\src\a.py'])

    def test_quoted_markdown_and_indented_newlines_are_directive_content(self):
        examples = [
            '::code-comment{title="Issue `foo`" body="use `foo()`" file="src/a.py"}',
            '::code-comment{title="Issue" body="use\n    foo()\n    `bar()`" file="src/a.py"}',
            r'::code-comment{title="Issue" body="use `foo()`" file="C:\work\src\a.py"}',
            r'::code-comment{title="Issue" body="use `foo()`" file="C:\\work\\src\\a.py"}',
        ]
        expected = ['src/a.py', 'src/a.py', r'C:\work\src\a.py', r'C:\work\src\a.py']
        for example, path in zip(examples, expected):
            self.assertEqual(list(code_comment_references(example)), [path])
            for enclosed in ['`' + example + '`', '```\n' + example + '\n```', '\\' + example]:
                self.assertEqual(list(code_comment_references(enclosed)), [])

    def test_references_keep_workspace_boundary_and_deny_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            (root / 'src').mkdir()
            target = root / 'src/a.py'
            target.write_text('pass')
            outside = Path(directory) / 'private.py'
            outside.write_text('secret')
            (root / 'alias.py').symlink_to(target)
            (root / 'escape.py').symlink_to(outside)
            def rows(path):
                text = '::code-comment{title="Issue" body="Fix" file="'+path+'" start=1}'
                return workspace_references([{'role':'assistant', 'text':text}], str(root))
            quoted = '::code-comment{title="Issue" body="use `foo()`\n    and `bar()`" file="src/a.py"}'
            self.assertEqual(workspace_references([{'role':'assistant', 'text':quoted}], str(root))[0]['path'], 'src/a.py')
            self.assertEqual(rows('src/a.py')[0]['path'], 'src/a.py')
            self.assertEqual(rows(str(target))[0]['path'], 'src/a.py')
            for path in ['../private.py', str(outside), 'alias.py', 'escape.py', 'https://example.com/a.py']:
                self.assertEqual(rows(path), [], path)


class FileCitationTests(unittest.TestCase):
    def test_complete_citation_is_not_active_inside_code(self):
        source = ':codex-file-citation{path="report.xls" artifact_kind="workbook" purpose="source"}'
        self.assertEqual(list(file_citation_references(source)), ['report.xls'])
        for text in ['`'+source+'`', '```\n'+source+'\n```', '\\'+source, '    '+source, source[:-1], source.replace('purpose="source"', 'unknown="source"'), source.replace('path="report.xls"', 'path=1'), source.replace('purpose="source"', 'purpose=1')]:
            self.assertEqual(list(file_citation_references(text)), [], text)

    def test_citation_grants_reuse_workspace_roots_and_deny_outside_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            target = root / 'report.xls'
            target.write_bytes(b'workbook')
            outside = Path(directory) / 'private.xls'
            outside.write_bytes(b'private')
            (root / 'escape.xls').symlink_to(outside)
            def rows(path):
                return workspace_references([{'role':'assistant', 'text':':codex-file-citation{path="'+str(path)+'" artifact_kind="workbook" purpose="source"}'}], str(root))
            self.assertEqual(rows(target)[0]['path'], 'report.xls')
            self.assertEqual(rows('report.xls')[0]['path'], 'report.xls')
            for path in [outside, '../private.xls', 'escape.xls', 'https://example.com/private.xls', 'file://remote/private.xls']:
                self.assertEqual(rows(path), [], str(path))
