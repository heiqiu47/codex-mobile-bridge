"""One opt-in setting shared by local control and authenticated mobile clients."""
import threading
from pathlib import Path

from bridge.features.auth.auth import session_file_lock
from bridge.features.notifications.channels import read_json, write_json


def settings(directory, value=None):
    path = Path(directory) / 'network-adaptation.json'
    if value is not None:
        if not isinstance(value, dict) or set(value) != {'enabled'} or type(value['enabled']) is not bool:
            raise ValueError('网络变化自动恢复开关无效')
        with session_file_lock(path):
            write_json(path, value)
    saved = read_json(path, {})
    return {'enabled': isinstance(saved, dict) and saved.get('enabled') is True}


class NetworkAdaptation:
    def __init__(self, directory, monitor):
        self.directory = Path(directory)
        self.monitor = monitor
        self.lock = threading.RLock()

    def public(self):
        return {**self.monitor.status(), 'running': True}

    def control(self, value):
        if not isinstance(value, dict):
            raise ValueError('网络变化自动恢复请求无效')
        if value == {'action': 'status'}:
            return self.public()
        if (set(value) != {'action', 'enabled'} or value['action'] != 'set'
                or type(value['enabled']) is not bool):
            raise ValueError('网络变化自动恢复请求无效')
        with self.lock:
            old = settings(self.directory)
            settings(self.directory, {'enabled': value['enabled']})
            try:
                self.monitor.set_enabled(value['enabled'])
            except Exception:
                settings(self.directory, old)
                raise
            return self.public()
