"""install/deploy.py: one permanent home for the app, shortcuts that follow
it, and an update that can fail without costing the player a working copy.

The bug behind it: 2.0.5 was built in its own download folder while the
desktop shortcut went on opening the 2.0.4 one.
"""

import importlib.util
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "deploy", os.path.join(ROOT, "install", "deploy.py"))
deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy)

ON_WINDOWS = os.name == "nt" and shutil.which("powershell") is not None


def make_build(where, version):
    """A stand-in for a PyInstaller folder build of ``version``."""
    os.makedirs(os.path.join(where, "_internal"), exist_ok=True)
    with open(os.path.join(where, "EqUpdater.exe"), "w") as f:
        f.write("exe " + version)
    with open(os.path.join(where, "_internal", "version.txt"), "w") as f:
        f.write(version)
    return where


def installed_version(install_dir):
    with open(os.path.join(install_dir, "_internal", "version.txt")) as f:
        return f.read()


class Sandbox(unittest.TestCase):
    def setUp(self):
        # Long form: %TEMP% is often 8.3 (OLIVER~1), and the shell writes
        # shortcut targets in full.
        self.tmp = deploy.long_path(tempfile.mkdtemp(prefix="equ-deploy-"))
        self.local = os.path.join(self.tmp, "Local")
        self.install = os.path.join(self.local, "Programs", "EqUpdater")
        self.state = os.path.join(self.local, "EqUpdater")
        os.makedirs(self.state)
        self.config = os.path.join(self.state, "config.json")
        with open(self.config, "w") as f:
            f.write('{"out_dir": "D:\\\\Games\\\\OctoWoW", "tweaks": {"locale": "deDE"}}')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, version, name=None):
        return make_build(os.path.join(
            self.tmp, name or f"EqUpdater-{version}", "dist", "EqUpdater"), version)

    def leftovers(self):
        return [p for p in (self.install + ".new", self.install + ".old")
                if os.path.exists(p)]


class TestInstallFolder(Sandbox):
    def test_default_home_is_programs_under_localappdata(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": self.local}):
            self.assertEqual(deploy.default_install_dir(), self.install)

    def test_fresh_install(self):
        exe = deploy.deploy(self.build("2.0.5"), self.install)
        self.assertEqual(exe, os.path.join(self.install, "EqUpdater.exe"))
        self.assertEqual(installed_version(self.install), "2.0.5")
        self.assertEqual(self.leftovers(), [])

    def test_upgrade_replaces_in_place_and_keeps_the_players_state(self):
        with open(self.config, "rb") as f:
            before = f.read()
        deploy.deploy(self.build("2.0.4"), self.install)
        exe = deploy.deploy(self.build("2.0.5"), self.install)
        self.assertEqual(exe, os.path.join(self.install, "EqUpdater.exe"))
        self.assertEqual(installed_version(self.install), "2.0.5")
        with open(self.config, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.state), ["config.json"])
        self.assertEqual(self.leftovers(), [])

    def test_the_old_download_folder_is_left_alone(self):
        old = self.build("2.0.4")
        deploy.deploy(self.build("2.0.5"), self.install)
        self.assertTrue(os.path.isfile(os.path.join(old, "EqUpdater.exe")))

    def test_running_it_again_changes_nothing(self):
        build = self.build("2.0.5")
        deploy.deploy(build, self.install)
        deploy.deploy(build, self.install)
        self.assertEqual(installed_version(self.install), "2.0.5")
        self.assertEqual(self.leftovers(), [])

    def test_an_incomplete_build_is_refused(self):
        deploy.deploy(self.build("2.0.4"), self.install)
        broken = os.path.join(self.tmp, "broken")
        os.makedirs(broken)
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(broken, self.install)
        self.assertEqual(installed_version(self.install), "2.0.4")


class TestFailedReplacement(Sandbox):
    """However it fails, the version that worked is still there."""

    def setUp(self):
        super().setUp()
        deploy.deploy(self.build("2.0.4"), self.install)

    def failing(self, on_call):
        calls = []

        def rename(src, dst):
            calls.append((src, dst))
            if len(calls) == on_call:
                raise PermissionError(5, "Access is denied", src)
            os.rename(src, dst)
        return rename

    def test_new_version_cannot_be_moved_in(self):
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(self.build("2.0.5"), self.install,
                          rename=self.failing(on_call=2))
        self.assertEqual(installed_version(self.install), "2.0.4")
        self.assertEqual(self.leftovers(), [])

    def test_current_version_cannot_be_moved_aside(self):
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(self.build("2.0.5"), self.install,
                          rename=self.failing(on_call=1))
        self.assertEqual(installed_version(self.install), "2.0.4")
        self.assertEqual(self.leftovers(), [])

    @unittest.skipUnless(os.name == "nt", "Windows file locking")
    def test_a_running_copy_is_not_replaced(self):
        """A running EqUpdater.exe cannot be opened for writing; hold it the
        same way and the installer must stop before touching anything."""
        import ctypes
        from ctypes import wintypes
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        CreateFileW.restype = wintypes.HANDLE
        GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
        handle = CreateFileW(os.path.join(self.install, "EqUpdater.exe"),
                             GENERIC_READ, 1, None, OPEN_EXISTING, 0, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value)
        try:
            with self.assertRaises(deploy.DeployError) as ctx:
                deploy.deploy(self.build("2.0.5"), self.install)
            self.assertIn("running", str(ctx.exception))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        self.assertEqual(installed_version(self.install), "2.0.4")
        self.assertEqual(self.leftovers(), [])

    def test_an_interrupted_run_is_repaired_by_the_next(self):
        """Stopped between moving the old copy aside and moving the new one
        in: no EqUpdater folder at all. The next run puts the old one back
        before doing anything else."""
        os.rename(self.install, self.install + ".old")
        make_build(self.install + ".new", "half")
        deploy.repair(self.install)
        self.assertEqual(installed_version(self.install), "2.0.4")
        self.assertEqual(self.leftovers(), [])
        deploy.deploy(self.build("2.0.5"), self.install)
        self.assertEqual(installed_version(self.install), "2.0.5")


