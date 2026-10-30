"""Serialize each host's operations while keeping account changes exclusive."""
from contextlib import contextmanager
import threading


class OperationGate:
    def __init__(self):
        self.condition = threading.Condition(threading.RLock())
        self.exclusive = None
        self.depth = 0
        self.active = {}

    @contextmanager
    def host(self, host):
        owner = threading.get_ident()
        with self.condition:
            self.condition.wait_for(lambda: self.exclusive in (None, owner) and
                                    (host not in self.active or self.active[host][0] == owner))
            previous = self.active.get(host, (owner, 0))
            self.active[host] = owner, previous[1] + 1
        try:
            yield
        finally:
            with self.condition:
                depth = self.active[host][1] - 1
                if depth:
                    self.active[host] = owner, depth
                else:
                    del self.active[host]
                self.condition.notify_all()

    def __enter__(self):
        owner = threading.get_ident()
        with self.condition:
            self.condition.wait_for(lambda: self.exclusive in (None, owner) and
                                    all(value[0] == owner for value in self.active.values()))
            self.exclusive = owner
            self.depth += 1
        return self

    def __exit__(self, *args):
        with self.condition:
            self.depth -= 1
            if not self.depth:
                self.exclusive = None
            self.condition.notify_all()
