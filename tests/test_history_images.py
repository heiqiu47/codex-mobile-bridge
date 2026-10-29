import base64
import json
import tempfile
import unittest
from pathlib import Path

from bridge.features.workspace.history_images import HistoryImages
from bridge.clients.claude.model import transcript, history_image
from bridge.clients.claude.history import image_event
from bridge.clients.deepseek.adapter import messages

PNG = b'\x89PNG\r\n\x1a\nfixture'
PAYLOAD = {'mediaType':'image/png','data':base64.b64encode(PNG).decode()}


class HistoryImageTests(unittest.TestCase):
    def test_shared_preview_is_lazy_scoped_and_revalidated(self):
        images = HistoryImages()
        rows = [{'attachments':[{'type':'image','_nativeImage':{'event':'e','part':0}}]}]
        images.bind('new-agent','chat',rows)
        descriptor = rows[0]['attachments'][0]
        self.assertNotIn('_nativeImage', descriptor)
        calls = []
        def load(source):
            calls.append(source)
            return PAYLOAD
        with self.assertRaises(ValueError):
            images.preview('new-agent','other',descriptor['desktopId'],load)
        self.assertEqual(calls, [])
        for _ in range(2):
            artifact, variant = images.preview('new-agent','chat',descriptor['desktopId'],load)
            self.assertEqual(artifact['previewBytes'], PNG)
            self.assertEqual(variant, 'native')
        self.assertEqual(len(calls), 2)
        with self.assertRaises(ValueError):
            images.preview('new-agent','chat',descriptor['desktopId'],lambda _: {'mediaType':'image/svg+xml','data':PAYLOAD['data']})
        with self.assertRaises(ValueError):
            images.preview('new-agent','chat',descriptor['desktopId'],lambda _: {'mediaType':'image/png','data':'http://private/'})

    def test_claude_history_preserves_order_and_opaque_original_block_index(self):
        event = {'type':'user','uuid':'message','message':{'role':'user','content':[
            {'type':'text','text':'before'}, {'type':'image','source':{'type':'base64','media_type':'image/png','data':PAYLOAD['data']}},
            {'type':'text','text':'after'}]}}
        result = transcript([event])
        self.assertEqual([row['text'] for row in result], ['before','','after'])
        source = result[1]['attachments'][0]['_nativeImage']
        self.assertEqual(history_image([event],source), PAYLOAD)
        self.assertNotIn(PAYLOAD['data'], json.dumps(result))
        with self.assertRaises(ValueError):
            history_image([event],{'event':'other','part':1})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history.jsonl'
            path.write_text(json.dumps(event)+'\n')
            self.assertEqual(history_image([image_event(path,source)],source), PAYLOAD)

    def test_native_reference_requires_no_client_binary_or_session_activation(self):
        source = {'event':'image','part':4}
        value = transcript([{'type':'user','uuid':'image','message':{'content':[
            {'type':'image','imageRef':source}]}}])
        self.assertEqual(value[0]['attachments'][0]['_nativeImage'],source)
        result = messages([{'event':{'seq':9,'type':'user/message','data':{'content':[
            {'type':'image','attachment':{'attachmentId':'native-image','name':'photo.png'}}]}}}])
        self.assertEqual(result[0]['attachments'][0]['_nativeImage'],{'seq':9,'part':0})
        self.assertNotIn('native-image', json.dumps(result))

    def test_reference_budget_does_not_leak_another_session(self):
        images = HistoryImages(max_entries=1)
        first = [{'attachments':[{'_nativeImage':{'event':'same','part':0}}]}]
        second = [{'attachments':[{'_nativeImage':{'event':'same','part':0}}]}]
        images.bind('claude','first',first);images.bind('claude','second',second)
        self.assertNotEqual(first,second)
        with self.assertRaises(ValueError):
            images.preview('claude','first',first[0]['attachments'][0]['desktopId'],lambda _: PAYLOAD)
