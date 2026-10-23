"""Runtime adaptation for LAN listeners, published entries, and Quick Tunnel."""
import json
import logging
import ipaddress
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from bridge.features.network.interfaces import (
    eligible_lan_addresses,
    enumerate_interfaces,
    network_signature,
)


LOGGER = logging.getLogger(__name__)


def _write_status(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)


class DynamicListenerManager:
    """Own dynamic LAN listeners and keep their HTTP origins in sync."""

    def __init__(self, root, port, bridge, config, web_dir, server_factory):
        self.root = root
        self.port = port
        self.bridge = bridge
        self.config = config
        self.web_dir = web_dir
        self.server_factory = server_factory
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

    def _set_origins(self, addresses):
        new_origins = {f'http://{address}:{self.port}' for address in addresses}
        preserved = set()
        for origin in self.root.origins:
            parsed = urlsplit(origin)
            try:
                loopback = parsed.scheme == 'http' and (
                    (parsed.hostname or '').lower() == 'localhost' or
                    ipaddress.ip_address(parsed.hostname).is_loopback
                ) and parsed.port == self.port
            except (ValueError, TypeError):
                loopback = False
            if parsed.scheme == 'https' or loopback:
                preserved.add(origin)
        next_origins = preserved | new_origins
        next_hosts = {urlsplit(origin).netloc for origin in next_origins}
        self.root.origins.clear()
        self.root.origins.update(next_origins)
        self.root.hosts.clear()
        self.root.hosts.update(next_hosts)

    def _start(self, address):
        listener = self.server_factory((address, self.port), self.bridge, self.config,
                                       self.web_dir, shared=self.root)
        thread = threading.Thread(target=listener.serve_forever,
                                  kwargs={'poll_interval': 0.5},
                                  name='gateway-lan-' + address, daemon=True)
        thread.start()
        return listener, thread

    def _close(self, entry):
        listener, thread = entry
        listener.shutdown()
        thread.join(timeout=3)
        listener.server_close()

    def apply(self, addresses):
        desired = list(dict.fromkeys(addresses))
        with self.lock:
            previous = list(self.active)
            errors = []
            started = []
            for address in desired:
                if address in self.listeners:
                    continue
                try:
                    entry = self._start(address)
                    self.listeners[address] = entry
                    started.append(address)
                    self.configure(entry[0])
                except OSError as exc:
                    errors.append(f'{address}: {exc}')
            if errors:
                # Never publish a partial replacement. Roll back listeners that
                # were newly opened, and keep the previous working listeners.
                for address in list(started):
                    if address in previous:
                        continue
                    entry = self.listeners[address]
                    try:
                        self._close(entry)
                        del self.listeners[address]
                    except OSError:
                        pass
                self.active = sorted(self.listeners)
                self.error = '; '.join(errors)
                self._set_origins(self.active)
                return list(self.active), self.error
            # Publish the complete replacement only after every listener is live.
            self._set_origins(desired)
            for address in list(self.listeners):
                if address in desired:
                    continue
                entry = self.listeners[address]
                try:
                    self._close(entry)
                    del self.listeners[address]
                except OSError as exc:
                    errors.append(f'{address}: {exc}')
            self.active = sorted(self.listeners)
            self.error = '; '.join(errors)
            if errors:
                return list(self.active), self.error
            self._set_origins(self.active)
            return list(self.active), self.error

    def addresses(self):
        with self.lock:
            return list(self.active)

    def error_message(self):
        with self.lock:
            return self.error

    def close(self):
        failures = []
        with self.lock:
            for address in list(self.listeners):
                entry = self.listeners[address]
                try:
                    self._close(entry)
                    del self.listeners[address]
                except OSError as exc:
                    failures.append(f'{address}: {exc}')
            self.active = sorted(self.listeners)
            self.error = '; '.join(failures)
            self._set_origins(self.active)


class RuntimeNetworkMonitor:
    """Apply stable network changes and publish a diagnostic snapshot."""

    def __init__(self, data_dir, preferences, port, manager, instance_id,
                 enumerator=None, interval=2.0, stability=6.0,
                 route_enumerator=None, clock=time.monotonic, pid=None):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir/'network-status.json'
        self.preferences = preferences
        self.port = port
        self.manager = manager
        self.instance_id = str(instance_id or '')
        self.enumerator = enumerator or enumerate_interfaces
        self.route_enumerator = route_enumerator or network_signature
        self.interval = interval
        self.stability = stability
        self.clock = clock
        self.pid = pid
        self.closed = threading.Event()
        self.worker = None
        self.lock = threading.RLock()
        self.pending = None
        self.pending_since = None
        self.pending_route = None
        self.pending_route_since = None
        self.route_signature = None
        self.route_since = None
        self.interfaces = []
        self.active = []
        self.network_changed = None
        self.last_status_key = None
        self.last_status_write = 0.0

    def _desired(self):
        selected = self.preferences.get('lanInterfaces')
        if not self.preferences.get('lan'):
            return []
        if selected is None:
            return eligible_lan_addresses(self.interfaces)
        wanted = set(selected)
        return sorted({address for row in self.interfaces if row['id'] in wanted
                       for address in row.get('addresses', [])})

    def _route_signature(self):
        # Route fixtures may return a mutable dict; snapshots must not alias it.
        value = self.route_enumerator(self.interfaces)
        return json.loads(json.dumps(value, sort_keys=True)) if value is not None else {}

    def _status(self, pending, pending_since, route_ready):
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
            'stable': bool(route_ready and pending_since is not None),
            'error': str(self.manager.error_message() or ''),
        }

    def scan(self, initial=False):
        rows = self.enumerator()
        with self.lock:
            previous_active = list(self.active)
            previous_route = self.route_signature
            self.interfaces = rows
            desired = self._desired()
            changed = False
            next_route = self._route_signature()
            now = self.clock()
            if self.pending != desired:
                self.pending = desired
                self.pending_since = now
            if self.route_signature != next_route:
                if self.pending_route != next_route:
                    self.pending_route = next_route
                    self.pending_route_since = now
            else:
                self.pending_route = next_route
                self.pending_route_since = self.pending_route_since or now
            lan_ready = initial or self.pending_since is None or now - self.pending_since >= self.stability
            route_ready = initial or self.pending_route_since is None or now - self.pending_route_since >= self.stability
            ready = lan_ready and route_ready
            if route_ready:
                if previous_route != next_route:
                    self.route_signature = next_route
                    changed = True
            if lan_ready:
                self.active, _ = self.manager.apply(desired)
            self.active = self.manager.addresses()
            changed = ready and (changed or self.active != previous_active)
            status = self._status(desired, self.pending_since, route_ready)
            status_key = json.dumps(status, separators=(',', ':'), sort_keys=True)
            should_write = status_key != self.last_status_key or now - self.last_status_write >= 30
            if should_write:
                status['updatedAt'] = int(time.time())
                _write_status(self.path, status)
                self.last_status_key = status_key
                self.last_status_write = now
            if changed and self.network_changed:
                try:
                    self.network_changed()
                except Exception:
                    # Quick Tunnel's supervisor will retry; keep LAN adaptation live.
                    LOGGER.exception('Quick Tunnel network rebuild failed')
            return list(self.active)

    def _run(self):
        while not self.closed.is_set():
            try:
                self.scan()
            except Exception:
                # Enumeration and status writes are non-fatal; preserve listeners.
                LOGGER.exception('Network adaptation scan failed')
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
