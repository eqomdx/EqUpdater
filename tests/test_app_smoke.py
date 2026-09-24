"""The application actually starts, and the safety rules survive the trip
from the planner into the window.

Unit tests prove `plan()` is right. These prove the app is wired to it: that
the mods page, the addon rows and Update All read the planner's answers
rather than their own, which is the mistake the planner exists to prevent and
the kind that only shows up assembled.

Skipped where there is no display.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_TK = True
except Exception:                                   # pragma: no cover
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "no display")
class TestAppStarts(unittest.TestCase):
    """Build the real window against a throwaway data directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-app-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app, branding
        cls.app_mod = app
        cls.branding = branding
        cls.app = app.EqUpdaterApp()
        for _ in range(12):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_product_identity(self):
        self.assertEqual(self.app.title(), "EqUpdater")
        self.assertEqual(self.app_mod.UA, "EqUpdater/2.0.1")

    def test_settings_live_under_the_new_name(self):
        self.assertIn("EqUpdater", self.app_mod.CONFIG_FILE)

    def test_the_window_carries_the_product_icon(self):
        icon = getattr(self.app, "_window_icon", "")
        self.assertTrue(icon.lower().endswith(("icon.png", "icon.ico")), icon)

    def test_update_all_starts_faded(self):
        """Nothing is installed in a throwaway folder, so there is nothing to
        update and the button must not invite a click."""
        self.app._refresh_update_all_btn()
        self.assertFalse(self.app._all_ready)


@unittest.skipUnless(HAVE_TK, "no display")
class TestPlannerReachesTheUI(unittest.TestCase):
    """The decisions the window draws are the planner's."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-ui-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.m = app
        cls.app = app.EqUpdaterApp()
        for _ in range(8):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _mod(self, mod_id="ClassicAPI"):
        return next(m for m in self.m.MODS_REGISTRY if m["id"] == mod_id)

    def test_a_newer_remote_is_offered(self):
        state = {"managed": True, "enabled": True,
                 "installed_version": "1.4",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertTrue(self.m.mod_update_available(
            self._mod(), state, {"latest_version": "1.5"}))

    def test_an_older_remote_is_not(self):
        """The headline case, through the app's own entry point."""
        state = {"managed": True, "enabled": True,
                 "installed_version": "V90",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertFalse(self.m.mod_update_available(
            self._mod(), state, {"latest_version": "V89"}))

    def test_an_unmanaged_mod_is_never_offered(self):
        state = {"managed": False, "enabled": True,
                 "installed_version": "1.4",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertFalse(self.m.mod_update_available(
            self._mod(), state, {"latest_version": "9.9"}))

    def test_a_failed_lookup_is_never_offered(self):
        state = {"managed": True, "enabled": True,
                 "installed_version": "1.4",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertFalse(self.m.mod_update_available(self._mod(), state, None))

    def test_ownership_inferred_for_inherited_records(self):
        """A record with no `managed` key came from Octo Updater. A recorded
        version is the evidence that it was installed rather than found."""
        self.assertTrue(self.m.addon_is_managed(
            {"git": "https://github.com/o/r", "sha": "a" * 40}))
        self.assertFalse(self.m.addon_is_managed({"git": None, "sha": None}))
        self.assertFalse(self.m.addon_is_managed(None))

    def test_explicit_unmanaged_beats_inference(self):
        self.assertFalse(self.m.addon_is_managed(
            {"managed": False, "git": "https://github.com/o/r",
             "sha": "a" * 40}))

    def test_every_addon_status_name_is_known_to_the_row(self):
        """A status the row cannot draw falls through to nothing on screen,
        which looks exactly like a working addon."""
        drawable = set(self.m.EqUpdaterApp._ADDON_STATES) | {
            "updateAvailable", "unmanaged", "invalid", "downloading",
            "available"}
        for status in self.m.ADDON_STATUS_NAMES.values():
            with self.subTest(status=status):
                self.assertIn(status, drawable)

    def test_every_texture_pack_state_is_drawable(self):
        """updateAvailable draws a button; everything else needs words."""
        from equpdater import mpq
        for state in mpq.STATES:
            with self.subTest(state=state):
                self.assertTrue(state == "updateAvailable"
                                or state in self.m.EqUpdaterApp._MPQ_STATES)

    def test_essential_mods_are_off_by_default(self):
        self.assertFalse(self.app._auto_mods_var.get())

    def test_every_mod_status_is_drawable_or_deliberately_silent(self):
        from equpdater.states import Status
        silent = {Status.UP_TO_DATE, Status.NOT_INSTALLED, Status.DISABLED,
                  Status.IGNORED, Status.ERROR, Status.INSTALLING,
                  Status.UPDATING, Status.DIVERGED}
        for status in Status:
            with self.subTest(status=status):
                self.assertTrue(
                    status in self.m.EqUpdaterApp._MOD_ACTIONS
                    or status in silent,
                    f"{status} would draw nothing and read as healthy")


class TestTexturePackDownload(unittest.TestCase):
    """Replacing a pack keeps the user's copy; a bad checksum keeps nothing
    new and touches nothing old."""

    def setUp(self):
        import io
        import hashlib
        from equpdater import app, mpq
        self.m, self.mpq, self.io = app, mpq, io
        self.data = tempfile.mkdtemp(prefix="equ-data-")
        self.path = os.path.join(self.data, "patch-Z.mpq")
        with open(self.path, "wb") as f:
            f.write(b"theirs")
        self.body = b"the source's build"
        self.sha = hashlib.sha256(self.body).hexdigest()
        self._real = app.secure_urlopen

        class Resp(io.BytesIO):
            headers = {}
            def __enter__(s): return s
            def __exit__(s, *a): s.close()
        app.secure_urlopen = lambda *a, **kw: Resp(self.body)

    def tearDown(self):
        self.m.secure_urlopen = self._real
        shutil.rmtree(self.data, ignore_errors=True)

    def remote(self, sha):
        return self.mpq.Remote(sha, None, "https://github.com/o/r/x.mpq")

    def test_replace_keeps_their_file(self):
        got = self.m.download_mpq(self.remote(self.sha), self.data,
                                  "patch-Z.mpq", keep_existing=True)
        self.assertEqual(got, self.sha)
        kept = [n for n in os.listdir(self.data) if n.endswith(".bak")]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.data, kept[0]), "rb") as f:
            self.assertEqual(f.read(), b"theirs")
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), self.body)

    def test_a_bad_checksum_changes_nothing(self):
        with self.assertRaises(RuntimeError):
            self.m.download_mpq(self.remote("0" * 64), self.data,
                                "patch-Z.mpq", keep_existing=True)
        self.assertEqual(sorted(os.listdir(self.data)), ["patch-Z.mpq"])
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"theirs")


