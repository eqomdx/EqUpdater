"""build.py tells an antivirus interruption apart from any other failure.

Antivirus software on a user's PC removed the freshly built EqUpdater.exe
from build\\EqUpdater while PyInstaller was still finishing it; PyInstaller
retried, then failed with "cannot find the file". The explanation must appear
for exactly that -- packed, then the exe gone -- and never for an ordinary
failure, where it would send people chasing their antivirus for nothing.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402


@unittest.skipUnless(os.name == "nt", "the diagnosis is Windows-only")
class TestAntivirusDiagnosis(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="equ-build-")
        self.real_work = build.WORK
        build.WORK = self.work
        self.dir = os.path.join(self.work, build.NAME)
        os.makedirs(self.dir)

    def tearDown(self):
        build.WORK = self.real_work
        shutil.rmtree(self.work, ignore_errors=True)

    def touch(self, name):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(b"x")

    def said(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            build.explain_antivirus_interruption()
        return out.getvalue()

    def test_packed_then_exe_gone_is_antivirus(self):
        self.touch(build.NAME + ".pkg")
        text = self.said()
        self.assertIn("interrupted by antivirus software", text)
        self.assertIn("Protection history", text)
        self.assertIn(os.path.join(self.dir, build.NAME + ".exe"), text)

    def test_failure_before_packing_is_not_blamed_on_antivirus(self):
        self.assertEqual(self.said(), "")

    def test_exe_still_there_is_not_blamed_on_antivirus(self):
        self.touch(build.NAME + ".pkg")
        self.touch(build.NAME + ".exe")
        self.assertEqual(self.said(), "")

    def test_the_installer_recognises_the_message(self):
        """install.ps1 keys its Windows Defender lookup off this phrase."""
        with open(os.path.join(ROOT, "install", "install.ps1"), encoding="utf-8") as f:
            self.assertIn("interrupted by antivirus software", f.read())
        self.assertIn("interrupted by antivirus software", build.ANTIVIRUS_HINT)


if __name__ == "__main__":
    unittest.main()
