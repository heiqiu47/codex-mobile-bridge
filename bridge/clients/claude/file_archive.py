"""Byte-preserving local transcript archive; standalone for selected remote workers."""
import hashlib
import json
import os
import subprocess
import shutil
import uuid
from pathlib import Path

# Populated only after native picker hide/restore acceptance for an exact version.
VERIFIED_PICKER_VERSIONS = frozenset()


def supported(binary, environment):
    if not VERIFIED_PICKER_VERSIONS:
        return False
    try:
        result = subprocess.run([binary, '--version'], env=environment, capture_output=True,
                                text=True, timeout=5)
        return result.returncode == 0 and result.stdout.split()[0] in VERIFIED_PICKER_VERSIONS
    except (OSError, subprocess.SubprocessError, IndexError):
        return False


def recorded_writer(directory, native):
    """Absence of a registry entry is unknown, not proof of a stopped writer."""
    registry = Path(directory)/'sessions'
    if not registry.is_dir() or registry.is_symlink():
        return False
    _owned(registry)
    for path in registry.glob('*.json'):
        _owned(path)
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('Claude 会话进程登记不可验证')
        value = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(value, dict) and value.get('sessionId') == native:
            return True
    return False


def _root(directory):
    directory = Path(directory)
    root = directory/'bridge-archives'
    _owned(directory)
    if root.exists():_owned(root)
    if directory.is_symlink() or root.is_symlink():
        raise ValueError('Claude 归档路径不可验证')
    return root


def _owned(path):
    if path.is_symlink() or (hasattr(os, 'getuid') and path.stat().st_uid != os.getuid()):
        raise ValueError('Claude 归档文件归属不可验证')


def _digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Claude 归档文件不可验证')
    _owned(path)
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def _sync_directory(path):
    if os.name != 'nt':
        handle = os.open(path, os.O_RDONLY)
        try:os.fsync(handle)
        finally:os.close(handle)


def _write(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as target:
        json.dump(value, target, ensure_ascii=False)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _manifest(directory, native):
    native = str(uuid.UUID(native))
    bundle = _root(directory)/native
    if bundle.is_symlink():
        raise ValueError('Claude 归档目录不可验证')
    if bundle.exists():_owned(bundle)
    path = bundle/'manifest.json'
    if not path.exists():
        return bundle, None
    if path.exists():_owned(path)
    if path.is_symlink():
        raise ValueError('Claude 归档记录不可验证')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('schema') != 1 or value.get('nativeId') != native
            or not isinstance(value.get('project'), str)
            or value['project'] in ('', '.', '..')
            or '/' in value['project'] or '\\' in value['project']):
        raise ValueError('Claude 归档记录不可验证')
    return bundle, value


def _original(directory, project, native):
    projects = Path(directory)/'projects'
    target = projects/project
    if projects.is_symlink() or target.is_symlink() or not target.is_dir():
        raise ValueError('Claude 原项目路径不可验证')
    _owned(projects);_owned(target)
    return target/(native+'.jsonl')


def archive_paths(directory):
    if not Path(directory).exists() and not Path(directory).is_symlink():
        return []
    root = _root(directory)
    if not root.exists():
        return []
    result = []
    for bundle in root.iterdir():
        if not bundle.is_dir() or bundle.name.startswith('.'):
            continue
        try:
            native = str(uuid.UUID(bundle.name))
        except ValueError:
            continue
        bundle, manifest = _manifest(directory, native)
        if manifest and manifest.get('phase') != 'restored':
            state(directory, bundle/(native+'.jsonl'), native)
            result.append(bundle/(native+'.jsonl'))
    return result


def state(directory, path, native):
    bundle, manifest = _manifest(directory, native)
    if not manifest:
        original = _original(directory, Path(path).parent.name, native)
        if Path(path) != original:
            raise ValueError('Claude 原会话路径不可验证')
        _digest(original)
        return {'archived': False}
    original = _original(directory, manifest['project'], native)
    archived = bundle/(native+'.jsonl')
    phase = manifest.get('phase')
    if phase not in ('archived', 'restored'):
        raise ValueError('Claude 文件归档事务中断，请在电脑端核对；不会自动重放')
    expected, absent = (archived, original) if phase == 'archived' else (original, archived)
    if (absent.exists() or absent.is_symlink()
            or (phase == 'archived' and _digest(expected) != manifest['sha256'])):
        raise ValueError('Claude 归档文件冲突或已变化，请在电脑端核对')
    _digest(expected)
    return {'archived': phase == 'archived'}


