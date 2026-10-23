"""Cancelable, event-driven socket reader shared by native network adapters."""
import select
import socket
import threading


class SocketNetworkWatcher:
    """Read notifications until close(), with no timer or subprocess polling.

    The callback only wakes the owning monitor. It must not close this watcher
    from inside its callback; close() is called by the monitor control thread.
    """
    def __init__(self, source, callback, relevant):
        self._source = source
        self._callback = callback
        self._relevant = relevant
        self._lock = threading.RLock()
        self._closed = False
        self._wake_read, self._wake_write = socket.socketpair()
        self._thread = threading.Thread(target=self._run, name='network-events', daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._wake_read.close()
            self._wake_write.close()
            raise

    def _run(self):
        try:
            while True:
                try:
                    ready, _, _ = select.select([self._source, self._wake_read], [], [])
                    if self._wake_read in ready:
                        return
                    data = self._source.recv(65536)
                except OSError:
                    return  # The caller's low-frequency scan remains available.
                if not data:
                    return
                if self._relevant(data):
                    with self._lock:
                        if not self._closed:
                            self._callback()
        finally:
            with self._lock:
                self._closed = True
                self._source.close()
                self._wake_read.close()
                self._wake_write.close()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._wake_write.send(b'\0')
        # Wake the blocking select before joining; no socket is closed while
        # another thread is still reading from it.
        self._thread.join()
