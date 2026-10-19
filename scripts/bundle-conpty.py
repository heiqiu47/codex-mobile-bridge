#!/usr/bin/env python3
"""Bundle the locked Microsoft ConPTY pair for Windows builds."""
import hashlib
import json
import platform
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'Microsoft.Windows.Console.ConPTY'


def bundle():
    if sys.platform != 'win32':
        raise ValueError('ConPTY bundle is only for Windows builds')
    arch = {'AMD64': 'x64', 'x86_64': 'x64'}[platform.machine()]
    lock = json.loads((ROOT/'scripts/conpty-lock.json').read_text(encoding='utf-8'))
    version = lock['version']
    cache = ROOT/'.tmp/conpty'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache/f'conpty-{version}.nupkg'
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != lock['sha256']:
        with urlopen(Request(lock['url'], headers={'User-Agent': 'Codex-Mobile-Bridge-build'}), timeout=180) as response:
            data = response.read(16*1024*1024 + 1)
        if len(data) > 16*1024*1024 or hashlib.sha256(data).hexdigest() != lock['sha256']:
            raise ValueError('ConPTY package SHA-256 mismatch')
        archive.write_bytes(data)
    files = {'conpty.dll': f'runtimes/win-{arch}/native/conpty.dll'}
    files.update({f'{host}/OpenConsole.exe': f'build/native/runtimes/{host}/OpenConsole.exe'
                  for host in ('x86', 'x64', 'arm64')})
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if any(names.count(name) != 1 for name in (*files.values(), f'{PACKAGE}.nuspec')):
            raise ValueError('ConPTY package is missing or duplicates a required file')
        metadata = ET.fromstring(package.read(f'{PACKAGE}.nuspec'))
        namespace = {'n': 'http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd'}
        if (metadata.findtext('n:metadata/n:id', namespaces=namespace) != PACKAGE
                or metadata.findtext('n:metadata/n:version', namespaces=namespace) != version
                or metadata.findtext('n:metadata/n:license', namespaces=namespace) != 'MIT'):
            raise ValueError('Unexpected ConPTY package metadata')
        binaries = {relative: package.read(member) for relative, member in files.items()}
    if any(not data.startswith(b'MZ') for data in binaries.values()):
        raise ValueError('ConPTY package contains an invalid executable')
    target = ROOT/'dist/conpty'
    shutil.rmtree(target, ignore_errors=True)
    for relative, data in binaries.items():
        path = target/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    shutil.copyfile(ROOT/'scripts/conpty-LICENSE', target/'LICENSE')
    (target/'version.json').write_text(json.dumps({'version': version, 'arch': arch,
                                                   'packageSha256': lock['sha256']}), encoding='utf-8')
    print('Bundled ConPTY:', target, version, arch)
    return target


if __name__ == '__main__':
    bundle()
