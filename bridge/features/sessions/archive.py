"""Durable archive receipts: uncertain native mutations are never replayed."""
import json
import threading
import uuid
from pathlib import Path
from bridge.app.lifecycle import private_json
from bridge.features.sessions.create import ArchiveNotSent, ArchiveRejected


class ArchiveCommands:
    def __init__(self, directory):
        self.path = Path(directory) / 'session-archives.json'
        self.lock = threading.RLock()

    def perform(self, identifier, archived, request_id, read, dispatch):
        uuid.UUID(identifier)
        if not isinstance(request_id, str):
            raise ValueError('归档请求标识无效')
        uuid.UUID(request_id)
        if not isinstance(archived, bool):
            raise ValueError('聊天归档设置无效')
        with self.lock:
            entries = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
            before = read()
            old = entries.get(request_id)
            if old and (old['id'] != identifier or old['archived'] != archived):
                raise ValueError('相同请求标识不能用于不同操作')
            for entry in entries.values():
                if entry['id'] == identifier and entry['status'] == 'unknown':
                    if bool(before.get('archived')) != entry['archived']:
                        raise ValueError('此前归档操作仍待核对；旧记录不会自动清除或重发，请先在原客户端核对')
                    entry['status'] = 'confirmed'
            if old:
                private_json(self.path, entries)
                return dict(old)
            result = {'id': identifier, 'archived': archived, 'status': 'confirmed'}
            if bool(before.get('archived')) == archived:
                return result
            # Validation and fresh runtime checks happen before persisting intent.
            call = dispatch(before)
            entries[request_id] = {**result, 'status': 'unknown'}
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_json(self.path, entries)
            try:
                call()
            except ArchiveRejected as exc:
                try:
                    after = read()
                except Exception:
                    raise ValueError('归档结果待核对，请检查原聊天；不会重复提交') from exc
                flags = before.get('_archiveFlags')
                if isinstance(flags, dict) and flags and flags == after.get('_archiveFlags'):
                    del entries[request_id]
                    private_json(self.path, entries)
                    raise
                raise ValueError('归档结果待核对，请检查原聊天；不会重复提交') from exc
            except ArchiveNotSent:
                del entries[request_id]
                private_json(self.path, entries)
                raise
            except Exception as exc:
                raise ValueError('归档结果待核对，请检查原聊天；不会重复提交') from exc
            after = read()
            if bool(after.get('archived')) != archived:
                raise ValueError('归档结果待核对，请刷新原聊天；不会重复提交')
            entries[request_id] = result
            private_json(self.path, entries)
            return result
