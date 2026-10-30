import unittest
from bridge.clients.deepseek.adapter import messages

class DeepSeekMessageModelTests(unittest.TestCase):
    def reply(self, seq, model='chat', effort='high', selected='chat'):
        return {'event': {'seq': seq, 'type': 'assistant/message', 'data': {
            'modelSelection': {'provider': 'deepseek', 'model': selected, 'reasoningEffort': effort},
            'message': {'source': {'provider': 'deepseek', 'model': model},
                        'content': [{'type': 'thinking', 'thinking': 'reason'}, {'type': 'text', 'text': 'answer'}]}}}}

    def test_each_reply_keeps_its_own_actual_model_and_effort(self):
        rows = messages([self.reply(1), self.reply(2, 'other', 'low', 'other')])
        self.assertEqual([(r['model'], r['effort']) for r in rows],
                         [('deepseek/chat', 'high')]*2+[('deepseek/other', 'low')]*2)

    def test_mismatched_or_missing_request_metadata_never_labels_actual_model_with_other_effort(self):
        reply = self.reply(1, selected='other')
        rows = messages([reply])
        self.assertEqual(rows[1]['model'], 'deepseek/chat')
        self.assertNotIn('effort', rows[1])
        del reply['event']['data']['modelSelection']
        self.assertNotIn('effort', messages([reply])[1])

    def test_user_and_tool_messages_do_not_inherit_model(self):
        rows = messages([self.reply(1), {'event': {'seq': 2, 'type': 'user/message', 'data': {'content': 'hello'}}}])
        self.assertNotIn('model', rows[-1])

if __name__ == '__main__': unittest.main()
