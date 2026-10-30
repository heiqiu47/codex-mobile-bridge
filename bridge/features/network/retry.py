"""Demand-driven exponential backoff shared by a remote host's readers."""
from contextlib import contextmanager
import random
import threading
import time


class ConnectionUnavailable(RuntimeError):
    pass


class TransportUnavailable(ConnectionUnavailable):
    pass


_connections = {}
_connections_lock = threading.Lock()


def ssh_connection(alias):
    with _connections_lock:
        if alias not in _connections:
            _connections[alias] = ConnectionRetry(ConnectionUnavailable, TransportUnavailable)
        return _connections[alias]


class ConnectionRetry:
    def __init__(self, unavailable, transport_error, *, clock=time.monotonic, jitter=random.uniform):
        self.unavailable = unavailable
        self.transport_error = transport_error
        self.clock = clock
        self.jitter = jitter
        self.lock = threading.Lock()
        self.failures = 0
        self.retry_at = 0
        self.checking = False
        self.verified = False
        self.generation = 0

    def status(self):
        with self.lock:
            remaining = max(0, self.retry_at - self.clock())
            return {'state': 'checking' if self.checking else 'offline' if self.failures else
                    'online' if self.verified else 'unknown', 'failures': self.failures,
                    'retryAfterSeconds': int(remaining + .999),
                    'nextRetryAt': time.time() + remaining if self.failures else None}

    def check(self):
        with self.lock:
            if self.failures or self.checking:
                raise self.unavailable('SSH 主机暂不可用，正在退避重试；可在账号管理中手动重试。')

    @contextmanager
    def attempt(self, *, manual=False):
        with self.lock:
            if self.checking or self.failures and not manual and self.clock() < self.retry_at:
                raise self.unavailable('SSH 主机暂不可用，正在退避重试；可在账号管理中手动重试。')
            probe = manual or bool(self.failures)
            if probe:
                self.generation += 1
                self.checking = True
            generation = self.generation
        try:
            yield
        except self.transport_error:
            with self.lock:
                if generation == self.generation:
                    self.failures += 1
                    self.retry_at = self.clock() + min(600, 30 * 2 ** min(self.failures - 1, 5) * self.jitter(.8, 1.2))
                    self.generation += 1
            raise
        except Exception:
            # A remote application error is not a failed SSH transport.
            self._reachable(generation)
            raise
        else:
            self._reachable(generation)
        finally:
            if probe:
                with self.lock:
                    self.checking = False

    def _reachable(self, generation):
        with self.lock:
            if generation == self.generation:
                self.failures = 0
                self.retry_at = 0
                self.verified = True