class TestUnusedCopies(Sandbox):
    def test_old_version_folders_are_named_checkouts_and_home_are_not(self):
        old = self.build("2.0.4")
        new = self.build("2.0.5")
        checkout = make_build(os.path.join(self.tmp, "repo", "dist", "EqUpdater"), "dev")
        os.makedirs(os.path.join(self.tmp, "repo", ".git"))
        exe = deploy.deploy(new, self.install)
        changed = [("Desktop\\EqUpdater.lnk", os.path.join(old, "EqUpdater.exe")),
                   ("Start\\EqUpdater.lnk", os.path.join(checkout, "EqUpdater.exe")),
                   ("Pinned\\EqUpdater.lnk", exe)]
        self.assertEqual(deploy.unused_copies(exe, new, changed),
                         sorted([os.path.join(self.tmp, "EqUpdater-2.0.4"),
                                 os.path.join(self.tmp, "EqUpdater-2.0.5")]))


@unittest.skipUnless(ON_WINDOWS, "Windows shortcuts")
class TestShortcuts(Sandbox):
    """Real .lnk files, written and read through the Windows shell."""

    def setUp(self):
        super().setUp()
        self.desktop = os.path.join(self.tmp, "Desktop")
        self.start = os.path.join(self.tmp, "Start Menu")
        os.makedirs(self.desktop)
        os.makedirs(self.start)
        self.old_exe = os.path.join(self.build("2.0.4"), "EqUpdater.exe")
        self.exe = deploy.deploy(self.build("2.0.5"), self.install)
        self.lnk = os.path.join(self.desktop, "EqUpdater.lnk")
        deploy.write_shortcut(self.lnk, self.old_exe)

    def test_the_legacy_shortcut_is_pointed_at_the_permanent_copy(self):
        self.assertEqual(deploy.read_shortcut(self.lnk)[0], self.old_exe)
        changed = deploy.fix_shortcuts(self.exe, [self.desktop, self.start])
        self.assertEqual(changed, [(self.lnk, self.old_exe)])
        target, workdir = deploy.read_shortcut(self.lnk)
        self.assertEqual(target, self.exe)
        self.assertEqual(workdir, self.install)

    def test_shortcuts_elsewhere_follow_too(self):
        """A Start-menu entry or a pinned taskbar icon, named anything."""
        pinned = os.path.join(self.start, "Eq Updater 2.0.4.lnk")
        deploy.write_shortcut(pinned, self.old_exe)
        deploy.fix_shortcuts(self.exe, [self.desktop, self.start])
        self.assertEqual(deploy.read_shortcut(pinned)[0], self.exe)

    def test_other_programs_shortcuts_are_untouched(self):
        other_exe = os.path.join(self.tmp, "Other", "WoW.exe")
        os.makedirs(os.path.dirname(other_exe))
        open(other_exe, "w").close()
        other = os.path.join(self.desktop, "OctoWoW.lnk")
        deploy.write_shortcut(other, other_exe)
        deploy.fix_shortcuts(self.exe, [self.desktop])
        self.assertEqual(deploy.read_shortcut(other)[0], other_exe)

    def test_fixing_twice_changes_nothing_the_second_time(self):
        deploy.fix_shortcuts(self.exe, [self.desktop])
        self.assertEqual(deploy.fix_shortcuts(self.exe, [self.desktop]), [])

    def run_main(self, *extra):
        out = io.StringIO()
        with mock.patch.object(deploy, "shortcut_folders",
                               lambda: [self.desktop, self.start]), \
                redirect_stdout(out):
            code = deploy.main(["--build", os.path.dirname(self.exe_for_main),
                                "--install-dir", self.install, *extra])
        return code, out.getvalue()

    def test_installer_step_upgrades_and_repoints(self):
        """2.0.4 shortcut on the desktop, 2.0.6 being installed."""
        self.exe_for_main = os.path.join(self.build("2.0.6"), "EqUpdater.exe")
        code, out = self.run_main("--no-shortcut")
        self.assertEqual(code, 0, out)
        self.assertEqual(installed_version(self.install), "2.0.6")
        self.assertEqual(deploy.read_shortcut(self.lnk)[0], self.exe)
        self.assertIn(os.path.join(self.tmp, "EqUpdater-2.0.4"), out)

    def test_fresh_install_offers_a_desktop_shortcut(self):
        os.remove(self.lnk)
        self.exe_for_main = os.path.join(self.build("2.0.6"), "EqUpdater.exe")
        code, out = self.run_main("--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(deploy.read_shortcut(self.lnk),
                         (self.exe, self.install))


if __name__ == "__main__":
    unittest.main()
