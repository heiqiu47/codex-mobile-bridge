"""The Mermaid engine only runs in a fixed, authenticated sandboxed page."""
import http.client
import unittest
from pathlib import Path

import test_bridge as support
from bridge.api.mermaid_render import shell_bytes, shell_csp

ROOT = Path(__file__).resolve().parents[1]


class GatewayMermaidTests(unittest.TestCase):
    setUpClass = classmethod(support.HttpTests.setUpClass.__func__)
    setUp = support.HttpTests.setUp
    tearDown = support.HttpTests.tearDown
    login = support.HttpTests.login
    request = support.HttpTests.request

    def raw(self, path, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            conn.request('GET', path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_shell_and_bundle_are_local_and_isolated(self):
        self.assertEqual(self.raw('/mermaid-render-shell')[0], 401)
        login = self.login()
        status, headers, body = self.raw('/mermaid-render-shell', login)
        self.assertEqual(status, 200)
        self.assertEqual(body, shell_bytes(ROOT / 'web'))
        self.assertIn(b'vendor/mermaid/mermaid.min.js?v=', body)
        self.assertIn(b'mermaid-render-frame.js?v=', body)
        self.assertEqual(headers['Content-Security-Policy'], shell_csp(self.origin))
        self.assertIn('sandbox allow-scripts', headers['Content-Security-Policy'])
        self.assertIn("connect-src 'none'", headers['Content-Security-Policy'])
        self.assertNotIn("script-src 'unsafe-inline'", headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(self.raw('/mermaid-render-shell?source=x', login)[0], 405)
        for asset in ('/mermaid-renderer.js', '/mermaid-render-frame.js', '/vendor/mermaid/mermaid.min.js'):
            self.assertEqual(self.raw(asset, login)[0], 200, asset)
        status, headers, _ = self.raw('/', login)
        self.assertEqual(status, 200)
        self.assertIn(self.origin + '/mermaid-render-shell;', headers['Content-Security-Policy'])
        self.assertNotIn("script-src 'unsafe-inline'", headers['Content-Security-Policy'])


class RelayMermaidTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            from aiohttp.test_utils import TestClient, TestServer
            from relay.server import create_app, STATE
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        (ROOT / '.tmp').mkdir(exist_ok=True)
        import tempfile
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.app = create_app(Path(self.temp.name) / 'relay', 'http://127.0.0.1:1', test_http=True)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.state = self.app[STATE]
        self.origin = str(self.server.make_url('')).rstrip('/')
        self.state.origin = self.origin
        self.state.host = self.origin.removeprefix('http://')

    async def asyncTearDown(self):
        await self.client.close()
        self.state.registry.close()
        self.temp.cleanup()

    async def test_scoped_shell_is_fixed_and_authenticated(self):
        self.assertEqual((await self.client.get('/mermaid-render-shell')).status, 401)
        self.state.phone_auth = lambda request: {'id': 'synthetic'}
        for prefix in ('', '/d/' + 'a' * 32):
            response = await self.client.get(prefix + '/mermaid-render-shell')
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), shell_bytes(ROOT / 'web'))
            self.assertEqual(response.headers['Content-Security-Policy'], shell_csp(self.origin))
            self.assertEqual((await self.client.get(prefix + '/mermaid-render-shell?source=x')).status, 404)
            page = await self.client.get(prefix + '/')
            self.assertIn(self.origin + prefix + '/mermaid-render-shell;', page.headers['Content-Security-Policy'])
