import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mobile_scope', ROOT / 'scripts/ci-mobile-scope.py')
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class MobileCompileScope(unittest.TestCase):
    def test_shared_resources_and_ci_changes_require_native_compilation(self):
        for path in ('mobile/shared/web/mobile-clipboard.js', 'mobile/android/src/Example.java',
                     'web/hosts/mobile.css', 'scripts/build-mobile-ios.py',
                     '.github/workflows/tests.yml', 'package-lock.json'):
            with self.subTest(path=path):
                self.assertTrue(scope.needs_mobile([path]))
        self.assertFalse(scope.needs_mobile(['README.md', 'bridge/features/accounts/accounts.py',
                                            'mobile-guide.md']))

    def test_deleting_or_renaming_native_source_still_requires_compile(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
            git('init')
            git('config', 'user.name', 'Synthetic CI test')
            git('config', 'user.email', 'fixture@example.invalid')
            (root / 'mobile').mkdir()
            (root / 'mobile/native.txt').write_text('fixture')
            git('add', '.');git('commit', '-m', 'fixture base')
            base = git('rev-parse', 'HEAD')
            (root / 'mobile/native.txt').rename(root / 'retired.txt')
            git('add', '-A');git('commit', '-m', 'fixture rename')
            head = git('rev-parse', 'HEAD')
            self.assertTrue(scope.needs_mobile(scope.changed_paths(root, base, head)))
            self.assertTrue(scope.needs_mobile(scope.changed_paths(root, '0' * 40, base)))
            self.assertFalse(scope.needs_mobile(scope.changed_paths(root, head, head)))
            with self.assertRaises(ValueError):
                scope.changed_paths(root, base, '--not-a-commit')


if __name__ == '__main__':
    unittest.main()
