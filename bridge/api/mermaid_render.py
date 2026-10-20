"""Isolated, fixed Mermaid rendering shell; diagram text is sent by postMessage."""
from pathlib import Path

from bridge.api.assets import current_version

SHELL_PATH = '/mermaid-render-shell'
SHELL_FILE = 'shared/mermaid-render-shell.html'
SCRIPT_PATHS = frozenset(('/vendor/mermaid/mermaid.min.js', '/mermaid-render-frame.js'))
SHELL_CSP = (
    "sandbox allow-scripts; default-src 'none'; "
    "script-src {origin}; style-src 'unsafe-inline'; style-src-attr 'unsafe-inline'; "
    "img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; "
    "object-src 'none'; worker-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'self'"
)


def shell_csp(origin):
    """Use the gateway's validated origin: sandboxed frames have an opaque origin."""
    return SHELL_CSP.format(origin=origin)


def is_public_renderer_script(path, method, destination):
    """Only inert, fixed JS assets may load from the opaque renderer origin."""
    return method == 'GET' and destination == 'script' and path in SCRIPT_PATHS


def shell_bytes(web_dir):
    """Keep scoped relative URLs while invalidating old browser-cached bundles."""
    body = (Path(web_dir) / SHELL_FILE).read_bytes()
    for relative, public in ((b'vendor/mermaid/mermaid.min.js', '/vendor/mermaid/mermaid.min.js'),
                             (b'mermaid-render-frame.js', '/mermaid-render-frame.js')):
        old = b'src="' + relative + b'"'
        new = b'src="' + relative + b'?v=' + current_version(web_dir, public).encode('ascii') + b'"'
        if body.count(old) != 1:
            raise ValueError('Missing fixed Mermaid shell script: ' + public)
        body = body.replace(old, new)
    return body
