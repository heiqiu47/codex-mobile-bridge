"""WSL PTYs use the same acknowledged input protocol as SSH terminals."""
import uuid
from pathlib import PurePosixPath

from bridge.features.terminals.manager import TerminalManager
from bridge.platforms.posix.terminal import RemoteTerminalSession
from bridge.platforms.windows import wsl


class WslTerminals:
    def __init__(self):
        self.manager = TerminalManager()

    def terminal(self, entry, identifier, owner, action, params):
        uuid.UUID(identifier)
        if action in ('info', 'open'):
            root = entry.store.get(identifier).get('cwd')
            if not isinstance(root, str) or not PurePosixPath(root).is_absolute() or '\x00' in root:
                raise ValueError('聊天项目目录不可用')
            if action == 'info':
                return {'cwd': root, 'host': entry.host, 'mode': 'pty', 'shell': None}
            def transport(source):
                return wsl.command(entry.row['distribution'], entry.row['user']) + ['-u', '-c', source]
            def factory(cwd, cols, rows):
                return RemoteTerminalSession(None, cwd, cols, rows, transport=transport, transport_name='WSL')
            return self.manager.open_session(owner, identifier, params.get('id', ''), root,
                params.get('cols'), params.get('rows'), session_factory=factory)
        if action not in ('input', 'resize', 'close', 'poll', 'complete'):
            raise ValueError('未知终端操作')
        session = self.manager.session(owner, identifier, params.get('id', ''))
        if action == 'input':
            return session.write(params.get('inputId'), params.get('data'))
        if action == 'resize':
            return session.resize(params.get('cols'), params.get('rows'))
        if action == 'complete':
            return session.complete(params.get('text'), params.get('selectionStart'))
        if action == 'close':
            session.stop()
            return {'closed': True}
        after, wait = params.get('after', 0), params.get('waitMs', 0)
        if type(after) is not int or not 0 <= after <= 10**12:
            raise ValueError('无效输出游标')
        if type(wait) is not int or not 0 <= wait <= 1000:
            raise ValueError('无效等待时间')
        return session.read(after, wait)

    def close(self):
        self.manager.close()
