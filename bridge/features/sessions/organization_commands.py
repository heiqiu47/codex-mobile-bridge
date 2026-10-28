"""Persist native sidebar write intent before dispatch; uncertain writes are read-only."""
import json
import threading
import uuid
from pathlib import Path

from bridge.features.sessions.organization import OrganizationNotSent, validate_change
from bridge.features.sessions.create import CreationUnavailable


class OrganizationCommands:
    def __init__(self, directory, save):
        self.path = Path(directory) / 'session-organization.json'
        self.lock = threading.RLock()
        self.save = save

    def native_memberships(self):
        """Explicit native project writes supersede old desktop migration assignments."""
        with self.lock:
            entries = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            return {entry['id'] for entry in entries.values()
                    if entry['change']['kind'] == 'project' and entry['status'] == 'confirmed'}

    def perform(self, identifier, change, read, dispatch):
        uuid.UUID(identifier)
        if not isinstance(change, dict) or set(change) != {'id', 'kind', 'targetId', 'expectedId'}:
            raise ValueError('会话分类设置无效')
        request_id = change['id']
        if not isinstance(request_id, str):
            raise ValueError('会话分类设置无效')
        uuid.UUID(request_id)
        mutation = {key: value for key, value in change.items() if key != 'id'}
        with self.lock:
            entries = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            old = entries.get(request_id)
            if old and (old['id'] != identifier or old['change'] != mutation):
                raise ValueError('相同请求标识不能用于不同操作')
            snapshot = read()
            for entry in entries.values():
                if entry['id'] == identifier and entry['status'] == 'unknown':
                    field = entry['change']['kind'] + 'Id'
                    if (snapshot.get(field) != entry['change']['targetId'] or
                            snapshot.get('identity') != entry['identity']):
                        raise ValueError('此前分类操作仍待核对；不会重复提交，请先在原客户端核对')
                    entry['status'] = 'confirmed'
            if old:
                self.save(self.path, entries)
                return {**snapshot, 'status': old['status']}
            validate_change(snapshot, mutation)
            if snapshot[mutation['kind'] + 'Id'] == mutation['targetId']:
                return snapshot
            entries[request_id] = {'id': identifier, 'change': mutation,
                                   'identity': snapshot['identity'], 'status': 'unknown'}
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.save(self.path, entries)
            try:
                result = dispatch(mutation)
                if (result.get('status') != 'confirmed' or
                        result.get(mutation['kind'] + 'Id') != mutation['targetId'] or
                        result.get('identity') != snapshot['identity']):
                    raise ValueError('原生分类结果待核对，请刷新会话列表')
            except (OrganizationNotSent, CreationUnavailable):
                del entries[request_id]
                self.save(self.path, entries)
                raise
            except Exception as exc:
                raise ValueError('原生分类结果待核对；不会重复提交，请先在原客户端核对') from exc
            entries[request_id]['status'] = 'confirmed'
            self.save(self.path, entries)
            return result
