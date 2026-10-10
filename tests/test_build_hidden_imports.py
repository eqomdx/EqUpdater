"""The PyInstaller command keeps Pillow's Tk bridge in the frozen build.

Pillow's _imagingtk extension imports PIL._tkinter_finder from C at run time
on Linux, so PyInstaller never sees it. Without it the packaged Linux app
died at start-up drawing its background ("No module named
'PIL._tkinter_finder'"). The packaged build is checked for real by
``--self-test --gui`` in release.yml; this catches the flag being dropped
without needing a build.
"""

import contextlib
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402


class TestHiddenImports(unittest.TestCase):
    def pyinstaller_command(self):
        seen = []
        with mock.patch.object(build, "run", side_effect=seen.append), \
                mock.patch.object(importlib.util, "find_spec",
                                  return_value=object()), \
                mock.patch.object(sys, "argv", ["build.py"]), \
                mock.patch.object(build, "DIST", tempfile.mkdtemp()), \
                mock.patch("builtins.print"):
            with contextlib.suppress(SystemExit):   # nothing was really built
                build.main()
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_pillow_tk_bridge_is_a_hidden_import(self):
        cmd = self.pyinstaller_command()
        pairs = list(zip(cmd, cmd[1:]))
        self.assertIn(("--hidden-import", "PIL._tkinter_finder"), pairs)


if __name__ == "__main__":
    unittest.main()
