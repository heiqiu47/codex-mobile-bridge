"""Host references stay native tokens, without opening or copying project files."""
import unittest
from unittest.mock import patch

from bridge.clients.file_mentions import file_mentions, display_file_mentions
from bridge.clients.claude.cli_session import _message_content
from bridge.clients.claude.model import transcript
from bridge.clients.deepseek.adapter import messages
from bridge.clients.errors import ResumePreflightBlocked


class NativeFileMentions(unittest.TestCase):
    def test_native_cli_and_history_preserve_space_chinese_windows_and_directory(self):
        files = [{'path': '/project/中文 文件.md'}, {'path': 'F:\\项目\\file.txt'},
                 {'path': '/project/other folder', 'kind': 'directory'}]
        with patch('builtins.open', side_effect=AssertionError('must not read contents')):
            text = _message_content({'text': '/skill inspect', 'resolvedReferences': files})
        self.assertEqual(text, '/skill inspect\n\n@"/project/中文 文件.md"\n@F:\\项目\\file.txt\n@"/project/other folder/"')
        for rows in (transcript([{'type': 'user', 'message': {'content': text}}]),
                     messages([{'event': {'type': 'user/message', 'seq': 1, 'data': {'message': {'content': text}}}}])):
            self.assertEqual(rows[0]['text'], '/skill inspect')
            self.assertEqual([f['name'] for f in rows[0]['attachments']], ['中文 文件.md', 'file.txt', 'other folder'])

    def test_unrepresentable_reference_is_blocked_before_native_write(self):
        for path in ('relative.md', '/project/line\nbreak', '/project/"quote', '/project/\x85control'):
            with self.assertRaises(ResumePreflightBlocked):
                file_mentions('text', [{'path': path}])

    def test_normal_prose_inline_mentions_and_assistant_messages_are_untouched(self):
        for text in ('Use @filename', 'mail@example.com', '@relative.md', '```\n@/file\n```', 'text\n\n@/file\nnormal prose'):
            message = {'role': 'user', 'text': text}
            display_file_mentions(message)
            self.assertEqual(message, {'role': 'user', 'text': text})
        message = {'role': 'assistant', 'text': '@/project/file'}
        display_file_mentions(message)
        self.assertNotIn('attachments', message)

    def test_attachments_only_and_cowork_mount_paths_round_trip(self):
        for quote in (True, False):
            message = {'role': 'user', 'text': file_mentions('', [{'path': '/host/project/my file'}], quote=quote)}
            display_file_mentions(message)
            self.assertEqual(message['text'], '')
            self.assertEqual(message['attachments'], [{'type': 'file', 'path': '/host/project/my file', 'name': 'my file'}])


if __name__ == '__main__': unittest.main()
