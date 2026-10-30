"""HTTP cache behavior for the fixed public asset allowlist."""
import gzip
import hashlib
import http.client
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.api.assets import STATIC, _CSS_URL, _HTML_URL, _assembled, current_version, served_asset_bytes
from bridge.api.httpd import GatewayServer


ROOT = Path(__file__).resolve().parents[1]


class RealAssetReferenceTests(unittest.TestCase):
    def test_index_versions_every_literal_public_asset_reference(self):
        web = ROOT / 'web'
        references = []
        for match in _HTML_URL.finditer(served_asset_bytes(web, '/')):
            url = match['url'].decode('ascii')
            path, _, query = url.partition('?')
            if path in STATIC and path != '/':
                references.append(path)
                self.assertEqual(query, 'v=' + current_version(web, path), url)
        self.assertGreaterEqual(len(set(references)), 50)

    def test_katex_stylesheet_versions_its_font_urls(self):
        web = ROOT / 'web'
        css = served_asset_bytes(web, '/vendor/katex/katex.min.css')
        fonts = [match['url'].decode('ascii') for match in _CSS_URL.finditer(css)
                 if match['url'].startswith(b'fonts/')]
        self.assertGreaterEqual(len(fonts), 20)
        for url in fonts:
            name, _, query = url.partition('?')
            self.assertEqual(query, 'v=' + current_version(web, '/vendor/katex/' + name))


class StaticCacheTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        folder = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(folder.cleanup)
        self.web = Path(folder.name)
        (self.web / 'index.html').write_text('<html><head><link href="/style.css?v=old"><link rel="manifest" href="/manifest.webmanifest"></head><body><script src="/app.js"></script></body></html>')
        (self.web / 'base.css').write_bytes(b'.item{color:red}')
        (self.web / 'mobile.css').write_bytes(b'.item{width:1px}')
        (self.web / 'app.js').write_bytes(b'console.log("ready")')
        (self.web / 'manifest.webmanifest').write_bytes(b'{"icons":[{"src":"/icon.png"}]}')
        (self.web / 'icon.png').write_bytes(b'PNG-fixture')
        routes = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/style.css': (('base.css', 'mobile.css'), 'text/css; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json'),
                  '/icon.png': ('icon.png', 'image/png')}
        patcher = patch.dict(STATIC, routes)
        patcher.start()
        self.addCleanup(patcher.stop)
        _assembled.cache_clear()
        self.addCleanup(_assembled.cache_clear)
        self.server = GatewayServer(('127.0.0.1', 0), object(), {'auth': {'mode': 'none'}, 'origins': []}, self.web)
        self.port = self.server.server_address[1]
        self.host = f'127.0.0.1:{self.port}'
        self.server.hosts.add(self.host)
        self.server.origins.add('http://' + self.host)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        self.addCleanup(connection.close)
        connection.request('GET', path, headers={'Host': self.host, 'Origin': 'http://' + self.host, **(headers or {})})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_html_nonce_and_content_versioned_references(self):
        one = self.get('/')
        two = self.get('/')
        self.assertEqual(one[1]['Cache-Control'], 'no-store')
        self.assertNotEqual(re.search(rb'bridge-style-nonce" content="([^"]+)', one[2])[1],
                            re.search(rb'bridge-style-nonce" content="([^"]+)', two[2])[1])
        style = re.search(rb'/style\.css\?v=([0-9a-f]{64})', one[2])[1].decode()
        self.assertEqual(style, hashlib.sha256(b'.item{color:red}.item{width:1px}').hexdigest())
        self.assertIn(b'/app.js?v=', one[2])
        self.assertIn(b'/manifest.webmanifest?v=', one[2])
        manifest = self.get('/manifest.webmanifest?v=' + re.search(rb'/manifest\.webmanifest\?v=([0-9a-f]{64})', one[2])[1].decode())
        self.assertIn(b'/icon.png?v=', manifest[2])
        self.assertIn('immutable', manifest[1]['Cache-Control'])

    def test_version_validator_and_representation_etags(self):
        digest = hashlib.sha256(b'.item{color:red}.item{width:1px}').hexdigest()
        versioned = '/style.css?v=' + digest
        status, headers, body = self.get(versioned)
        self.assertEqual((status, body), (200, b'.item{color:red}.item{width:1px}'))
        self.assertIn('immutable', headers['Cache-Control'])
        self.assertEqual(headers['Vary'], 'Accept-Encoding')
        for url in ('/style.css', '/style.css?v=stale', versioned + '&v=' + digest):
            self.assertEqual(self.get(url)[1]['Cache-Control'], 'no-cache')
        for validator in (headers['ETag'], 'W/' + headers['ETag'], '"nope", W/' + headers['ETag'], '*'):
            status, conditional, body = self.get(versioned, {'If-None-Match': validator})
            self.assertEqual((status, body), (304, b''))
            self.assertNotIn('Content-Length', conditional)
        zipped = self.get(versioned, {'Accept-Encoding': 'gzip'})
        # The fixture is short, so use the real large stylesheet for gzip below.
        self.assertEqual(zipped[1]['ETag'], headers['ETag'])

    def test_dependency_change_and_rollback(self):
        first = self.get('/')[2]
        old_version = re.search(rb'/style\.css\?v=([0-9a-f]{64})', first)[1].decode()
        file = self.web / 'mobile.css'
        stat = file.stat()
        file.write_bytes(b'.item{width:2px}')
        os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        second = self.get('/')[2]
        new_version = re.search(rb'/style\.css\?v=([0-9a-f]{64})', second)[1].decode()
        self.assertNotEqual(new_version, old_version)
        self.assertEqual(self.get('/style.css?v=' + old_version)[1]['Cache-Control'], 'no-cache')
        self.assertIn('immutable', self.get('/style.css?v=' + new_version)[1]['Cache-Control'])
        file.write_bytes(b'.item{width:1px}')
        os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        self.assertEqual(re.search(rb'/style\.css\?v=([0-9a-f]{64})', self.get('/')[2])[1].decode(), old_version)

    def test_gzip_validator_is_for_encoded_bytes(self):
        payload = b'const longValue = "' + b'a' * 2048 + b'";'
        (self.web / 'app.js').write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        url = '/app.js?v=' + digest
        plain = self.get(url)
        zipped = self.get(url, {'Accept-Encoding': 'gzip'})
        self.assertEqual(gzip.decompress(zipped[2]), plain[2])
        self.assertNotEqual(zipped[1]['ETag'], plain[1]['ETag'])
        self.assertEqual(self.get(url, {'Accept-Encoding': 'gzip', 'If-None-Match': plain[1]['ETag']})[0], 200)
        self.assertEqual(self.get(url, {'Accept-Encoding': 'gzip', 'If-None-Match': zipped[1]['ETag']})[0], 304)

    def test_literal_js_dependency_changes_parent_version(self):
        (self.web / 'app.js').write_bytes(b"const icon='/icon.png';")
        first = re.search(rb'/app\.js\?v=([0-9a-f]{64})', self.get('/')[2])[1]
        self.assertIn(b'/icon.png?v=', served_asset_bytes(self.web, '/app.js'))
        (self.web / 'icon.png').write_bytes(b'PNG-changed')
        second = re.search(rb'/app\.js\?v=([0-9a-f]{64})', self.get('/')[2])[1]
        self.assertNotEqual(first, second)
        self.assertEqual(self.get('/app.js?v=' + first.decode())[1]['Cache-Control'], 'no-cache')

    def test_unknown_query_and_bad_host_do_not_gain_immutable_cache(self):
        digest = hashlib.sha256(b'console.log("ready")').hexdigest()
        self.assertEqual(self.get('/app.js?v=' + digest + '&other=x')[1]['Cache-Control'], 'no-cache')
        self.assertEqual(self.get('/app.js?v=' + digest + '&other=')[1]['Cache-Control'], 'no-cache')
        self.assertEqual(self.get('/app.js?v=&v=' + digest)[1]['Cache-Control'], 'no-cache')
        self.assertEqual(self.get('/app.js?bridge-v=' + digest)[1]['Cache-Control'], 'no-cache')
        status, _, _ = self.get('/app.js?v=' + digest, {'Host': 'attacker.example'})
        self.assertEqual(status, 403)
        self.assertEqual(self.get('/api/auth')[1]['Cache-Control'], 'no-store')

    def test_startup_retry_keys_preserve_asset_bytes_csp_and_content_version(self):
        digest = current_version(self.web, '/app.js')
        original = self.get('/app.js?v=' + digest)
        self.assertIn('immutable', original[1]['Cache-Control'])
        for attempt in (2, 3):
            retry = self.get('/app.js?v=' + digest + '&bridge_retry=fixture-' + str(attempt))
            self.assertEqual((retry[0], retry[2]), (200, original[2]))
            self.assertEqual(retry[1]['ETag'], original[1]['ETag'])
            self.assertEqual(retry[1]['Content-Type'], original[1]['Content-Type'])
            self.assertEqual(retry[1]['Content-Security-Policy'], original[1]['Content-Security-Policy'])
            self.assertEqual(retry[1]['Cache-Control'], 'no-cache')


if __name__ == '__main__':
    unittest.main()
