"""Small, bounded WebSocket transport for an existing terminal session."""
import base64
import collections
import hashlib
import hmac
import json
import socket
import struct
import threading
import time


GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
MAX_FRAME = 32768


def _read(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            raise EOFError()
        data.extend(part)
    return bytes(data)


def _frame(stream):
    head = _read(stream, 2)
    opcode = head[0] & 15
    if head[0] & 0x70 or not head[0] & 0x80 or not head[1] & 0x80:
        raise ValueError('Invalid WebSocket frame')
    size = head[1] & 127
    if size == 126:
        size = struct.unpack('!H', _read(stream, 2))[0]
        if size < 126: raise ValueError('Nonminimal WebSocket length')
    elif size == 127:
        size = struct.unpack('!Q', _read(stream, 8))[0]
        if size < 65536: raise ValueError('Nonminimal WebSocket length')
    if size > MAX_FRAME or opcode not in (1, 8, 9, 10) or (opcode >= 8 and size > 125):
        raise ValueError('Unsupported WebSocket frame')
    mask = _read(stream, 4)
    return opcode, bytes(byte ^ mask[index % 4] for index, byte in enumerate(_read(stream, size)))


def serve(handler, bridge, thread, owner, identifier, after, csrf, enabled):
    """Upgrade only an already authenticated, CSRF checked terminal read route."""
    headers = handler.headers
    key = headers.get('Sec-WebSocket-Key', '')
    protocols = [item.strip() for item in headers.get('Sec-WebSocket-Protocol', '').split(',')]
    if (headers.get('Upgrade', '').lower() != 'websocket' or
            'upgrade' not in [item.strip().lower() for item in headers.get('Connection', '').split(',')] or
            headers.get('Sec-WebSocket-Version') != '13' or
            len(headers.get_all('Sec-WebSocket-Key', [])) != 1 or
            len(headers.get_all('Sec-WebSocket-Protocol', [])) != 1 or
            len(protocols) != 2 or protocols[0] != 'terminal.v1' or
            not hmac.compare_digest(protocols[1], csrf) or
            headers.get('Content-Length') or headers.get('Transfer-Encoding')):
        raise PermissionError('终端连接验证失败')
    try:
        if len(key) != 24 or len(base64.b64decode(key, validate=True)) != 16:
            raise ValueError()
    except ValueError:
        raise PermissionError('终端连接验证失败') from None
    # Validate binding before 101. An unknown or other owner's PTY is never upgraded.
    bridge.terminal(thread, owner, 'poll', {'id': identifier, 'after': after, 'waitMs': 0})
    if not handler.server.terminal_sockets.acquire(blocking=False):
        handler.output(503, {'error': '终端连接数已满'})
        return
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode('ascii')).digest()).decode('ascii')
    try:
        handler.send_response(101, 'Switching Protocols')
        handler.send_header('Upgrade', 'websocket')
        handler.send_header('Connection', 'Upgrade')
        handler.send_header('Sec-WebSocket-Accept', accept)
        handler.send_header('Sec-WebSocket-Protocol', 'terminal.v1')
        handler.end_headers()
    except Exception:
        handler.server.terminal_sockets.release()
        raise
    handler.close_connection = True
    stopped = threading.Event()
    send_lock = threading.Lock()
    rendered = threading.Event()
    pending = collections.deque()
    pending_lock = threading.Lock()
    sequence = [0]
    handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    handler.connection.settimeout(20)

    def emit(opcode, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(payload) > 1048576: raise ValueError('WebSocket output too large')
        head = (bytes((0x80 | opcode, len(payload))) if len(payload) < 126 else
                bytes((0x80 | opcode, 126)) + struct.pack('!H', len(payload)) if len(payload) <= 65535 else
                bytes((0x80 | opcode, 127)) + struct.pack('!Q', len(payload)))
        with send_lock:
            handler.wfile.write(head + payload)
            handler.wfile.flush()

    def authorized():
        session = handler.login_session()
        return (session and handler.server.auth.permitted(handler.client()['ip']) and
                hmac.compare_digest(session['csrf'], csrf) and
                handler.server.auth.key(handler.token()) == owner and enabled())

    def output_loop():
        cursor = after
        last_ping = time.monotonic()
        chunks = []
        try:
            while not stopped.is_set() and authorized():
                if time.monotonic() - last_ping > 10:
                    emit(9, b'')
                    last_ping = time.monotonic()
                with pending_lock:
                    queued_bytes = sum(item[1] for item in pending)
                    full = len(pending) >= 32 or queued_bytes >= 196608
                    expired = bool(pending and time.monotonic() - pending[0][2] > 30)
                if expired: break
                if full:
                    rendered.wait(1)
                    rendered.clear()
                    continue
                if chunks:
                    result = chunks.pop(0)
                else:
                    result = bridge.terminal(thread, owner, 'poll', {'id': identifier, 'after': cursor, 'waitMs': 1000})
                    output = result['output']
                    if len(output) > 16384:
                        position = result['cursor'] - len(output)
                        chunks = []
                        for index in range(0, len(output), 16384):
                            part = output[index:index + 16384]
                            position += len(part)
                            chunks.append({**result, 'output': part, 'cursor': position,
                                           'reset': result['reset'] and index == 0})
                        result = chunks.pop(0)
                if result['output'] or result['cursor'] != cursor or result['reset'] or not result['running']:
                    sequence[0] += 1
                    payload = json.dumps({'type': 'state', 'seq': sequence[0], 'value': result},
                                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    with pending_lock:
                        pending.append((sequence[0], len(payload), time.monotonic()))
                    emit(1, payload)
                    cursor = result['cursor']
                if not result['running'] and not chunks: break
            if not stopped.is_set(): emit(8, struct.pack('!H', 1000))
        except Exception:
            pass
        finally:
            stopped.set()
            try: handler.connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass

    worker = threading.Thread(target=output_loop, daemon=True)
    worker.start()
    try:
        while not stopped.is_set():
            opcode, payload = _frame(handler.rfile)
            if opcode == 8: break
            if opcode == 9:
                emit(10, payload)
                continue
            if opcode == 10: continue
            if not authorized(): break
            try:
                message = json.loads(payload.decode('utf-8', 'strict'))
                if not isinstance(message, dict): raise ValueError('Invalid terminal message')
                action = message.get('action')
                if action == 'rendered' and set(message) == {'action', 'seq'} and type(message['seq']) is int:
                    if message['seq'] > sequence[0]: raise ValueError('Invalid output acknowledgement')
                    with pending_lock:
                        while pending and pending[0][0] <= message['seq']:
                            pending.popleft()
                    rendered.set()
                    continue
                if action == 'input' and set(message) == {'action', 'inputId', 'data'}:
                    params = {'id': identifier, 'inputId': message['inputId'], 'data': message['data']}
                elif action == 'resize' and set(message) == {'action', 'cols', 'rows', 'requestId'}:
                    params = {'id': identifier, 'cols': message['cols'], 'rows': message['rows']}
                else: raise ValueError('Invalid terminal message')
                bridge.terminal(thread, owner, action, params)
                emit(1, {'type': 'ack', 'action': action,
                         'id': message['inputId'] if action == 'input' else message['requestId']})
            except (ValueError, KeyError, UnicodeError) as exc:
                emit(1, {'type': 'error', 'message': str(exc)[:160]})
                break
    except (EOFError, OSError, ValueError):
        pass
    finally:
        stopped.set()
        try: handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        worker.join(timeout=2)
        handler.server.terminal_sockets.release()
