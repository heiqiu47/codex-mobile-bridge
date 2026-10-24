"""Registered-environment account routing, isolated from native local accounts."""
import contextlib
import json
from pathlib import Path
import re
import threading

from bridge.clients.codex.catalog import ModelStore
from bridge.features.accounts.wsl_account_models import WslAccountModels
from bridge.platforms.windows import wsl
from bridge.features.accounts.wsl_account_payload import worker_source
from bridge.features.accounts.wsl_account_worker import ERROR_MESSAGES


class WslAccounts:
    def __init__(self, bridge):
        self.bridge = bridge
        self.lock = threading.RLock()
        self.closed = False
        self.models_store = ModelStore(Path(bridge.data_dir)/'wsl-accounts')
        self.model_catalog = WslAccountModels(self)

    def _registry(self, provider):
        if provider == 'codex':
            registry = getattr(self.bridge, 'entries', None)
        elif provider == 'claude':
            registry = getattr(getattr(self.bridge, 'desktop_sessions', None), 'claude_wsl', None)
        else:
            raise ValueError('WSL 客户端无效')
        if registry is None:
            raise ValueError('此网关不支持 WSL 账号')
        return registry

    def _row(self, provider, identifier, *, enabled=False):
        pattern = r'wsl:[0-9a-f]{32}' if provider == 'codex' else r'wsl-claude:[0-9a-f]{32}'
        if not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
            raise ValueError('WSL 入口身份无效')
        registry = self._registry(provider)
        row = next((dict(row) for row in registry.entries if row.get('id') == identifier), None)
        if row is None or (enabled and not row.get('enabled', True)):
            raise ValueError('WSL 入口未登记或已关闭')
        # Registration files are not an authorization to retarget another path.
        if provider == 'codex':
            from bridge.features.endpoints.registry import entry_id
            expected = entry_id(row['distribution'], row['user'], row['home'])
        else:
            from bridge.clients.claude.wsl import entry_id
            expected = entry_id(row['distribution'], row['user'], row['configDir'])
        if expected != identifier:
            raise ValueError('WSL 登记身份已变化')
        return row

    @staticmethod
    def _target(row):
        return {'distribution': row['distribution'], 'user': row['user'],
                'configDir': row.get('configDir', row.get('home'))}

    def environments(self, provider):
        registry = self._registry(provider)
        running = set(wsl.running_distributions())
        with registry.lock:
            rows = [{**self._target(row), 'id': row['id'], 'label': row['label'],
                     'enabled': row.get('enabled', True), 'running': row['distribution'] in running}
                    for row in registry.entries]
        return {'provider': provider, 'environments': rows}

    def _call(self, provider, row, request):
        payload = {**request, 'provider': provider, 'directory': self._target(row)['configDir']}
        # wsl.read passes all source bytes exclusively through subprocess stdin;
        # neither credentials nor the request are placed in process arguments.
        source = worker_source()
        source += '\ntry:\n value=execute(json.loads('+repr(json.dumps(payload, ensure_ascii=False))+'))\n print(json.dumps({"ok":True,"value":value}))\n'
        source += 'except AccountError as error:\n code=next((key for key,message in ERROR_MESSAGES.items() if message==str(error)),"failed")\n print(json.dumps({"ok":False,"errorCode":code}))\nexcept Exception:\n print(json.dumps({"ok":False,"errorCode":"failed"}))\n'
        result = wsl.read(row['distribution'], source, row['user'], timeout=25, allow_start=False)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise ValueError(ERROR_MESSAGES.get(result.get('errorCode'), ERROR_MESSAGES['failed']) if isinstance(result, dict) else ERROR_MESSAGES['failed'])
        return result['value']

    def _public(self, provider, row, value):
        return {**value, 'provider': provider, 'entry': row['id'], 'target': self._target(row),
                'sharedWithDesktop': False}

    def read(self, provider, entry):
        with self.lock:
            if self.closed:
                raise ValueError('网关正在停止')
            registry = self._registry(provider)
            with registry.lock:
                row = self._row(provider, entry)
                if row['distribution'] not in wsl.running_distributions():
                    return self._public(provider, row, {'available': False, 'identity': None, 'accounts': [],
                        'activeId': None, 'blockers': ['WSL 已停止，请在电脑端启动后查看账号'],
                        'capabilities': {'save': False, 'import': False, 'switch': False, 'models': False}})
                value = self._call(provider, row, {'action': 'read'})
                if not row.get('enabled', True):
                    value['blockers'].append('此 WSL 入口已关闭')
                    value['capabilities'] = {key: False for key in value['capabilities']}
                return self._public(provider, row, value)

    @contextlib.contextmanager
    def _guard(self, provider, row):
        with contextlib.ExitStack() as locks:
            registry = self._registry(provider)
            if provider == 'codex':
                endpoint = getattr(registry, 'bridges', {}).get(row['id'])
                if endpoint is not None:
                    locks.enter_context(endpoint.write_lock)
                    locks.enter_context(endpoint.lock)
                    if any(receipt.get('result', {}).get('status') in ('queued', 'unknown', 'pending')
                           for receipt in endpoint.receipts.values()):
                        raise ValueError('此 WSL 接入存在排队或结果待核对的操作')
                    if endpoint.server is not None and not endpoint.server.closed:
                        raise ValueError('此 WSL 共享服务仍连接，无法保证重新载入认证；请先退出原服务')
                    for session in endpoint.live.values():
                        if session.activating or session.refreshing or session.loading:
                            raise ValueError('此 WSL 会话状态尚未核验')
                # Persisted unresolved writes also block after a gateway restart.
                path = Path(registry.directory)/row['id'][4:]/'operations.json'
                if path.exists():
                    receipts = json.loads(path.read_text(encoding='utf-8'))
                    if any(item.get('result', {}).get('status') in ('queued', 'unknown', 'pending') for item in receipts.values()):
                        raise ValueError('此 WSL 接入存在排队或结果待核对的操作')
            hook = getattr(self.bridge, 'wsl_account_guard', None)
            if hook and provider == 'codex':
                locks.enter_context(hook(provider, row))
            yield

    @contextlib.contextmanager
    def _change_scope(self, provider, entry, action):
        registry = self._registry(provider)
        with contextlib.ExitStack() as locks:
            if provider == 'claude' and action == 'switch':
                with registry.lock:
                    row = self._row(provider, entry, enabled=True)
                hook = getattr(self.bridge, 'wsl_account_guard', None)
                if hook is None:
                    raise ValueError('WSL Claude Code 操作记录保护尚不可用')
                # Manager mutation lock precedes registry/remote locks, matching
                # normal Claude sends. The hook rechecks target registration.
                locks.enter_context(hook(provider, row))
            locks.enter_context(registry.lock)
            yield

    def change(self, value, desktop=False):
        if not isinstance(value, dict):
            raise ValueError('WSL 账号请求无效')
        allowed = {'provider', 'entry', 'action', 'id', 'name', 'baseUrl', 'model', 'apiKey', 'authScheme',
                   'expectedIdentity', 'sourceId', 'sourceIdentity', 'refresh'}
        if set(value)-allowed:
            raise ValueError('WSL 账号请求包含未知字段')
        provider, entry, action = value.get('provider'), value.get('entry'), value.get('action')
        if action not in ('read', 'save-api', 'import-api', 'import-current', 'import-sources', 'switch', 'delete', 'rename', 'models'):
            raise ValueError('WSL 账号操作不支持')
        if not desktop and action not in ('read', 'switch', 'models'):
            raise ValueError('请在电脑端管理 WSL 账号凭据')
        if not desktop and any(key in value for key in ('apiKey', 'sourceId', 'sourceIdentity', 'baseUrl', 'authScheme', 'name', 'model')):
            raise ValueError('浏览器不能保存或导入 WSL 凭据')
        if action == 'models':
            return self.model_catalog.get(value)
        with self.lock:
            if self.closed:
                raise ValueError('网关正在停止')
            registry = self._registry(provider)
            with self._change_scope(provider, entry, action):
                row = self._row(provider, entry, enabled=action != 'read')
                if action == 'read':
                    return self.read(provider, entry)
                if action == 'import-sources':
                    return self._public(provider, row, {'sources': self.bridge.wsl_account_sources(provider)})
                if row['distribution'] not in wsl.running_distributions():
                    raise ValueError('WSL 已停止，请在电脑端启动后操作')
                request = dict(value)
                if action == 'import-api':
                    request.update(self.bridge.wsl_account_import(provider, value))
                    request['action'] = 'save-api'
                with self._guard(provider, row) if action == 'switch' else contextlib.nullcontext():
                    result = self._call(provider, row, request)
                return self._public(provider, row, result)

    def close(self):
        with self.lock:
            self.closed = True
        self.model_catalog.close()
