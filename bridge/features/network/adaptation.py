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


def migrate_legacy_interfaces(config_path, rows=None):
    """Pin unambiguous legacy IP selections during explicit startup only.

    Keep the legacy fields for rollback. Both files use Desktop.save's config
    lock, so a live UI save cannot be overwritten with an earlier snapshot.
    """
    from bridge.features.network import addresses, interfaces
    config_path = Path(config_path)
    profile_path = config_path.parent / 'desktop.json'
    with session_file_lock(config_path):
        config = read_json(config_path, {})
        profile = read_json(profile_path, {}) if profile_path.is_file() else None
        records = [(config_path, config)]
        if profile is not None:
            records.append((profile_path, profile))
        updates = []
        for path, record in records:
            if 'lanInterfaces' in record or record.get('lanAddresses') is None:
                continue
            legacy = addresses.selected_addresses(record['lanAddresses'])
            # Resume an interrupted migration only when the legacy selections
            # match exactly; never borrow a different profile's access scope.
            peers = [other for _, other in records if other is not record and
                     'lanInterfaces' in other and other.get('lanAddresses') == record['lanAddresses']]
            if not legacy:
                selected = []
            elif peers:
                selected = interfaces.selected_interfaces(peers[0]['lanInterfaces'])
            else:
                if rows is None:
                    rows = interfaces.enumerate_interfaces()
                selected = interfaces.migrate_addresses_to_interfaces(rows, legacy)
            if legacy and not selected:
                continue
            updates.append((path, {**record, 'lanInterfaces': selected}))
        for path, value in updates:
            write_json(path, value)
            if path == config_path:
                config = value
        return config


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
