"""Explicit API-only imports into WSL; native OAuth material never transfers."""
import hashlib
import hmac
import json
import re

from bridge.features.accounts.cli_sync import LocalCliSync


def _identity(source, value):
    return hashlib.sha256(json.dumps([source, value], sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class WslAccountSources:
    def __init__(self, bridge):
        self.bridge = bridge

    def _codex(self, identifier):
        accounts = self.bridge.accounts
        with accounts.lock:
            row = accounts.row(identifier)
            if row['kind'] != 'api':
                raise ValueError('仅支持显式导入已保存 API，官方登录不能复制到 WSL')
            url, key = accounts.api_credentials({'id': identifier, 'baseUrl': row['baseUrl']})
            return {'name': row['name'], 'baseUrl': url, 'apiKey': key,
                    'model': row['model'], 'authScheme': 'bearer'}

    def _claude(self, identifier):
        manager = getattr(self.bridge, 'desktop_sessions', None)
        if manager is None:
            raise ValueError('Claude Desktop 账号管理器不可用')
        store = manager._account_store('claude')
        with store.lock:
            return LocalCliSync(self.bridge).import_desktop_claude(identifier, store=store)

    def sources(self, provider):
        result = []
        if provider == 'codex':
            accounts = self.bridge.accounts
            with accounts.lock:
                ids = [r['id'] for r in accounts.index['accounts'] if r.get('kind') == 'api']
            source = 'desktop-codex'
        elif provider == 'claude':
            manager = getattr(self.bridge, 'desktop_sessions', None)
            if manager is None:
                return []
            store = manager._account_store('claude')
            with store.lock:
                public = store.public()
                current = public.get('current') or {}
                ids = [public['activeId']] if current.get('kind') == 'api' and current.get('saved') else []
            source = 'desktop-claude'
        else:
            raise ValueError('WSL 客户端无效')
        for identifier in ids:
            try:
                value = self._codex(identifier) if provider == 'codex' else self._claude(identifier)
                source_id = source+':'+identifier
                result.append({'id': source_id, 'name': value['name'], 'source': source,
                               'sourceIdentity': _identity(source_id, value)})
            except (OSError, ValueError, KeyError, TypeError):
                # Invalid/changed/unsupported source is not an import candidate.
                continue
        return result

    def import_api(self, provider, request):
        source, expected = request.get('sourceId'), request.get('sourceIdentity')
        prefix = {'codex': 'desktop-codex:', 'claude': 'desktop-claude:'}.get(provider)
        if (not prefix or not isinstance(source, str) or not source.startswith(prefix)
                or not re.fullmatch('[0-9a-f]{32}', source[len(prefix):])
                or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('请选择此客户端已保存的 API 来源并刷新身份')
        identifier = source[len(prefix):]
        value = self._codex(identifier) if provider == 'codex' else self._claude(identifier)
        if not hmac.compare_digest(_identity(source, value), expected):
            raise ValueError('桌面 API 来源已变化，请刷新后重新选择')
        name = request.get('name')
        if name is not None:
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError('接入名称无效')
            value['name'] = name.strip()
        return value


def sources(bridge, provider):
    return WslAccountSources(bridge).sources(provider)


def import_api(bridge, provider, value):
    return WslAccountSources(bridge).import_api(provider, value)
