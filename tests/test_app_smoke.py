"""The application actually starts, and the safety rules survive the trip
from the planner into the window.

Unit tests prove `plan()` is right. These prove the app is wired to it: that
the mods page, the addon rows and Update All read the planner's answers
rather than their own, which is the mistake the planner exists to prevent and
the kind that only shows up assembled.

Skipped where there is no display.
"""

import gc
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_TK = True
except Exception:                                   # pragma: no cover
    HAVE_TK = False

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Tk / thread lifecycle for every test in this file ────────────────────────
#
# Tcl must delete an interpreter on the thread that created it; deleting one
# anywhere else aborts the process ("Tcl_AsyncDelete: async handler deleted
# by the wrong thread") -- no exception, no traceback, the test run just
# dies. So a Tk object may only ever be freed on this (the main) thread.
#
# Two rules keep it that way:
#
# 1. The background animation's worker holds no Tk object at all (see
#    ui._FrameProducer), and closing an app waits for that worker to exit.
#    `_close_app` fails the test if one survives.
# 2. A closed app is kept referenced until the process exits. Its other
#    background workers (news, update checks) hold references to it and may
#    finish after the test; if the test let go first, the last reference --
#    and the interpreter -- would be dropped on that worker's thread.

_CLOSED_APPS = []


def _animation_threads():
    return [t for t in threading.enumerate()
            if t.name == "bg-animation" and t.is_alive()]


