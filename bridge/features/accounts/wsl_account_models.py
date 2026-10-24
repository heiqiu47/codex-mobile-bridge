"""Account-bound model metadata with passive cache reads and 12-hour refresh."""
import copy
from concurrent.futures import Future
import threading
import time

from bridge.clients.codex.catalog import ModelStore, MODEL_REFRESH_SECONDS
from bridge.platforms.windows import wsl


class WslAccountModels:
    def __init__(self, owner):
        self.owner = owner
        self.lock = threading.RLock()
        self.reads = {}
        self.timers = {}
        self.closed = False

    def _snapshot(self, request):
        owner = self.owner
        provider, entry = request['provider'], request['entry']
        with owner.lock:
            if owner.closed:
                raise ValueError('网关正在停止')
            registry = owner._registry(provider)
            with registry.lock:
                row = owner._row(provider, entry, enabled=True)
                if row['distribution'] not in wsl.running_distributions():
                    raise ValueError('WSL 已停止，请在电脑端启动后操作')
                snapshot = owner._call(provider, row, {'action': 'read'})
                card = next((card for card in snapshot['accounts'] if card['id'] == request.get('id')), None)
                digest = card.get('modelCatalogIdentity') if card else None
                identity = ModelStore.key('wsl-saved-api', provider, entry, digest) if digest else None
                return row, digest, identity

    def _public(self, row, request, result, record=None, identity=None, error=None):
        value = copy.deepcopy(result)
        if record:
            value['cache'] = {'identity': identity, 'updatedAt': record[0],
                              'state': 'stale' if error or time.time()-record[0] >= MODEL_REFRESH_SECONDS else 'fresh'}
        if error:
            value['modelError'] = error
        return self.owner._public(request['provider'], row, value)

    def get(self, request):
        row, digest, identity = self._snapshot(request)
        if not identity:
            return self._public(row, request, {'models': [], 'modelError': '此接入的模型请使用原 CLI 查看'})
        record = self.owner.models_store.read(identity)
        if record and not request.get('refresh'):
            with self.owner.lock:
                if self.owner.closed:
                    raise ValueError('网关正在停止')
                self._schedule(identity, request, record[0])
                return self._public(row, request, record[1], record, identity)
        with self.lock:
            if self.closed:
                raise ValueError('网关正在停止')
            future = self.reads.get(identity)
            creator = future is None
            if creator:
                future = self.reads[identity] = Future()
        if not creator:
            return copy.deepcopy(future.result())
        try:
            # Registry/control locks are deliberately absent during HTTPS I/O.
            try:
                result = self.owner._call(request['provider'], row, {**request, 'modelIdentity': digest})
            except (OSError, ValueError, TimeoutError):
                result = {'models': [], 'modelError': '模型目录刷新失败，已保留上次结果'}
            with self.owner.lock, self.owner._registry(request['provider']).lock:
                latest, _, latest_identity = self._snapshot(request)
                if latest_identity != identity or result.get('identityChanged'):
                    value = self._public(latest, request, {'models': [], 'modelError': '模型接入已变化，请刷新后重新读取'})
                else:
                    with self.lock:
                        if self.closed:
                            raise ValueError('网关正在停止')
                        if not result.get('modelError'):
                            at = self.owner.models_store.write(identity, result)
                            record = (at, result)
                            self._schedule(identity, request, at, replace=True)
                            value = self._public(row, request, result, record, identity)
                        elif record:
                            self._schedule(identity, request, time.time()-MODEL_REFRESH_SECONDS+300, replace=True)
                            value = self._public(row, request, record[1], record, identity, result['modelError'])
                        else:
                            value = self._public(row, request, result)
            future.set_result(value)
            return copy.deepcopy(value)
        except Exception as error:
            future.set_exception(error)
            # The initiating caller receives the exception directly. Mark it
            # observed as well when there were no concurrent readers.
            future.exception()
            raise
        finally:
            with self.lock:
                if self.reads.get(identity) is future:
                    self.reads.pop(identity, None)

    def _schedule(self, identity, request, at, replace=False):
        with self.lock:
            if replace and identity in self.timers:
                self.timers.pop(identity).cancel()
            if self.closed or identity in self.timers or (not replace and identity in self.reads):
                return
            request = {**request, 'refresh': True}
            def due():
                with self.lock:
                    self.timers.pop(identity, None)
                    if self.closed:
                        return
                try:
                    # A timer cannot refresh a new credential or wake a distro.
                    if self._snapshot(request)[2] == identity:
                        self.get(request)
                except (OSError, ValueError, TimeoutError):
                    pass
            timer = threading.Timer(max(0, at+MODEL_REFRESH_SECONDS-time.time()), due)
            timer.daemon = True
            self.timers[identity] = timer
            timer.start()

    def close(self):
        with self.lock:
            self.closed = True
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()
