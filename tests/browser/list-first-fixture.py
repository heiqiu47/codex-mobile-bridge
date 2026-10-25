"""Isolated real-page startup fixture. No real gateway, credentials or model calls.

?case=first|cached|blocked|slow|identity changes only synthetic reads.
Static resources use the production versioned URLs and HTTP cache policy.
"""
import gzip
import json
import sys
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bridge.api.assets import STATIC, served_asset_bytes  # noqa: E402

PAYLOADS = {p: served_asset_bytes(ROOT / 'web', p) for p in STATIC}
state = {'case': 'first', 'requests': Counter(), 'writes': []}
SID = '12345678-1234-4234-9234-123456789012'
PROBE = b"""window.__listProbe={events:[],errors:[]};
addEventListener('error',e=>{if(e.target===window)__listProbe.errors.push(e.message)});
new MutationObserver(()=>{const n=document.querySelector('#sessions .session strong');const status=document.getElementById('bootstrap-status');const stamp=(status?.hidden?'ready':'pending')+'|'+(n?.textContent||'');if(__listProbe.events.at(-1)?.stamp!==stamp)__listProbe.events.push({stamp,ms:Math.round(performance.now())});}).observe(document,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});"""



class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def output(self, body, mime='application/json', status=200, cache=False):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        body = gzip.compress(body)
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=31536000, immutable' if cache else 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/':
            state.update(case=parse_qs(urlsplit(self.path).query).get('case', ['first'])[0], requests=Counter(), writes=[])
        state['requests'][path] += 1
        case = state['case']
        if path == '/__probe.js':
            return self.output(PROBE, 'text/javascript')
        if path == '/__state':
            return self.output(state)
        if path == '/api/auth':
            return self.output({'authenticated': True, 'csrf': 'synthetic', 'draftIdentity': 'synthetic', 'listCacheIdentity': ('b' if case == 'identity' else 'a') * 64, 'computer': {'name': 'Startup fixture'}, 'uiLanguage': 'zh'})
        if path == '/api/clients':
            if case == 'cached':
                time.sleep(5)
            return self.output({'clients': [{'id': 'codex', 'name': 'Codex', 'enabled': True, 'connected': True, 'installed': True, 'running': True, 'configured': True, 'selectable': True}]})
        if path == '/api/sessions':
            if case in ('cached', 'identity'):
                time.sleep(5)
            return self.output({'sessions': [{'id': SID, 'host': 'local', 'title': 'Cached chat' if case != 'cached' else 'Fresh chat', 'projectName': 'Synthetic', 'projectKey': 'test', 'cwd': '/synthetic', 'recency': 1000000, 'access': {'source': 'desktop'}}], 'complete': True, 'remoteHosts': [], 'availableSources': ['desktop']})
        if path == '/api/accounts':
            return self.output({'accounts': [], 'activeIds': []})
        if path == '/api/account':
            return self.output({'visible': False})
        if path.startswith('/api/'):
            return self.output({})
        if case == 'blocked' and any(s in path for s in ('katex', 'xterm', 'source-view', 'pdf-preview')):
            return self.output({}, status=503)
        if path not in PAYLOADS:
            return self.output({}, status=404)
        if case == 'slow' and path.endswith('.js'):
            time.sleep(0.3)
        return self.output(PAYLOADS[path].replace(b'<head>', b'<head><script src="/__probe.js"></script>', 1) if path == '/' else PAYLOADS[path], STATIC[path][1], cache=path not in ('/', '/index.html') and 'v=' in self.path)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        state['writes'].append(urlsplit(self.path).path)
        if self.path == '/api/activity':
            return self.output({'sessions': []})
        return self.output({'error': 'No writes allowed in this fixture'}, status=405)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    print(f'http://127.0.0.1:{server.server_port}', flush=True)
    server.serve_forever()
