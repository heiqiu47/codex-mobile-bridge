"""Explicit, local-only binding to the independently installed Harness plugin."""
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

from bridge.clients.deepseek.adapter import DeepSeek, BRIDGE_REVISION
from bridge.clients.errors import BridgeUnavailable

SOURCE = Path(__file__).resolve().parent
PACKAGE = 'dsh-codex-mobile-bridge'


def package_files():
    return {**{name: (SOURCE/'plugin'/name).read_bytes() for name in
               ('package.json', 'cordis.patch.yml', 'index.mjs', 'README.md')},
            'host.mjs': (SOURCE/'host.mjs').read_bytes(),
            'LICENSE': (SOURCE.parents[2]/'LICENSE').read_bytes(),
            'LICENSE.coding-mobile': (SOURCE.parent/'LICENSE.coding-mobile').read_bytes()}


def export_package(destination):
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError('请选择插件包保存目录')
    target = Path(destination).expanduser().resolve()
    if not target.is_dir():
        raise ValueError('请选择插件包保存目录')
    files = package_files()
    version = json.loads(files['package.json'])['version']
    path = target/f'{PACKAGE}-{version}.zip'
    # Never replace a user's existing package or add private connection files.
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(PACKAGE+'/'+name, content)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _private(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (hasattr(os, 'getuid') and
            (info.st_uid != os.getuid() or info.st_mode & 0o077)):
        raise ValueError('DSH 绑定文件权限不安全')
    if info.st_size > 16384:
        raise ValueError('DSH 绑定文件过大')
    return json.loads(path.read_text('utf-8'))


class ManualDeepSeek(DeepSeek):
    manual = True

    def __init__(self, binding_file, instance_id=None):
        path = Path(binding_file).expanduser().absolute()
        if path.name != 'binding.json':
            raise ValueError('请选择插件生成的 binding.json')
        binding = _private(path)
        directory = path.parent.resolve()
        required = ('directory', 'home', 'profileDirectory', 'profile', 'instanceId', 'packageDirectory')
        if binding.get('protocol') != 1 or any(not isinstance(binding.get(key), str) or not binding[key] for key in required):
            raise ValueError('DSH 绑定格式不兼容')
        if instance_id is not None and binding['instanceId'] != instance_id:
            raise ValueError('DSH 插件实例已改变，请重新绑定')
        if binding['directory'] != str(directory) or directory.parent != Path(binding['profileDirectory']).resolve():
            raise ValueError('DSH 绑定目录不匹配')
        if Path(binding['profileDirectory']).resolve() != (Path(binding['home'])/'profiles'/binding['profile']).resolve():
            raise ValueError('DSH 档案目录不匹配')
        package = Path(binding['packageDirectory'])
        expected = package_files()
        for name in ('host.mjs', 'index.mjs', 'package.json', 'cordis.patch.yml'):
            if (package/name).read_bytes() != expected[name]:
                raise ValueError('DSH 插件版本不匹配，请安装当前网关导出的插件包')
        super().__init__(directory, binding['home'])
        self.binding = binding
        self.receipts_path = directory/'requests.sqlite'
        self._connection()

    def _connection(self):
        binding = _private(self.directory/'binding.json')
        config = _private(self.directory/'connection.json')
        if binding != self.binding or config.get('instanceId') != self.binding['instanceId'] or config.get('endpoint') != str(self.directory/'endpoint.json'):
            raise ValueError('DSH 插件实例已改变，请重新绑定')
        token = config.get('token')
        if not isinstance(token, str) or len(token) != 64:
            raise ValueError('DSH 插件凭据无效')
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        if hasattr(self, 'credential') and self.credential != fingerprint:
            raise ValueError('DSH 插件凭据已改变，请重新绑定')
        self.credential = fingerprint

    def call(self, action, sid=None, body=None):
        self._connection()
        if action == 'quit':
            raise ValueError('请在第三方客户端中退出应用；网关仅管理接入')
        value = super().call(action, sid, body)
        if action == 'status':
            if value.get('bridgeRevision') != BRIDGE_REVISION:
                raise BridgeUnavailable('DSH 插件版本不兼容，请更新后重新绑定')
            value.update(bindingMode='manual', profile=self.binding['profile'], nativeQuit=False)
        return value

    def discover_existing(self):
        self._connection()
        return {'installed': True, 'updateRequired': False, 'manual': True}

    def ensure_installed(self):
        raise ValueError('当前使用手动安装插件，请在第三方客户端管理插件')

    def uninstall(self):
        raise ValueError('请先解除绑定，再在第三方客户端中卸载插件')


def discover_plugins(home):
    """Inspect explicit Harness profiles, never executable names or arbitrary ports."""
    if not isinstance(home, str) or not home.strip():
        raise ValueError('请选择 Harness 数据目录')
    root = Path(home).expanduser().resolve()
    profiles = root/'profiles'
    if not profiles.is_dir():
        return []
    candidates = []
    for profile in sorted(profiles.iterdir()):
        if profile.is_symlink() or not profile.is_dir():
            continue
        path = profile/'codex-mobile-bridge/binding.json'
        if not path.exists():
            continue
        try:
            adapter = ManualDeepSeek(path)
            if Path(adapter.binding['home']).resolve() != root:
                continue
            candidates.append({'file': str(path), 'profile': adapter.binding['profile']})
        except (OSError, ValueError):
            continue
    return candidates
