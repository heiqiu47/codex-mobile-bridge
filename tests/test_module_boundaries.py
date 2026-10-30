"""Dependency direction is a source gate; fixtures prove violations are rejected."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boundary_check', ROOT / 'scripts/check-boundaries.py')
boundary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)


class ModuleBoundaries(unittest.TestCase):
    def test_repository_has_no_new_or_obsolete_exceptions(self):
        exceptions = json.loads((ROOT / 'docs/architecture/dependency-exceptions.json').read_text())
        self.assertEqual(boundary.check(ROOT, exceptions), [])

    def test_relative_alias_and_literal_dynamic_imports_are_checked(self):
        source = '''from ...app.lifecycle import private_json as write
from ... import features
import bridge.api.httpd as routes
import importlib as loader
from importlib import import_module as load
loader.import_module("bridge.clients.codex.ipc")
load("...app.service", package=__package__)
__import__("bridge.features.sessions")
'''
        found = {dep for _, dep in boundary.dependencies(source, 'bridge.platforms.windows')}
        self.assertTrue({'bridge.app.lifecycle.private_json', 'bridge.features', 'bridge.api.httpd',
                         'bridge.clients.codex.ipc', 'bridge.app.service',
                         'bridge.features.sessions'} <= found)
        self.assertTrue(all(boundary.rule_for('bridge.platforms.windows.fixture', dep)
                            for dep in found if dep.startswith('bridge.')))

    def test_cross_provider_is_rejected_but_common_platform_dependencies_are_allowed(self):
        self.assertEqual(boundary.rule_for('bridge.clients.claude.adapter',
                                          'bridge.clients.codex.ipc'), 'provider-peer')
        self.assertIsNone(boundary.rule_for('bridge.clients.claude.adapter',
                                           'bridge.platforms.macos.claude'))
        self.assertIsNone(boundary.rule_for('bridge.app.service', 'bridge.clients.codex.ipc'))

    def test_new_edge_fails_and_removed_exception_must_be_deleted(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            root = Path(directory)
            source = root / 'bridge/platforms/macos/example.py'
            source.parent.mkdir(parents=True)
            source.write_text('from ...app import service\n')
            self.assertEqual(len(boundary.check(root, [])), 1)
            exception = {'file': source.relative_to(root).as_posix(), 'dependency': 'bridge.app.service',
                         'rule': 'platform-upward', 'reason': 'Synthetic fixture only'}
            self.assertEqual(boundary.check(root, [exception]), [])
            source.write_text('import os\n')
            self.assertIn('obsolete exception', boundary.check(root, [exception])[0])
            with self.assertRaises(ValueError):
                boundary.check(root, [exception, exception])


if __name__ == '__main__':
    unittest.main()
