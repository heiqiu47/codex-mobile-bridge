"""Runtime adaptation for LAN listeners and published gateway entries."""
import ipaddress
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


def _write_status(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)


class DynamicListenerManager:
    """Own selected-address listeners; a wildcard listener is never rebuilt."""

    def __init__(self, root, port, bridge, config, web_dir, server_factory, wildcard=False):
        self.root = root
        self.port = port
        self.bridge = bridge
        self.config = config
        self.web_dir = web_dir
        self.server_factory = server_factory
        self.wildcard = bool(wildcard)
        self.configure = lambda listener: None
        self.lock = threading.RLock()
        self.listeners = {}
        self.active = []
        self.error = ''
        self._clean_legacy_http_origins()

    def _clean_legacy_http_origins(self):
        # Manual additional origins are HTTPS. Numeric HTTP sources belong to
        # this dynamic owner, so previous-run LAN entries never stay trusted.
        for origin in list(self.root.origins):
            parsed = urlsplit(origin)
            if parsed.scheme != 'http':
                continue
            try:
                host = ipaddress.IPv4Address(parsed.hostname)
            except (ValueError, TypeError):
                continue
            if host.is_loopback or parsed.port != self.port:
                continue
            self.root.origins.discard(origin)
            self.root.hosts.discard(parsed.netloc)

    def _remove_origins(self, addresses):
        for address in addresses:
            origin = f'http://{address}:{self.port}'
            self.root.origins.discard(origin)
            self.root.hosts.discard(urlsplit(origin).netloc)

    def _set_origins(self, addresses):
        new_origins = {f'http://{address}:{self.port}' for address in addresses}
        old_origins = {f'http://{address}:{self.port}' for address in self.active
                       if address not in addresses}
        self.root.origins.update(new_origins)
        self.root.hosts.update({urlsplit(origin).netloc for origin in new_origins})
        for origin in old_origins:
            self.root.origins.discard(origin)
            self.root.hosts.discard(urlsplit(origin).netloc)

    def _start(self, address):
        listener = self.server_factory((address, self.port), self.bridge, self.config,
                                       self.web_dir, shared=self.root)
        thread = threading.Thread(target=listener.serve_forever,
                                  kwargs={'poll_interval': 0.5},
                                  name='gateway-lan-' + address, daemon=True)
        thread.start()
        return listener, thread

    def _close(self, address, entry):
        listener, thread = entry
        listener.shutdown()
        thread.join(timeout=3)
        listener.server_close()

    def apply(self, addresses):
        desired = list(dict.fromkeys(addresses))
        with self.lock:
            previous = list(self.active)
            self._set_origins(desired)
            errors = []
            for address in desired:
                if self.wildcard or address in self.listeners:
                    continue
                try:
                    entry = self._start(address)
                    self.configure(entry[0])
                    self.listeners[address] = entry
                except OSError as exc:
                    errors.append(f'{address}: {exc}')
            if errors:
                # Keep the last working entry while a replacement address is
                # unavailable. Retry happens on the next stable monitor scan.
                self.active = sorted(self.listeners)
                self.error = '; '.join(errors)
                self._remove_origins(set(desired).difference(self.active))
                self._set_origins(self.active)
                return list(self.active), self.error
            for address in list(self.listeners):
                if address in desired:
                    continue
                try:
                    self._close(address, self.listeners.pop(address))
                except OSError as exc:
                    errors.append(f'{address}: {exc}')
            if self.wildcard:
                self.active = desired
            else:
                self.active = sorted(self.listeners)
            self.error = '; '.join(errors)
            self._set_origins(self.active)
            return list(self.active), self.error

    def addresses(self):
        with self.lock:
            return list(self.active)

    def error_message(self):
        with self.lock:
            return self.error

    def close(self):
        with self.lock:
            for address in list(self.listeners):
                try:
                    self._close(address, self.listeners.pop(address))
                except OSError:
                    pass
            self._set_origins([])
            self.active = []


class RuntimeNetworkMonitor:
    """Apply only stable interface changes and publish an audit snapshot."""

    def __init__(self, data_dir, preferences, port, manager, instance_id,
                 enumerator=None, interval=2.0, stability=6.0,
                 clock=time.monotonic, pid=None):
        from bridge.features.network.interfaces import enumerate_interfaces
        self.data_dir = Path(data_dir)
        self.path = self.data_dir/'network-status.json'
        self.preferences = preferences
        self.port = port
        self.manager = manager
        self.instance_id = str(instance_id or '')
        self.enumerator = enumerator or enumerate_interfaces
        self.interval = interval
        self.stability = stability
        self.clock = clock
        self.pid = pid
        self.closed = threading.Event()
        self.worker = None
        self.lock = threading.RLock()
        self.pending = None
        self.pending_since = None
        self.interfaces = []
        self.active = []

    def _desired(self):
        selected = self.preferences.get('lanInterfaces')
        if not self.preferences.get('lan'):
            return []
        if selected is None:
            return sorted({address for row in self.interfaces for address in row['addresses']})
        wanted = set(selected)
        return sorted({address for row in self.interfaces if row['id'] in wanted
                       for address in row['addresses']})

    def _status(self, pending, pending_since, ready):
        selected = self.preferences.get('lanInterfaces')
        return {
            'pid': self.pid,
            'instanceId': self.instance_id,
            'mode': 'off' if not self.preferences.get('lan') else
                    'all' if selected is None else 'selected',
            'selectedInterfaces': [] if selected is None else [str(item) for item in selected],
            'interfaces': self.interfaces,
            'addresses': list(self.active),
            'pendingAddresses': [] if pending is None else list(pending),
            'stable': bool(ready),
            'error': str(self.manager.error_message() or ''),
            'updatedAt': int(time.time()),
            '_pendingSince': pending_since,
        }

    def scan(self, initial=False):
        rows = self.enumerator()
        with self.lock:
            self.interfaces = rows
            desired = self._desired()
            signature = json.dumps(desired, separators=(',', ':'))
            now = self.clock()
            if self.pending != signature:
                self.pending = signature
                self.pending_since = now
            ready = initial or self.pending_since is None or now - self.pending_since >= self.stability
            if ready:
                self.active, _ = self.manager.apply(desired)
            self.active = self.manager.addresses()
            status = self._status(desired, self.pending_since, ready)
            status.pop('_pendingSince', None)
            _write_status(self.path, status)
            return list(self.active)

    def _run(self):
        while not self.closed.is_set():
            try:
                self.scan()
            except Exception:
                # Interface enumeration is read-only; a transient OS error must
                # not stop the gateway or the established listener.
                pass
            self.closed.wait(self.interval)

    def start(self):
        self.worker = threading.Thread(target=self._run, name='network-adaptation', daemon=True)
        self.worker.start()

    def addresses(self):
        with self.lock:
            return list(self.active)

    def close(self):
        self.closed.set()
        if self.worker:
            self.worker.join(timeout=3)
        self.manager.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
