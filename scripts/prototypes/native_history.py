"""Opt-in, read-only history experiments. Not imported by the gateway.

The IPC probe only discovers an existing owner and follows/unfollows that owner.
The stored-history probe requires an isolated copy, never the user's CODEX_HOME.
Results contain counts/timings, not message bodies or credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bridge.clients.codex.ipc import DesktopIPC, IPCError

PAGE_METHODS = {'thread/turns/list', 'thread/items/list'}


def read_params(method, params):
    """Reject writes, activation and implicit full-history hydration at the edge."""
    if method not in PAGE_METHODS | {'thread/read', 'thread/loaded/list'}:
        raise ValueError('Only explicit history reads are allowed')
    allowed = {'threadId', 'cursor', 'limit', 'sortDirection', 'turnId', 'itemsView'}
    if method == 'thread/loaded/list':
        allowed = set()
    elif method == 'thread/read':
        allowed = {'threadId', 'includeTurns'}
        if params.get('includeTurns') is not False:
            raise ValueError('Full-history reads are not allowed')
    if set(params) - allowed:
        raise ValueError('Unexpected read parameter')
    if method != 'thread/loaded/list' and not params.get('threadId'):
        raise ValueError('A thread identity is required')
    if method in PAGE_METHODS:
        if type(params.get('limit')) is not int or not 1 <= params['limit'] <= 100:
            raise ValueError('Explicit bounded page size is required')
        if params.get('sortDirection') not in ('asc', 'desc'):
            raise ValueError('Explicit page direction is required')
        if method == 'thread/turns/list' and params.get('itemsView') != 'notLoaded':
            raise ValueError('Turns must omit bodies; fetch items separately')
    return params


class MeasuredIPC(DesktopIPC):
    # These native app-server reads are intentionally capability probes on IPC.
    # A rejection is recorded; it does not enable a complete-history fallback.
    VERSIONS = {k: DesktopIPC.VERSIONS[k] for k in ('initialize', 'thread-owner-discovery')}
    VERSIONS.update({k: 0 for k in PAGE_METHODS})

    def __init__(self, path):
        self.frames = []
        self.last_frame = None
        self.waiting = threading.Event()
        self.target = None
        self.started = 0
        self.result = None
        self.sent = []
        super().__init__(path, self.event, lambda: None)

    def _send(self, message):
        method = message.get('method')
        if method in PAGE_METHODS:
            read_params(method, message['params'])
        elif method not in ('initialize', 'thread-owner-discovery',
                            'thread-stream-following-changed') and message.get('type') != 'client-discovery-response':
            raise ValueError('IPC operation is outside the read-only experiment')
        self.sent.append(method or message.get('type'))
        return super()._send(message)

    def _exact(self, sock, length):
        start = time.perf_counter()
        data = DesktopIPC._exact(sock, length)
        if length != 4:
            self.last_frame = {'bytes': length, 'transferSeconds': time.perf_counter() - start,
                               'receivedAt': time.perf_counter()}
        return data

    def event(self, message):
        params = message.get('params') or {}
        change = params.get('change') or {}
        if (message.get('method') != 'thread-stream-state-changed' or
                params.get('conversationId') != self.target or change.get('type') != 'snapshot'):
            return
        snapshot = change.get('conversationState') or {}
        if snapshot.get('id') != self.target:
            return
        self.result = {**(self.last_frame or {}),
                       'subscribeToDecodedSeconds': time.perf_counter() - self.started,
                       'decodeAndDispatchSeconds': time.perf_counter() - self.last_frame['receivedAt'],
                       'ownerHash': hashlib.sha256(message['sourceClientId'].encode()).hexdigest(),
                       'revision': change.get('revision'), 'stateKeys': sorted(snapshot),
                       'turns': len(snapshot.get('turns', []))}
        self.result.pop('receivedAt', None)
        self.waiting.set()

    def measure(self, thread_id, owner, timeout=30):
        self.target, self.result = thread_id, None
        self.waiting.clear()
        self.started = time.perf_counter()
        try:
            self.follow(thread_id, owner)
            if not self.waiting.wait(timeout):
                return {'error': 'snapshot-timeout', 'seconds': time.perf_counter() - self.started}
            return self.result
        finally:
            self.follow(thread_id, owner, False)
            self.target = None


class StoredReader:
    """Use the installed native paging API on copied history, never attach/resume."""
    MAX_FRAME = 32 * 1024 * 1024

    def __init__(self, executable, home):
        home = Path(home).resolve()
        if not home.is_relative_to(ROOT / '.tmp') or not (home / '.history-probe-copy').is_file():
            raise ValueError('An isolated history copy under project .tmp is required')
        self.metrics, self.counter, self.messages = [], 0, queue.Queue()
        started = time.perf_counter()
        # Keep OS launch/locale settings, not API keys or provider overrides.
        env = {key: os.environ[key] for key in (
            'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'LC_CTYPE',
            'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
            'USERPROFILE', 'APPDATA', 'LOCALAPPDATA') if key in os.environ}
        env['CODEX_HOME'] = str(home)
        self.process = subprocess.Popen([str(executable), 'app-server', '--listen', 'stdio://'],
            cwd=home, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self._request('initialize', {'clientInfo': {'name': 'history_readonly_probe', 'version': '0.1'},
                'capabilities': {'experimentalApi': True}})
            self.process.stdin.write(b'{"method":"initialized"}\n')
            self.process.stdin.flush()
            self.start_seconds = time.perf_counter() - started
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(self.MAX_FRAME + 1)
                if not line:
                    break
                if len(line) > self.MAX_FRAME:
                    self.messages.put(ValueError('Native response exceeds probe budget'))
                    return
                start = time.perf_counter()
                value = json.loads(line)
                self.messages.put((value, len(line), time.perf_counter() - start))
        except Exception as exc:
            self.messages.put(exc)
        finally:
            self.messages.put(EOFError('Native reader closed'))

    def request(self, method, params):
        return self._request(method, read_params(method, params))

    def _request(self, method, params):
        self.counter += 1
        key, start = self.counter, time.perf_counter()
        self.process.stdin.write(json.dumps({'id': key, 'method': method, 'params': params}).encode() + b'\n')
        self.process.stdin.flush()
        deadline = start + 30
        while True:
            entry = self.messages.get(timeout=max(.001, deadline - time.perf_counter()))
            if isinstance(entry, Exception):
                raise entry
            value, size, decode = entry
            if value.get('id') != key:
                if time.perf_counter() >= deadline:
                    raise TimeoutError('Native read timed out')
                continue
            metric = {'method': method, 'bytes': size, 'seconds': time.perf_counter() - start,
                      'decodeSeconds': decode}
            if 'error' in value:
                metric['error'] = value['error']
            self.metrics.append(metric)
            if 'error' in value:
                raise ValueError(json.dumps(value['error']))
            return value.get('result', {})

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process.stdout.close()


def stored_pages(reader, thread_id):
    """Two explicit pages, with no hidden traversal or fallback to a full read."""
    meta = reader.request('thread/read', {'threadId': thread_id, 'includeTurns': False})
    thread = meta.get('thread', {})
    if thread.get('id') != thread_id:
        raise ValueError('Native thread identity mismatch')
    turns = reader.request('thread/turns/list', {'threadId': thread_id, 'limit': 2,
        'itemsView': 'notLoaded', 'sortDirection': 'desc'})
    result = {'turnCount': len(turns.get('data', [])), 'pages': []}
    cursor, seen = None, set()
    for _ in range(2):
        params = {'threadId': thread_id, 'limit': 20, 'sortDirection': 'desc'}
        if cursor is not None:
            params['cursor'] = cursor
        page = reader.request('thread/items/list', params)
        ids = [(r.get('turnId'), (r.get('item') or {}).get('id')) for r in page.get('data', [])]
        if any(i in seen for i in ids):
            raise ValueError('Native pages overlap')
        seen.update(ids)
        result['pages'].append({'items': len(ids), 'hasMore': page.get('nextCursor') is not None})
        next_cursor = page.get('nextCursor')
        if next_cursor is None:
            break
        if next_cursor == cursor:
            raise ValueError('Native pagination cursor did not advance')
        cursor = next_cursor
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('ipc', 'stored'))
    parser.add_argument('--thread', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ipc', type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--home', type=Path)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / '.tmp'):
        parser.error('Evidence must be stored under project .tmp')
    result = {'mode': args.mode, 'readOnly': True, 'threads': []}
    if args.mode == 'ipc':
        client = MeasuredIPC(args.ipc)
        try:
            client.connect()
            for thread_id in args.thread:
                owner = client.owner(thread_id)
                record = {'threadId': thread_id, 'ownerHash': hashlib.sha256(owner.encode()).hexdigest()}
                result['threads'].append(record)
                record['snapshot'] = client.measure(thread_id, owner)
                record['pages'] = []
                for method in sorted(PAGE_METHODS):
                    params = {'threadId': thread_id, 'limit': 2, 'sortDirection': 'desc'}
                    if method == 'thread/turns/list':
                        params['itemsView'] = 'notLoaded'
                    start = time.perf_counter()
                    try:
                        reply = client.request(method, params, target=owner, timeout=3)
                        record['pages'].append({'method': method, 'accepted': True,
                            'resultKeys': sorted(reply.get('result', {}))})
                    except IPCError as exc:
                        record['pages'].append({'method': method, 'accepted': False, 'error': str(exc)[:250]})
                    record['pages'][-1]['seconds'] = time.perf_counter() - start
                record['ownerUnchanged'] = client.owner(thread_id) == owner
        finally:
            result['sentMethods'] = client.sent
            client.close()
            args.output.write_text(json.dumps(result, indent=2))
    else:
        client = StoredReader(args.executable, args.home)
        result['isolatedProcessStartSeconds'] = client.start_seconds
        try:
            before = client.request('thread/loaded/list', {})
            for thread_id in args.thread:
                record = {'threadId': thread_id}
                result['threads'].append(record)
                for attempt in range(2):
                    start = len(client.metrics)
                    try:
                        value = stored_pages(client, thread_id)
                        record.setdefault('attempts', []).append(value)
                    except ValueError as exc:
                        record.setdefault('attempts', []).append({'error': str(exc)[:300]})
                    record['attempts'][-1]['metrics'] = client.metrics[start:]
                    if 'error' in record['attempts'][-1]:
                        break
            after = client.request('thread/loaded/list', {})
            result['loadedBeforeCount'] = len(before.get('data', []))
            result['loadedAfterCount'] = len(after.get('data', []))
            result['noThreadLoaded'] = before.get('data') == after.get('data') == []
        finally:
            client.close()
            args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
