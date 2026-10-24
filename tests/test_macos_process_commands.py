"""Read-only process command contract; never invokes ps or signals real apps."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bridge.platforms.macos.desktop import commands


class MacOSProcessCommandsTests(unittest.TestCase):
    def test_empty_selection_never_invokes_ps(self):
        # macOS ps -p '' can produce invalid UTF-8 diagnostic bytes.
        with patch('bridge.platforms.macos.desktop.subprocess.run') as run:
            self.assertEqual(commands([]), {})
            run.assert_not_called()

    def test_nonempty_selection_keeps_exact_pid_query_and_full_command(self):
        result = SimpleNamespace(returncode=0, stdout=' 701 /fixture/Desktop --profile /path with spaces\n')
        with patch('bridge.platforms.macos.desktop.subprocess.run', return_value=result) as run:
            self.assertEqual(commands([701]), {701: '/fixture/Desktop --profile /path with spaces'})
            self.assertEqual(run.call_args.args[0], ['ps', '-ww', '-p', '701', '-o', 'pid=,args='])
