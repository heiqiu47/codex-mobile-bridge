"""Exact Claude WSL account write gate; only explicit switches may release stdin."""
from contextlib import contextmanager
import json
import subprocess


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
def account_guard(bridge, provider, row, *, read_only=False, release_idle=False):
    if provider != 'claude':
        yield
        return
    manager = bridge.desktop_sessions
    registry = manager.claude_wsl
    remote = manager.adapters['claude'].remote_cli.wsl
    # Match normal writes/toggles: manager -> registration -> remote -> receipts.
    scope = manager.locks['claude'] if read_only else manager._changing('claude', rebind=False)
    with scope, registry.lock, remote.lock:
        releasable = []
        if remote.refreshing:
            raise ValueError('WSL Claude Code 列表正在刷新，请稍后重试')
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
                    if (not release_idle or getattr(owned, 'error', None) or
                            getattr(owned, 'native', None) != metadata.get('nativeId') or
                            getattr(owned, 'origin', None) != metadata.get('origin') or
                            getattr(owned, 'cwd', None) != metadata.get('cwd') or
                            not metadata.get('nativeId') or not metadata.get('origin') or not metadata.get('cwd') or
                            (getattr(owned, 'preflight', None) or {}).get('status') != 'ready' or
                            owned.preflight.get('cwd') != metadata['cwd']):
                        raise ValueError('此 WSL Claude Code 仍运行，无法保证重新载入认证')
                    releasable.append((sid, owned, dict(metadata)))
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
        def release():
            if read_only:
                raise ValueError('只读检查不能释放 WSL Claude Code 执行器')
            # Called only after the account worker's fresh identity preflight.
            # No signals or process-name matching: EOF affects only the pipe
            # created for this exact gateway-owned stream-json executor.
            for sid, owned, metadata in releasable:
                with owned.condition:
                    if (remote.owned.get(sid) is not owned or remote.index.get(sid) != metadata or
                            owned.active or owned.pending or owned.error):
                        raise ValueError('WSL Claude Code 状态已变化，账号尚未切换')
            if continuation:
                remote.prepare_account_switch(row['id'], release.identity)
            for sid, owned, _ in releasable:
                try:
                    if owned.process.poll() is None:
                        owned.process.stdin.close()
                        owned.process.wait(timeout=5)
                    if owned.process.poll() is None:
                        raise ValueError('WSL Claude Code 尚未退出，账号尚未切换')
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise ValueError('WSL Claude Code 尚未退出，账号尚未切换；请检查原会话') from exc
                remote.owned.pop(sid, None)
        pending = remote.continuation_pending.get(row['id'])
        continuation = release_idle and (bool(pending) or any(
            metadata.get('host') == row['id'] and metadata.get('nativeId') for metadata in remote.index.values()))
        release.releasable = bool(releasable)
        def complete(identity):
            if not continuation:
                return []
            # Recovery may finish on a later account refresh; invalidate manager
            # read caches without rebinding any native session or sending input.
            with manager._changing('claude', rebind=False):
                return remote.complete_account_switch(row['id'], identity)
        release.after_switch = complete
        release.recovery_identity = pending.get('appliedIdentity') if pending and not releasable else None
        yield release if releasable or continuation else None