def _private_files(root):
    if not root.exists() and not root.is_symlink():return []
    _owned(root)
    if not root.is_dir():raise ValueError('Claude 会话附属目录不可验证')
    result = []
    for path in root.rglob('*'):
        _owned(path)
        if path.is_file():result.append(path)
        elif not path.is_dir():raise ValueError('Claude 会话附属文件不可验证')
    return result


def _snapshot(directory, original, bundle, native):
    destination = bundle/'sidecars'
    if destination.exists():
        _private_files(destination)
        shutil.rmtree(destination)
    roots = [original.parent/native, Path(directory)/'file-history'/native]
    # Validate the complete trees before creating any copy.
    for root in roots:
        if root.parent.exists() or root.parent.is_symlink():_owned(root.parent)
    files = [(root, _private_files(root)) for root in roots]
    inventory = {}
    for index, (root, items) in enumerate(files):
        for source in items:
            target = destination/str(index)/source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(source, target, follow_symlinks=False)
            with target.open('rb') as copied:os.fsync(copied.fileno())
            parent = target.parent
            while parent != bundle:
                _sync_directory(parent);parent = parent.parent
            inventory[str(target.relative_to(destination))] = _digest(target)
            if _digest(source) != _digest(target):
                raise ValueError('Claude 附属文件在备份期间变化')
    return inventory


def _restore_snapshots(directory, original, bundle, native, manifest):
    snapshot = bundle/'sidecars'
    actual = {str(path.relative_to(snapshot)): _digest(path) for path in _private_files(snapshot)}
    if actual != manifest.get('sidecars', {}):
        raise ValueError('Claude 附属文件备份已变化')
    roots = [original.parent/native, Path(directory)/'file-history'/native]
    missing = []
    for index, root in enumerate(roots):
        backup = bundle/'sidecars'/str(index)
        for source in _private_files(backup):
            target = root/source.relative_to(backup)
            parent = target.parent
            while parent != Path(directory):
                if parent.exists() or parent.is_symlink():_owned(parent)
                parent = parent.parent
            if target.exists() or target.is_symlink():
                if _digest(target) != _digest(source):
                    raise ValueError('Claude 附属文件冲突，恢复不会覆盖')
            else:missing.append((source,target))
    for source,target in missing:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Independent copy: later native edits must not mutate the backup inode.
        with source.open('rb') as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer);writer.flush();os.fsync(writer.fileno())
        shutil.copystat(source,target,follow_symlinks=False)


def change(directory, path, native, archived):
    """Caller must freshly verify the exact profile and stopped native writer."""
    if type(archived) is not bool:
        raise ValueError('Claude 归档设置无效')
    native = str(uuid.UUID(native))
    directory = Path(directory)
    root = _root(directory)
    root.mkdir(mode=0o700, exist_ok=True)
    lock = root/'.transaction'
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError('Claude 文件归档事务待核对，不会自动重放') from exc
    try:
        before = state(directory, path, native)
        if before['archived'] == archived:
            return before
        bundle, manifest = _manifest(directory, native)
        if manifest is None:
            original = _original(directory, Path(path).parent.name, native)
            bundle.mkdir(mode=0o700)
            manifest = {'schema': 1, 'nativeId': native, 'project': original.parent.name,
                        'sha256': _digest(original)}
        original = _original(directory, manifest['project'], native)
        stored = bundle/(native+'.jsonl')
        source, target = (original, stored) if archived else (stored, original)
        if archived:
            if source.stat().st_nlink != 1:
                raise ValueError('Claude 会话已有共享硬链接，不能归档')
            manifest['sha256'] = _digest(source)
            manifest['sidecars'] = _snapshot(directory, original, bundle, native)
        else:
            _restore_snapshots(directory, original, bundle, native, manifest)
        previous = 'restored' if archived else 'archived'
        manifest['phase'] = 'preparing'
        _write(bundle/'manifest.json', manifest)
        linked = False
        try:
            # link refuses existing destinations atomically; same filesystem only.
            with source.open('rb') as original_file:os.fsync(original_file.fileno())
            os.link(source, target, follow_symlinks=False)
            linked = True
            if _digest(target) != manifest['sha256'] or _digest(source) != manifest['sha256']:
                raise ValueError('Claude 会话在归档期间变化')
            source.unlink()
            _sync_directory(source.parent);_sync_directory(target.parent)
            manifest['phase'] = 'archived' if archived else 'restored'
            _write(bundle/'manifest.json', manifest)
        except Exception:
            if linked and source.exists() and target.exists() and _digest(source) == _digest(target):
                target.unlink()
                manifest['phase'] = previous
                _write(bundle/'manifest.json', manifest)
            raise
        return state(directory, target, native)
    finally:
        lock.rmdir()
