"""Build-time ConPTY package verification and layout."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('conpty_bundle', Path(__file__).resolve().parents[1]/'scripts/bundle-conpty.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class ConptyBundleTests(unittest.TestCase):
    def package(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('Microsoft.Windows.Console.ConPTY.nuspec',
                             '<package xmlns="http://schemas.microsoft.com/packaging/2011/08/nuspec.xsd">'
                             '<metadata><id>Microsoft.Windows.Console.ConPTY</id><version>1.25.260930003</version>'
                             '<license type="expression">MIT</license></metadata></package>')
            archive.writestr('runtimes/win-x64/native/conpty.dll', b'MZ-dll')
            for arch in ('x86', 'x64', 'arm64'):
                archive.writestr(f'build/native/runtimes/{arch}/OpenConsole.exe', b'MZ-'+arch.encode())
        return stream.getvalue()

    def test_verified_package_keeps_all_native_host_architectures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            (root/'scripts/conpty-LICENSE').write_text('Microsoft MIT fixture')
            data = self.package()
            (root/'.tmp/conpty').mkdir(parents=True)
            (root/'.tmp/conpty/conpty-1.25.260930003.nupkg').write_bytes(data)
            (root/'scripts/conpty-lock.json').write_text(json.dumps({
                'version': '1.25.260930003', 'sha256': hashlib.sha256(data).hexdigest(),
                'url': 'https://www.nuget.org/api/v2/package/Microsoft.Windows.Console.ConPTY/1.25.260930003'}))
            with patch.object(bundle, 'ROOT', root), patch.object(bundle.sys, 'platform', 'win32'), \
                    patch.object(bundle.platform, 'machine', return_value='AMD64'), \
                    patch.object(bundle, 'urlopen', side_effect=AssertionError('cached archive should not download')):
                target = bundle.bundle()
            self.assertEqual((target/'conpty.dll').read_bytes(), b'MZ-dll')
            for arch in ('x86', 'x64', 'arm64'):
                self.assertEqual((target/arch/'OpenConsole.exe').read_bytes(), b'MZ-'+arch.encode())
            self.assertEqual((target/'LICENSE').read_text(), 'Microsoft MIT fixture')
            self.assertEqual(json.loads((target/'version.json').read_text())['arch'], 'x64')

    def test_bad_package_digest_does_not_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            (root/'scripts/conpty-lock.json').write_text(json.dumps({
                'version': '1.25.260930003', 'sha256': '0'*64,
                'url': 'https://www.nuget.org/api/v2/package/Microsoft.Windows.Console.ConPTY/1.25.260930003'}))
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self, size): return self_data
            self_data = self.package()
            with patch.object(bundle, 'ROOT', root), patch.object(bundle.sys, 'platform', 'win32'), \
                    patch.object(bundle.platform, 'machine', return_value='AMD64'), \
                    patch.object(bundle, 'urlopen', return_value=Response()):
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    bundle.bundle()
            self.assertFalse((root/'dist/conpty').exists())


if __name__ == '__main__':
    unittest.main()