def _wait_for_animation_threads(timeout=3.0):
    """The animation workers still alive after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while _animation_threads() and time.monotonic() < deadline:
        time.sleep(0.02)
    return _animation_threads()


def _close_app(app):
    """Destroy an EqUpdaterApp the way the window's X button does, keep it
    referenced, free what can be freed on this thread, and check that no
    animation worker outlived it."""
    try:
        app.destroy()
    finally:
        _CLOSED_APPS.append(app)
    gc.collect()
    leaked = _wait_for_animation_threads()
    if leaked:
        raise AssertionError("bg-animation worker(s) outlived the app: %r"
                             % leaked)


def tearDownModule():
    leaked = _wait_for_animation_threads()
    assert not leaked, "bg-animation worker(s) leaked: %r" % leaked


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
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_product_identity(self):
        self.assertEqual(self.app.title(), "EqUpdater")
        self.assertEqual(self.app_mod.UA, "EqUpdater/2.0.1")

    def test_settings_live_under_the_new_name(self):
        self.assertIn("EqUpdater", self.app_mod.CONFIG_FILE)

    def test_the_window_carries_the_product_icon(self):
        self.assertIsNotNone(getattr(self.app, "_window_icon_photo", None))

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
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _mod(self, mod_id="ClassicAPI"):
        return next(m for m in self.m.MODS_REGISTRY if m["id"] == mod_id)

    def test_a_newer_remote_is_offered(self):
        state = {"managed": True, "enabled": True,
                 "installed_version": "1.4",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertTrue(self.m.mod_plan(
            self._mod(), state, {"latest_version": "1.5"}).will_update)

    def test_an_older_remote_is_not(self):
        """The headline case, through the app's own entry point."""
        state = {"managed": True, "enabled": True,
                 "installed_version": "V90",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertFalse(self.m.mod_plan(
            self._mod(), state, {"latest_version": "V89"}).will_update)

    def test_an_unmanaged_mod_is_never_offered(self):
        state = {"managed": False, "enabled": True,
                 "installed_version": "1.4",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertFalse(self.m.mod_plan(
            self._mod(), state, {"latest_version": "9.9"}).will_update)

    def test_a_failed_lookup_is_never_offered(self):
        state = {"managed": True, "enabled": True,
                 "installed_version": "1.4",
                 "installed_files": ["ClassicAPI.dll"]}
        self.assertFalse(self.m.mod_plan(self._mod(), state, None).will_update)

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
        for state in ("unmanaged", "modified", "unverifiable", "upToDate",
                      "updateAvailable", "sourceDiffers", "unconfirmed"):
            with self.subTest(state=state):
                self.assertTrue(state == "updateAvailable"
                                or state in self.m.EqUpdaterApp._MPQ_STATES)

    def test_listed_addons_are_offered_but_not_recommended(self):
        taken_off = {"ItemRack", "Magnify", "PallyPowerTW", "pfQuest",
                     "pfQuest-turtle", "pfUI", "SUCC-bag"}
        self.assertFalse(taken_off & set(self.m.RECOMMENDED_ADDONS))
        for name in taken_off:
            with self.subTest(name=name):
                self.assertIn(name, self.m.LISTED_ADDONS)
                self.assertEqual(self.m.CURATED_ADDONS[name],
                                 self.m.LISTED_ADDONS[name])
        self.assertEqual(self.m.RECOMMENDED_ADDONS["Questie-Octo"],
                         "https://github.com/SandreaSub/Questie-Octo")
        self.assertFalse(set(self.m.LISTED_ADDONS) & set(self.m.RECOMMENDED_ADDONS))

    def test_reset_tweaks_asks_first(self):
        """Reset throws away the user's values; it must not happen on one
        click without a yes."""
        from tkinter import messagebox
        saved = []
        real_ask, real_save = messagebox.askyesno, self.m.save_tweaks_config
        self.m.save_tweaks_config = saved.append
        try:
            messagebox.askyesno = lambda *a, **k: False
            self.app._reset_tweaks()
            self.assertEqual(saved, [])
            messagebox.askyesno = lambda *a, **k: True
            self.app._reset_tweaks()
            self.assertEqual(saved, [dict(self.m.TWEAKS_DEFAULTS)])
        finally:
            messagebox.askyesno, self.m.save_tweaks_config = real_ask, real_save

    def test_essential_mods_are_off_by_default(self):
        self.assertFalse(self.app._auto_mods_var.get())

    def test_every_mod_status_is_drawable_or_deliberately_silent(self):
        from equpdater.states import Status
        silent = {Status.UP_TO_DATE, Status.NOT_INSTALLED, Status.DISABLED,
                  Status.IGNORED, Status.ERROR, Status.DIVERGED}
        for status in Status:
            with self.subTest(status=status):
                self.assertTrue(
                    status in self.m.EqUpdaterApp._MOD_ACTIONS
                    or status in silent,
                    f"{status} would draw nothing and read as healthy")


@unittest.skipUnless(HAVE_TK, "no display")
class TestAnimatedBackground(unittest.TestCase):
    """The GIF plays on the Tk timer, loops, and gives way to the still image
    whenever it cannot be played."""

    COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]

    def setUp(self):
        from PIL import Image
        from equpdater import ui
        self.ui, self.Image = ui, Image
        self.tmp = tempfile.mkdtemp(prefix="equ-gif-")
        self.root = tk.Tk()
        self.canvas = tk.Canvas(self.root, width=40, height=30)
        self.canvas.pack()
        self.item = self.canvas.create_image(0, 0, anchor="nw")

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        del self.root, self.canvas
        gc.collect()  # free Tk objects here, on the Tk thread
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.assertEqual(_wait_for_animation_threads(), [],
                         "a bg-animation worker outlived its test")

    def gif(self, frames, name="t.gif"):
        path = os.path.join(self.tmp, name)
        imgs = [self.Image.new("RGB", (32, 18), c) for c in frames]
        imgs[0].save(path, save_all=True, append_images=imgs[1:],
                     duration=30, loop=0)
        return path

    def run_for(self, anim, ms, sample=None):
        def tick():
            if sample:
                sample()
            self.root.after(10, tick)
        self.root.after(10, tick)
        self.root.after(ms, self.root.quit)
        anim.start()
        self.root.mainloop()
        # Wait for the worker: the window is destroyed in tearDown.
        self.assertTrue(anim.stop(wait=3.0), "bg-animation worker did not exit")

    def test_plays_every_frame_and_loops(self):
        seen = []
        anim = self.ui.AnimatedBackground(
            self.root, self.canvas, self.item, self.gif(self.COLOURS),
            40, 30, darken=1.0)

        shown = []

        def sample():
            if anim.photo is not None:
                rgb = tuple(int(v) for v in anim.photo._PhotoImage__photo.get(5, 5))
                if not seen or seen[-1] != rgb:
                    seen.append(rgb)
                shown.append(self.canvas.itemcget(self.item, "image")
                             == str(anim.photo))
        self.run_for(anim, 700, sample)
        self.assertIsNone(anim.error)
        self.assertEqual(set(seen), set(self.COLOURS))
        self.assertGreater(len(seen), len(self.COLOURS))      # came round again
        self.assertEqual(seen[:4], self.COLOURS + [self.COLOURS[0]])
        self.assertTrue(shown and all(shown))                 # drawn on the canvas
        self.assertIsNone(anim.photo)                         # released on stop

    def test_unreadable_gif_falls_back(self):
        path = os.path.join(self.tmp, "broken.gif")
        with open(path, "wb") as f:
            f.write(b"GIF89a not really")
        failed = []
        anim = self.ui.AnimatedBackground(self.root, self.canvas, self.item,
                                          path, 40, 30, on_fail=failed.append)
        self.run_for(anim, 300)
        self.assertEqual(len(failed), 1)
        self.assertTrue(anim._stopped)
        self.assertIsNone(anim.photo)

    def test_a_still_gif_is_not_an_animation(self):
        failed = []
        anim = self.ui.AnimatedBackground(
            self.root, self.canvas, self.item, self.gif(self.COLOURS[:1]),
            40, 30, on_fail=failed.append)
        self.run_for(anim, 300)
        self.assertEqual(len(failed), 1)
        self.assertIn("1 frame", failed[0])

    def test_stop_ends_the_worker(self):
        anim = self.ui.AnimatedBackground(
            self.root, self.canvas, self.item, self.gif(self.COLOURS),
            40, 30)
        self.run_for(anim, 200)                # stops and waits
        self.assertFalse(anim._producer.thread.is_alive())
        self.assertEqual(_animation_threads(), [])

    def test_the_worker_holds_no_tk_object(self):
        """The worker's thread keeps its target alive until it has finished,
        and drops it on that thread. Anything Tk reachable from the target
        would be freed there -- which Tcl answers by aborting the process."""
        from PIL import ImageTk
        anim = self.ui.AnimatedBackground(
            self.root, self.canvas, self.item, self.gif(self.COLOURS), 40, 30)
        anim.start()
        try:
            producer = anim._producer
            self.assertIs(producer.thread._target.__self__, producer)
            seen, stack = set(), [producer]
            while stack:
                obj = stack.pop()
                if id(obj) in seen:
                    continue
                seen.add(id(obj))
                self.assertNotIsInstance(obj, (tk.Misc, tk.Variable,
                                               ImageTk.PhotoImage))
                if isinstance(obj, (list, tuple, set)):
                    stack.extend(obj)
                elif isinstance(obj, dict):
                    stack.extend(obj.values())
                elif obj is producer:
                    stack.extend(vars(obj).values())
        finally:
            self.assertTrue(anim.stop(wait=3.0))


class TestTkTeardownRace(unittest.TestCase):
    """The installer failure, reproduced: a test tears its window down while
    the animation worker is still making a frame, and garbage collection
    then runs on another thread. Before the fix the worker's exit dropped the
    last reference to the window and Tcl aborted the process
    (Tcl_AsyncDelete). Run in a child process, because that abort would take
    the whole test run with it."""

    SCRIPT = textwrap.dedent('''
        import gc, sys, threading, time, tkinter as tk
        sys.path.insert(0, {root!r})
        from equpdater import ui
        real = ui.apply_edge_fades
        def slow(img, layers):             # a frame that takes a while
            time.sleep(0.3)
            return real(img, layers)
        ui.apply_edge_fades = slow
        root = tk.Tk()
        canvas = tk.Canvas(root, width=40, height=30); canvas.pack()
        item = canvas.create_image(0, 0, anchor="nw")
        anim = ui.AnimatedBackground(root, canvas, item, {gif!r}, 40, 30)
        root.after(200, root.quit)
        anim.start(); root.mainloop()
        anim.stop()                        # deliberately no wait
        root.destroy(); del root, canvas, item, anim
        gc.collect()
        def allocate():                    # another thread triggers GC
            for _ in range(40):
                [object() for _ in range(20000)]
                time.sleep(0.02)
        t = threading.Thread(target=allocate); t.start(); t.join()
        print("clean exit")
    ''')

    @unittest.skipUnless(HAVE_TK, "no display")
    def test_teardown_mid_frame_does_not_abort(self):
        script = self.SCRIPT.format(root=ROOT,
                                    gif=os.path.join(ROOT, "bubbles.gif"))
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                proc = subprocess.run([sys.executable, "-c", script],
                                      capture_output=True, text=True,
                                      timeout=60)
                self.assertNotIn("Tcl_AsyncDelete", proc.stderr)
                self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
                self.assertIn("clean exit", proc.stdout)


class TestEdgeFades(unittest.TestCase):
    """The top and bottom fades ease in: nothing at their inner edge, full
    strength at the window edge, and no step anywhere in between."""

    def test_fades_have_no_edge(self):
        from equpdater.ui import edge_fade_layers
        layers = edge_fade_layers(10, 100, "#000000", top=(30, 0.5),
                                  bottom=(40, 0.9))
        (_, top_mask, top_y), (_, bot_mask, bot_y) = layers
        self.assertEqual((top_y, bot_y), (0, 60))
        top = [top_mask.getpixel((0, y)) for y in range(30)]
        bot = [bot_mask.getpixel((0, y)) for y in range(40)]
        self.assertEqual(top, sorted(top, reverse=True))      # fades downwards
        self.assertEqual(bot, sorted(bot))                    # fades upwards
        self.assertLessEqual(top[-1], 3)
        self.assertLessEqual(bot[0], 3)
        self.assertAlmostEqual(top[0], 0.5 * 255, delta=3)
        self.assertAlmostEqual(bot[-1], 0.9 * 255, delta=3)
        steps = [abs(a - b) for a, b in zip(bot, bot[1:])]
        self.assertLessEqual(max(steps), 12)                  # smooth


@unittest.skipUnless(HAVE_TK, "no display")
class TestAnimatedBackgroundSetting(unittest.TestCase):
    """The Settings checkbox, its default, and what the app does with it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-bgset-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app, branding
        cls.m, cls.branding = app, branding
        cls.app = app.EqUpdaterApp()
        for _ in range(8):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def image_on_canvas(self):
        return self.app._bg_canvas.itemcget(self.app._bg_item, "image")

    def test_on_by_default_and_playing(self):
        self.assertTrue(self.app._animated_bg_var.get())
        self.assertIsNotNone(self.app._bg_anim)
        self.assertFalse(self.app._bg_anim._stopped)

    def test_off_shows_the_still_and_is_remembered(self):
        self.app._animated_bg_var.set(False)
        self.app._toggle_animated_background()
        self.assertIsNone(self.app._bg_anim)
        self.assertEqual(self.image_on_canvas(), str(self.app._bg_photo))
        self.assertIs(self.m.load_config()["animated_background"], False)

        self.app._animated_bg_var.set(True)
        self.app._toggle_animated_background()
        self.assertFalse(self.app._bg_anim._stopped)
        self.assertIs(self.m.load_config()["animated_background"], True)

    def test_missing_gif_keeps_the_still(self):
        real = self.branding.animated_background_candidates
        self.branding.animated_background_candidates = lambda: [
            os.path.join(self.tmp, "nope.gif")]
        try:
            self.app._start_bg_animation()
        finally:
            self.branding.animated_background_candidates = real
        self.assertIsNone(self.app._bg_anim)
        self.assertEqual(self.image_on_canvas(), str(self.app._bg_photo))

    def test_failure_restores_the_still(self):
        self.app._start_bg_animation()
        self.app._bg_animation_failed("test")
        self.assertIsNone(self.app._bg_anim)
        self.assertEqual(self.image_on_canvas(), str(self.app._bg_photo))

    def test_header_and_footer_sit_on_the_background(self):
        """No separate header image and no solid footer block: both were
        hard-edged rectangles over the moving background."""
        self.assertIs(self.app._hdr_canvas, self.app._bg_canvas)
        bottoms = [w for w in self.app.place_slaves()
                   if w.winfo_y() + w.winfo_height() >= self.m.WIN_H - 2
                   and w.winfo_width() >= self.m.WIN_W - 2
                   and w is not self.app._bg_canvas]
        self.assertEqual(bottoms, [])
        self.app._status_var.set("status text")
        self.assertEqual(self.app._bg_canvas.itemcget(
            self.app._foot_items["status"], "text"), "status text")

    def test_both_assets_ship(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in (self.branding.BACKGROUND_STATIC,
                     self.branding.BACKGROUND_ANIMATED):
            self.assertTrue(os.path.isfile(os.path.join(root, name)), name)


@unittest.skipUnless(HAVE_TK, "no display")
class TestNewsCadence(unittest.TestCase):
    """The forum is read once at launch and once per refresh click. Never on
    a tab switch, never on a timer, never twice at once."""

    def test_launch_and_refresh_only(self):
        tmp = tempfile.mkdtemp(prefix="equ-news-")
        os.environ["LOCALAPPDATA"] = tmp
        os.environ["XDG_DATA_HOME"] = tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app as m
        calls = {"announcements": 0, "patch": 0}
        item = {"id": "1", "title": "t", "author": None, "date": "",
                "body": "b", "html": "b", "url": "https://octowow.st/forum/viewtopic.php?t=1"}

        def featured():
            calls["announcements"] += 1
            return item

        def patch():
            calls["patch"] += 1
            return [item]
        m.fetch_featured_post, m.fetch_patch_notes = featured, patch

        a = m.EqUpdaterApp()
        seen = {}

        def after_launch():
            seen["launch"] = dict(calls)
            for tab in ("NEWS", "TWEAKS", "NEWS"):
                a._switch_tab(tab)
            a.after(400, after_tabs)

        def after_tabs():
            seen["tabs"] = dict(calls)
            a._load_featured()                 # the Announcements refresh button
            a._load_patch_notes()              # the Changelog refresh button
            a.after(400, after_refresh)

        def after_refresh():
            seen["refresh"] = dict(calls)
            a._feat_loading = True             # a read still in flight
            a._load_featured()
            seen["overlap"] = dict(calls)
            a._feat_loading = False
            a.after(3500, done)                # nothing polls in the meantime

        def done():
            seen["idle"] = dict(calls)
            a.quit()

        a.after(1500, after_launch)
        a.mainloop()
        _close_app(a)
        shutil.rmtree(tmp, ignore_errors=True)

        one, two = {"announcements": 1, "patch": 1}, {"announcements": 2, "patch": 2}
        self.assertEqual(seen["launch"], one)
        self.assertEqual(seen["tabs"], one)
        self.assertEqual(seen["refresh"], two)
        self.assertEqual(seen["overlap"], two)
        self.assertEqual(seen["idle"], two)


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
        _close_app(cls.app)
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
