import unittest
import uuid
from unittest.mock import Mock

import test_bridge

THREAD = test_bridge.THREAD


class MessageManagementHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = test_bridge.password_record('correct password test')

    setUp = test_bridge.HttpTests.setUp
    tearDown = test_bridge.HttpTests.tearDown
    request = test_bridge.HttpTests.request
    login = test_bridge.HttpTests.login

    def test_management_receipts_are_authenticated_host_scoped_and_mutations_need_csrf(self):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        target = '/api/sessions/' + THREAD + '/message-management?host=local&' + '&'.join('id=' + key for key in ids)
        self.server.bridge.message_management = Mock(return_value={'receipts': [{'id': ids[0], 'status': 'notFound'}]})
        self.server.bridge.manage_messages = Mock(return_value={'version': 'next'})
        self.assertEqual(self.request('GET', target)[0], 401)
        self.server.bridge.message_management.assert_not_called()
        headers = self.login()
        self.assertEqual(self.request('GET', target, headers=headers)[0], 200)
        self.server.bridge.message_management.assert_called_once_with(THREAD, ids)
        body = {'action': 'withdraw', 'id': ids[0], 'version': 'prior', 'expectedAccount': 'account'}
        self.assertEqual(self.request('POST', target, body, {'Cookie': headers['Cookie']})[0], 403)
        self.server.bridge.manage_messages.assert_not_called()
        self.assertEqual(self.request('POST', target, body, headers)[0], 200)
        self.server.bridge.manage_messages.assert_called_once_with(THREAD, body)
        self.assertEqual(self.request('GET', target.replace('host=local', 'host=missing'), headers=headers)[0], 404)


if __name__ == '__main__': unittest.main()
