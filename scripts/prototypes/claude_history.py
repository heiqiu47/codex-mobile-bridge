"""Read-only Claude Code raw-event paging experiment; not a rendered timeline.

Native transcript branches, compaction and tool pairs still need semantic merge
before product integration. A changed file invalidates the cursor rather than
pretending a partial view is the authoritative execution/approval state.
"""
import hashlib
import json
import os
from pathlib import Path


def event_page(path, scope, *, limit=20, cursor=None, byte_budget=2 * 1024 * 1024):
    if not isinstance(scope, str) or not scope or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Explicit source identity and bounded page size required')
    path = Path(path).resolve()
    with path.open('rb') as stream:
        stat = os.fstat(stream.fileno())
        stamp = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
        identity = hashlib.sha256((scope + '\0' + str(path)).encode()).hexdigest()
        end = stat.st_size
        if cursor:
            if cursor.get('identity') != identity or cursor.get('stamp') != stamp:
                raise ValueError('History identity or file changed; refresh the recent page')
            end = cursor.get('offset')
            if type(end) is not int or not 0 <= end <= stat.st_size:
                raise ValueError('Invalid file cursor')
            if end and end != stat.st_size:
                stream.seek(end - 1)
                if stream.read(1) != b'\n':
                    raise ValueError('Cursor must point to a complete record boundary')
        pos, pending, read_bytes, events, boundary = end, b'', 0, [], 0
        while pos or pending:
            if pos:
                size = min(65536, pos, byte_budget - read_bytes)
                if size <= 0:
                    raise ValueError('Page scan exceeded byte budget; no full-file fallback')
                pos -= size
                stream.seek(pos)
                block = stream.read(size)
                if len(block) != size:
                    raise ValueError('History changed during read')
                read_bytes += size
                pending = block + pending
            parts = pending.splitlines(keepends=True)
            keep = parts.pop(0) if pos else b''
            offset = pos + len(keep) + sum(map(len, parts))
            for line in reversed(parts):
                offset -= len(line)
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get('type') not in ('user', 'assistant') or event.get('isSidechain'):
                    continue
                events.append(event)
                boundary = offset
                if len(events) >= limit:
                    break
            pending = keep
            if len(events) >= limit:
                break
        final = os.fstat(stream.fileno())
        if [final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns] != stamp:
            raise ValueError('History changed during read')
        next_cursor = ({'identity': identity, 'stamp': stamp, 'offset': boundary}
                       if len(events) == limit and boundary > 0 else None)
        return {'events': list(reversed(events)), 'cursor': next_cursor, 'bytesRead': read_bytes,
                'sourceBytes': stat.st_size, 'readOnly': True, 'authoritativeState': False}
