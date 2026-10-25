"""Standalone Linux identity proof for Codex's native PID-backed updater."""
import json
import os
import stat
from pathlib import Path


def codex_updater(process, executable, args, environment, directory, expected=None):
    """Return safe metadata only for the registered non-inference updater role."""
    if [arg for arg in args[1:] if arg] != [b'app-server', b'daemon', b'pid-update-loop']:
        return None
    if not executable.startswith('/') or executable.startswith('/mnt/') or Path(executable).name != 'codex':
        return None
    uid = os.getuid()
    root = Path(directory).resolve()
    selected = environment.get(b'CODEX_HOME')
    if not selected or Path(os.fsdecode(selected)).resolve() != root or process.stat().st_uid != uid:
        return None
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    ticks = int((process/'stat').read_text().rsplit(')', 1)[1].split()[19])
    binary = Path(executable).stat()
    value = {'pid': int(process.name), 'startTicks': ticks, 'bootId': boot,
             'executable': executable, 'executableDevice': binary.st_dev,
             'executableInode': binary.st_ino, 'home': str(root), 'uid': uid}
    state = root/'app-server-daemon'
    if state.is_symlink() or state.stat().st_uid != uid or state.stat().st_mode & 0o022:
        return None
    def record(name):
        path = state/name
        if path.is_symlink():
            return None
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
                return None
            return json.loads(path.read_text())
        except FileNotFoundError:
            return None
    valid = False
    for name in ('daemon-updater.pid', 'app-server-updater.pid'):
        data = record(name) or {}
        identity = data.get('processIdentity') or data.get('linuxProcessIdentity') or {}
        if data.get('pid') == value['pid'] and identity.get('bootId') == boot and identity.get('startTicks') == ticks:
            valid = True
    if not valid:
        return None
    if expected is not None:
        return value if value == expected else None
    for name in ('daemon.pid', 'app-server.pid'):
        data = record(name) or {}
        identity = data.get('processIdentity') or data.get('linuxProcessIdentity') or {}
        pid = data.get('pid')
        if type(pid) is not int or pid <= 0:
            continue
        main = Path('/proc')/str(pid)
        try:
            fields = (main/'stat').read_text().rsplit(')', 1)[1].split()
            if (fields[0] == 'Z' or main.stat().st_uid != uid or identity.get('bootId') != boot or
                    identity.get('startTicks') != int(fields[19])):
                continue
            main_args = (main/'cmdline').read_bytes().split(b'\0')
            main_environment = dict(item.split(b'=', 1) for item in (main/'environ').read_bytes().split(b'\0') if b'=' in item)
            selected = main_environment.get(b'CODEX_HOME')
            info = Path(os.readlink(main/'exe')).stat()
            if (b'app-server' in main_args and b'--managed-daemon' in main_args and selected and
                    Path(os.fsdecode(selected)).resolve() == root and
                    (info.st_dev, info.st_ino) == (binary.st_dev, binary.st_ino)):
                return value
        except FileNotFoundError:
            continue
    return None
