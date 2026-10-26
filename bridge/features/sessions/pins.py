"""Bridge display preferences, independent of native Codex pins."""
import json
import threading
import uuid
from pathlib import Path
from bridge.app.lifecycle import private_json


class SessionPins:
    def __init__(self, directory, environment):
        self.path = Path(directory) / 'session-pins.json'
        self.environment = environment
        self.lock = threading.RLock()

    def _read(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict):
            raise ValueError('聊天置顶记录无效')
        return value

    def identifiers(self):
        with self.lock:
            return tuple(self._read().get(self.environment, []))

    def set(self, identifier, pinned):
        uuid.UUID(identifier)
        if not isinstance(pinned, bool):
            raise ValueError('聊天置顶开关无效')
        with self.lock:
            value = self._read()
            identifiers = set(value.get(self.environment, []))
            if pinned:
                identifiers.add(identifier)
            else:
                identifiers.discard(identifier)
            value[self.environment] = sorted(identifiers)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_json(self.path, value)
        return {'id': identifier, 'bridgePinned': pinned}
