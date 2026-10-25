"""Exact Claude WSL account write gate; no native calls or receipt mutation."""
from contextlib import contextmanager
import json


def request_scope(manager, provider, action, sid, body):
    """Optional exact WSL attribution; never add preflight to ordinary writes."""
    if provider != 'claude':
        return None
    try:
        host = None
        if action == 'create':
            project = manager.directory_projects.get(body.get('projectKey'))
            if project and project.get('provider') == provider:
                host = project.get('host')
        if host is None:
            remote = getattr(manager.adapters[provider], 'remote_cli', None)
            if isinstance(getattr(remote, 'index', None), dict):
                with remote.lock:
                    metadata = remote.index.get(sid)
                    if isinstance(metadata, dict):
                        host = metadata.get('host')
        if isinstance(host, str) and host.startswith('wsl-claude:'):
            return provider, host, sid
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Attribution failure cannot change the pre-existing dispatch or receipt
        # semantics; it provides no evidence to label a native/local route.
        pass
    return None


@contextmanager
def account_guard(bridge, provider, row, *, read_only=False):
    if provider != 'claude':
        yield
        return
    manager = bridge.desktop_sessions
    registry = manager.claude_wsl
    remote = manager.adapters['claude'].remote_cli.wsl
    # Match normal writes/toggles: manager -> registration -> remote -> receipts.
    scope = manager.locks['claude'] if read_only else manager._changing('claude', rebind=False)
    with scope, registry.lock, remote.lock:
        current = registry.selected(row['id'])
        if any(current.get(key) != row.get(key) for key in ('distribution', 'user', 'configDir')):
            raise ValueError('WSL 登记身份已变化，请刷新')
        for sid, owned in remote.owned.items():
            metadata = remote.index.get(sid)
            if metadata is None:
                # No process attribution means it cannot authorize this switch.
                if owned.process.poll() is None:
                    raise ValueError('WSL Claude Code 运行会话归属尚未核验')
                continue
            if metadata.get('host') != row['id']:
                continue
            with owned.condition:
                if owned.active or owned.pending:
                    raise ValueError('此 WSL Claude Code 有任务或待处理请求')
                if owned.process.poll() is None:
                    raise ValueError('此 WSL Claude Code 仍运行，无法保证重新载入认证')
        with manager.db_lock:
            db = manager._receipts(manager.adapters['claude'])
            # Older receipts have irreversible request hashes and no scope.
            # Preserve them as-is; do not attribute unrelated unknown writes to
            # every WSL environment. New scope rows share receipt insertion tx.
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='request_scopes'").fetchone()
            if exists:
                records = db.execute('SELECT requests.result FROM requests JOIN request_scopes '
                                     'ON requests.id=request_scopes.id WHERE request_scopes.provider=? '
                                     'AND request_scopes.host=?', ('claude', row['id'])).fetchall()
                for (raw,) in records:
                    result = json.loads(raw)
                    if result.get('status') in ('unknown', 'pending', 'queued'):
                        raise ValueError('此 WSL 接入存在排队或结果待核对的操作')
        yield