@unittest.skipUnless(HAVE_TK, "no display")
class TestNoDllWithoutConsent(unittest.TestCase):
    """Against a real client folder: nothing is installed unless the user
    said yes, and nothing is ever installed over a DLL already there."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-dll-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.m = app
        cls.app = app.EqUpdaterApp()
        for _ in range(8):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.client = tempfile.mkdtemp(prefix="client-", dir=self.tmp)
        open(os.path.join(self.client, "WoW.exe"), "wb").close()
        self.app._game_path.set(self.client)
        self.app._default_mods_install_started = False
        self.app._mod_pending_state.clear()
        self.m.update_config(lambda c: [c.pop(k, None) for k in
                                        ("mods", "essential_mods_asked",
                                         "auto_install_mods")])
        self.threads = []
        self._real_thread = self.m.threading.Thread
        self.m.threading.Thread = lambda *a, **kw: self.threads.append(kw) or \
            type("T", (), {"start": lambda s: None})()

    def tearDown(self):
        self.m.threading.Thread = self._real_thread

    def test_declining_installs_nothing_not_even_vanillafixes(self):
        asked = []
        self.app._ask_essential_mods = lambda mods: asked.append(mods) or False
        self.app._maybe_install_essential_mods()
        del self.app._ask_essential_mods
        self.assertEqual(len(asked), 1)
        self.assertIn("VanillaFixes", [m["id"] for m in asked[0]])
        self.assertEqual(self.threads, [])
        self.assertEqual(self.app._mod_pending_state, {})

    def test_the_question_is_asked_once(self):
        self.m.update_config(lambda c: c.update(essential_mods_asked=True,
                                                auto_install_mods=False))
        self.app._ask_essential_mods = lambda mods: self.fail("asked twice")
        self.app._maybe_install_essential_mods()
        del self.app._ask_essential_mods
        self.assertEqual(self.threads, [])

    def test_a_discovered_dll_is_not_installed_over(self):
        """The first-run install used to overwrite exactly these: recorded
        unmanaged, enabled, no version -- which read as 'wanted, missing'."""
        mod = next(m for m in self.m.MODS_REGISTRY if m["id"] == "ClassicAPI")
        for f in mod["installed_files"]:
            with open(os.path.join(self.client, f), "wb") as fh:
                fh.write(b"the user's own build")
        self.app._discover_existing_mods(self.client)
        self.app._install_missing_essential_mods()
        self.assertNotIn("ClassicAPI", self.app._mod_pending_state)

        installs = []
        real = self.m.install_mod
        self.m.install_mod = lambda *a, **kw: installs.append(a) or []
        try:
            self.app._apply_mods_worker(self.client, only_mod_id=None)
        finally:
            self.m.install_mod = real
        self.assertNotIn(mod, [a[0] for a in installs])
        with open(os.path.join(self.client, mod["installed_files"][0]), "rb") as fh:
            self.assertEqual(fh.read(), b"the user's own build")


if __name__ == "__main__":
    unittest.main()
