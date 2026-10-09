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

# Every app here starts on an empty profile, which is a first launch, and a
# first launch waits for the language picker. TestFirstLanguage drives the
# picker itself.
os.environ["EQUPDATER_NO_LANGUAGE_PROMPT"] = "1"


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
        self.assertEqual(self.app_mod.UA, "EqUpdater/2.0.6")

    def test_settings_live_under_the_new_name(self):
        self.assertIn("EqUpdater", self.app_mod.CONFIG_FILE)

    def test_default_game_folder_is_not_inside_the_app(self):
        """An update replaces the app's folder (and an AppImage's is a
        read-only mount): a game there would be deleted or unwritable."""
        game = os.path.normcase(os.path.abspath(self.app_mod.DEFAULT_GAME_DIR))
        app_dir = os.path.normcase(os.path.abspath(self.app_mod.APP_DIR))
        self.assertFalse(game.startswith(app_dir + os.sep), game)
        self.assertEqual(os.path.basename(game).lower(), "octowow")

    def test_the_window_carries_the_product_icon(self):
        self.assertIsNotNone(getattr(self.app, "_window_icon_photo", None))

    def test_update_all_starts_faded(self):
        """Nothing is installed in a throwaway folder, so there is nothing to
        update and the button must not invite a click."""
        self.app._refresh_update_all_btn()
        self.assertFalse(self.app._all_ready)

    def test_game_environment_variables_are_saved_and_checked(self):
        """Settings -> Game launcher -> Environment variables: saved as typed,
        shown again next time, and a bad line named at once."""
        tk, m = self.app_mod.tk, self.app_mod

        def build():
            frame = tk.Frame(self.app)
            frame.pack()
            self.app._build_game_launcher_settings(frame, "#000000",
                                                   "#111111", "#222222")
            self.app.update()
            return frame, self.app._env_vars_box, self.app._env_vars_error

        def type_into(box, text):
            box.delete("1.0", "end")
            box.insert("1.0", text)
            self.app.update()

        frame, box, error = build()
        try:
            self.assertFalse(error.winfo_ismapped())
            text = "DXVK_HUD=fps\nWINEDLLOVERRIDES=d3d9=n,b\nbroken line"
            type_into(box, text)
            self.assertEqual(m.load_config()["game_launcher"]["env_vars"], text)
            self.assertTrue(error.winfo_ismapped())
            self.assertIn("3", error.cget("text"))
            frame.destroy()

            frame, box, error = build()          # Settings opened again
            self.assertEqual(box.get("1.0", "end-1c"), text)
            self.assertTrue(error.winfo_ismapped())
            type_into(box, "DXVK_HUD=fps\n")
            self.assertFalse(error.winfo_ismapped())
            self.assertEqual(m.load_config()["game_launcher"]["env_vars"],
                             "DXVK_HUD=fps\n")
            type_into(box, "")
            self.assertEqual(m.load_config()["game_launcher"]["env_vars"], "")
        finally:
            frame.destroy()
            m.update_config(lambda c: c.pop("game_launcher", None))

    def test_linux_settings_fit_and_open_the_game_launcher(self):
        """On Linux the launcher's fields used to sit in Settings' left
        column and, in OpenDyslexic, pushed its last row (SUPPORT ME) out of
        the panel. They are in a panel of their own, opened from Settings."""
        from unittest import mock
        app, m = self.app, self.app_mod

        def find(root, text):
            if getattr(root, "cget", None) and isinstance(root, m.tk.Label) \
                    and root.cget("text") == text:
                return root
            for child in root.winfo_children():
                hit = find(child, text)
                if hit is not None:
                    return hit
            return None

        def bottom(w):
            return w.winfo_rooty() + w.winfo_height()

        # A first run opens Settings by itself 500 ms after start, built for
        # the real platform (on Windows: no Game launcher item). Whether that
        # has fired yet is timing; drop it so this test builds its own.
        app.update()
        if app._settings_overlay is not None:
            app._settings_overlay.destroy()
            app._settings_overlay = None
        with mock.patch.object(m.platforms, "WINDOWS", False), \
                mock.patch.object(m.platforms, "LINUX", True):
            try:
                for choice in ("arial", "friz", "opendyslexic"):
                    with self.subTest(font=choice):
                        app._font_choice_var.set(choice)
                        app._change_font_choice()
                        app._open_settings()
                        app.update()
                        ov = app._settings_overlay
                        panel = ov.winfo_children()[0]
                        last = find(ov, m.tr("Buy Me a Coffee"))
                        self.assertIsNotNone(last)
                        self.assertLessEqual(bottom(last), bottom(panel))
                        self.assertIsNone(find(ov, m.tr("Environment variables")))

                        item = find(ov, m.tr("Game launcher…"))
                        item.event_generate("<Button-1>")
                        app.update()
                        shade = app._launcher_overlay
                        self.assertIsNotNone(shade)
                        box = find(shade, m.tr("Environment variables"))
                        self.assertIsNotNone(box)
                        launcher = shade.winfo_children()[0]
                        self.assertLessEqual(bottom(app._env_vars_box),
                                             bottom(launcher))
                        app.event_generate("<Escape>")    # closes the panel...
                        app.update()
                        self.assertIsNone(app._launcher_overlay)
                        self.assertIsNotNone(app._settings_overlay)  # ...only
                        app._open_game_launcher()
                        app._close_settings()
                        self.assertIsNone(app._launcher_overlay)
            finally:
                if app._settings_overlay is not None:
                    app._close_settings()
                app._font_choice_var.set("arial")
                app._change_font_choice()


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

    def gif(self, frames, name="t.gif", duration=30):
        path = os.path.join(self.tmp, name)
        imgs = [self.Image.new("RGB", (32, 18), c) for c in frames]
        imgs[0].save(path, save_all=True, append_images=imgs[1:],
                     duration=duration, loop=0)
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
        """Every frame, in order, then round again.

        Sampled every 10 ms, so a frame shown for less than that between two
        samples is missed -- which a loaded CI machine does produce (it once
        dropped the second pass's first frame). So frames last 80 ms, strict
        order is asserted on the first pass, and "round again" is the
        sequence wrapping back to an earlier frame, not one exact frame."""
        seen = []
        anim = self.ui.AnimatedBackground(
            self.root, self.canvas, self.item,
            self.gif(self.COLOURS, duration=80), 40, 30, darken=1.0)

        shown = []

        def sample():
            if anim.photo is not None:
                rgb = tuple(int(v) for v in anim.photo._PhotoImage__photo.get(5, 5))
                if not seen or seen[-1] != rgb:
                    seen.append(rgb)
                shown.append(self.canvas.itemcget(self.item, "image")
                             == str(anim.photo))
        self.run_for(anim, 1200, sample)
        self.assertIsNone(anim.error)
        self.assertEqual(set(seen), set(self.COLOURS))
        self.assertEqual(seen[:3], self.COLOURS)              # in order
        order = [self.COLOURS.index(c) for c in seen]
        self.assertTrue(any(b < a for a, b in zip(order, order[1:])),
                        f"never came round again: {seen}")
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
        # The Settings overlay covers the whole window, and on a first run it
        # opens 500 ms after start -- before this test on a slow machine
        # (CI failed on that alone). It is a modal, not a footer block.
        bottoms = [w for w in self.app.place_slaves()
                   if w.winfo_y() + w.winfo_height() >= self.m.WIN_H - 2
                   and w.winfo_width() >= self.m.WIN_W - 2
                   and w is not self.app._bg_canvas
                   and w is not self.app._settings_overlay]
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
class TestFontList(unittest.TestCase):
    """Settings' font list: every face is available out of the box, and each
    name is drawn in its own face whichever one is selected."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-fonts-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        import tkinter.font as tkfont
        cls.tkfont, cls.tk = tkfont, tk
        cls.app = app.EqUpdaterApp()
        for _ in range(8):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def rows(self):
        found = []

        def walk(w):
            if getattr(w, "font_choice", None):
                found.append(w)
            for c in w.winfo_children():
                walk(c)
        walk(self.app)
        return {w.font_choice: self.tkfont.Font(
                    root=self.app, font=w.cget("font")).actual("family")
                for w in found}

    def test_every_face_ships(self):
        """No zip to find, nothing to install: a fresh profile has all three."""
        f = self.app._fonts
        self.assertTrue(f.arial_available)
        self.assertTrue(f.friz_available)
        self.assertTrue(f.dyslexic_available)

    def test_each_name_is_drawn_in_its_own_face(self):
        f = self.app._fonts
        expected = {"arial": f.arial, "friz": f.friz,
                    "opendyslexic": f.open_dyslexic}
        if self.app._settings_overlay is None:
            self.app._open_settings()
        self.app.update()
        try:
            self.assertEqual(self.rows(), expected)
            for choice in ("opendyslexic", "friz", "arial"):
                self.app._font_choice_var.set(choice)
                self.app._change_font_choice()
                self.app.update()
                self.assertEqual(self.rows(), expected, choice)
        finally:
            self.app._font_choice_var.set("arial")
            self.app._change_font_choice()

    def test_dots_line_up_with_the_letters(self):
        """Each dot is centred on its name's capitals, and the rows are
        evenly spaced -- OpenDyslexic's tall line box used to lift its dot
        above the text."""
        if self.app._settings_overlay is None:
            self.app._open_settings()
        self.app.update()
        names = []

        def walk(w):
            if getattr(w, "font_choice", None):
                names.append(w)
            for c in w.winfo_children():
                walk(c)
        walk(self.app)
        self.assertEqual(len(names), 3)
        tops = []
        for name in names:
            dot = [w for w in name.master.winfo_children()
                   if isinstance(w, self.tk.Radiobutton)][0]
            ascent, cap, _ = self.app._fonts.ink_metrics(name.font_choice, 10)
            dot_mid = dot.winfo_rooty() + dot.winfo_height() / 2
            cap_mid = name.winfo_rooty() + ascent - cap / 2
            self.assertLessEqual(abs(dot_mid - cap_mid), 1.5, name.font_choice)
            tops.append(name.master.winfo_rooty())
        steps = {b - a for a, b in zip(tops, tops[1:])}
        self.assertEqual(len(steps), 1, steps)

    def test_clicking_a_name_chooses_it(self):
        if self.app._settings_overlay is None:
            self.app._open_settings()
        self.app.update()
        found = []

        def walk(w):
            if getattr(w, "font_choice", None) == "friz":
                found.append(w)
            for c in w.winfo_children():
                walk(c)
        walk(self.app)
        try:
            found[0].event_generate("<Button-1>")
            self.app.update()
            self.assertEqual(self.app._fonts.choice, "friz")
        finally:
            self.app._font_choice_var.set("arial")
            self.app._change_font_choice()


@unittest.skipUnless(HAVE_TK, "no display")
class TestLanguage(unittest.TestCase):
    """EqUpdater speaks the saved Game Language, and offers a restart --
    asked in the new language -- when that changes."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-lang-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app, i18n
        cls.m, cls.i18n = app, i18n
        app.save_tweaks_config({**app.TWEAKS_DEFAULTS, "locale": "deDE"})
        cls.app = app.EqUpdaterApp()
        for _ in range(8):
            cls.app.update()
        # Read now: other tests here switch the language for a moment, and a
        # late status update during one would be in that language.
        cls.status_at_start = cls.app._status_var.get()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        cls.i18n.set_language("enUS")
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.m.save_tweaks_config({**self.m.TWEAKS_DEFAULTS, "locale": "deDE"})

    def ask(self):
        from unittest import mock
        asked = []
        with mock.patch("tkinter.messagebox.askyesno",
                        lambda title, body, **kw: asked.append(title) or False):
            self.app._offer_language_restart()
        return asked

    def test_the_window_speaks_the_game_language(self):
        self.assertEqual(self.i18n.language(), "deDE")
        # Either, depending on whether the start-up check has answered yet:
        # what matters is that the status line is in German.
        german = {self.i18n.tr("Ready to update"),
                  self.i18n.tr("Update available!")}
        self.assertNotIn("Ready to update", german)
        self.assertIn(self.status_at_start, german)

    def test_same_language_asks_nothing(self):
        self.assertEqual(self.ask(), [])

    def test_a_new_language_is_offered_in_that_language(self):
        self.m.save_tweaks_config({**self.m.TWEAKS_DEFAULTS, "locale": "ruRU"})
        asked = self.ask()
        self.assertEqual(asked, ["Перезапустить EqUpdater?"])
        # Declined: the window carries on in the language it was drawn in.
        self.assertEqual(self.i18n.language(), "deDE")

    def test_chinese_is_offered_in_chinese(self):
        self.m.save_tweaks_config({**self.m.TWEAKS_DEFAULTS, "locale": "zhCN"})
        self.assertEqual(self.ask(), ["重启 EqUpdater？"])

    def test_font_section_greyed_only_in_chinese(self):
        """Chinese letters come from Windows' own font whatever is picked,
        so in Chinese the font list is shown but cannot be used."""
        def font_dots():
            found = []

            def walk(w):
                if getattr(w, "font_choice", None):
                    found.extend(c for c in w.master.winfo_children()
                                 if isinstance(c, tk.Radiobutton))
                for c in w.winfo_children():
                    walk(c)
            walk(self.app)
            return found

        def drop_settings():
            # Not _close_settings: closing is "confirm", which runs the
            # game-folder checks. Only the drawing is under test here.
            if self.app._settings_overlay is not None:
                self.app._settings_overlay.destroy()
                self.app._settings_overlay = None

        for lang, state in (("deDE", "normal"), ("zhCN", "disabled")):
            self.i18n.set_language(lang)
            drop_settings()
            self.app._open_settings()
            self.app.update()
            try:
                dots = font_dots()
                self.assertEqual(len(dots), 3)
                self.assertEqual({str(d.cget("state")) for d in dots},
                                 {state}, lang)
            finally:
                drop_settings()
                self.i18n.set_language("deDE")

    def shown(self):
        return {name for name, w in (("apply", self.app._tweaks_apply_btn),
                                     ("reset", self.app._tweaks_reset_btn))
                if w.winfo_manager()}

    def test_reset_stays_while_a_custom_value_is_saved(self):
        """German saved, English picked: the screen shows the defaults, but
        Reset still has German to put back, so it stays beside Apply."""
        self.app._refresh_tweaks_panel()
        self.app._tweak_vars["locale"].set("enUS")
        self.assertEqual(self.shown(), {"apply", "reset"})
        self.app._tweak_vars["locale"].set("ruRU")
        self.assertEqual(self.shown(), {"apply", "reset"})

    def test_no_reset_when_everything_is_default(self):
        self.m.save_tweaks_config(dict(self.m.TWEAKS_DEFAULTS))
        self.app._refresh_tweaks_panel()
        try:
            self.assertEqual(self.shown(), set())
        finally:
            self.m.save_tweaks_config({**self.m.TWEAKS_DEFAULTS, "locale": "deDE"})
            self.app._refresh_tweaks_panel()


@unittest.skipUnless(HAVE_TK, "no display")
class TestFirstLanguage(unittest.TestCase):
    """The first-launch picker: one button per language, the choice saved as
    the Language tweak, closing it keeps what is saved."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-firstlang-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.m = app
        cls.app = app.EqUpdaterApp()
        for _ in range(4):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.m.save_tweaks_config(dict(self.m.TWEAKS_DEFAULTS))

    def run_picker(self, act):
        """Open the picker; once it is up, ``act(window, buttons)``."""
        def when_open():
            win = getattr(self.app, "_language_prompt", None)
            if win is None:
                self.app.after(20, when_open)
                return
            buttons = {}

            def walk(w):
                if getattr(w, "language", None):
                    buttons[w.language] = w
                for c in w.winfo_children():
                    walk(c)
            walk(win)
            self.seen = sorted(buttons)
            act(win, buttons)
        self.app.after(20, when_open)
        self.app._ask_first_language()

    def test_every_language_is_offered(self):
        self.run_picker(lambda win, b: win.destroy())
        self.assertEqual(self.seen, sorted(self.m.LOCALES))

    def test_the_choice_is_saved_as_the_language(self):
        self.run_picker(lambda win, b: b["ruRU"].event_generate("<Button-1>"))
        self.assertEqual(self.m.load_tweaks_config()["locale"], "ruRU")

    def test_closing_keeps_what_is_saved(self):
        self.m.save_tweaks_config({**self.m.TWEAKS_DEFAULTS, "locale": "esES"})
        self.run_picker(lambda win, b: win.destroy())
        self.assertEqual(self.m.load_tweaks_config()["locale"], "esES")

    def test_ask_language_flag_asks_once_on_an_existing_install(self):
        """Settings kept, picker shown at the next launch, then never again."""
        from unittest import mock
        self.m.update_config(lambda c: c.__setitem__("ask_language", True))
        asked = []
        os.environ.pop("EQUPDATER_NO_LANGUAGE_PROMPT", None)
        try:
            with mock.patch.object(self.m.EqUpdaterApp, "_ask_first_language",
                                   lambda app: asked.append(True)):
                for _ in range(2):
                    # Not _close_app: it waits for *every* animation worker,
                    # and this class's own app is still running one.
                    extra = self.m.EqUpdaterApp()
                    try:
                        extra.destroy()
                    finally:
                        _CLOSED_APPS.append(extra)
        finally:
            os.environ["EQUPDATER_NO_LANGUAGE_PROMPT"] = "1"
        self.assertEqual(asked, [True])
        self.assertNotIn("ask_language", self.m.load_config())


@unittest.skipUnless(HAVE_TK, "no display")
class TestCustomAddonDialog(unittest.TestCase):
    """The link is checked as it is typed: green when it will work, and an
    error from an earlier Install never outlives the text it was about."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-custom-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.m = app
        cls.app = app.EqUpdaterApp()
        for _ in range(4):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        if self.app._settings_overlay is not None:
            self.app._settings_overlay.destroy()
            self.app._settings_overlay = None
        self.app._open_custom_addon_dialog()
        self.app.update()
        self.url = self.app._custom_addon_url
        self.status = self.app._custom_addon_status

    def tearDown(self):
        if self.app._settings_overlay is not None:
            self.app._settings_overlay.destroy()
            self.app._settings_overlay = None

    def press_install(self):
        install = self.m.tr("Install")

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label) and c.cget("text") == install:
                    return c
                hit = walk(c)
                if hit is not None:
                    return hit
        walk(self.app._settings_overlay).event_generate("<Button-1>")
        self.app.update()

    def test_a_valid_link_says_so_in_green(self):
        self.url.set("https://octowow.st/git/olzon/GuildRecipes_Octo")
        self.assertEqual(self.status.cget("text"),
                         "Valid URL. Click Install to continue.")
        self.assertEqual(self.status.cget("fg"), self.m.C_OK)

    def test_half_typed_is_not_scolded(self):
        self.url.set("https://octowow.st/git/olz")
        self.assertEqual(self.status.cget("text"), "")

    def test_an_old_error_clears_once_the_link_is_right(self):
        self.url.set("https://octowow.st/git/olz")
        self.press_install()
        self.assertEqual(self.status.cget("text"),
                         "URL must be https from an allowed host.")
        self.assertEqual(self.status.cget("fg"), self.m.C_ERR)
        self.url.set("https://octowow.st/git/olzon/GuildRecipes_Octo")
        self.assertEqual(self.status.cget("fg"), self.m.C_OK)


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


@unittest.skipUnless(HAVE_TK, "no display")
class TestAddonSectionToggle(unittest.TestCase):
    """Expanding or collapsing an addon section swaps in the finished list in
    one step. It used to empty the list, jump to the top and refill it batch
    by batch on screen -- the "brief visual glitch" a Linux tester saw."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-addon-toggle-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.app = app.EqUpdaterApp()
        cls.app._addons_verify = lambda *a, **k: None   # no network, no disk
        cls.app._switch_tab("ADDONS")
        for _ in range(6):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        a = self.app
        a._addon_sections_open.clear()
        a._addons_status = {
            "state": "done", "addons": {},
            "available": [{"folder": "Addon%03d" % i, "status": "available",
                           "toc": {"Title": "Addon %d" % i}}
                          for i in range(80)]}
        a._render_addons()
        self.finish()

    def shown(self):
        cv = self.app._addons_canvas
        return cv.nametowidget(cv.itemcget(self.app._addons_win, "window"))

    def click_header(self, title):
        """Click a section's header, as the player does."""
        for child in self.shown().winfo_children():
            for label in child.winfo_children():
                if isinstance(label, tk.Label) and label.cget("text") == title:
                    label.event_generate("<Button-1>")
                    return
        self.fail("no %s header" % title)

    def finish(self):
        """Run the batched build to the end, checking at every step that
        what is on screen is a finished list, never a partial one."""
        # Bounded by time, not by update() calls: each batch is an after(1),
        # and Windows' timer only makes it due every ~15 ms, so most calls
        # there find nothing to run yet.
        deadline = time.monotonic() + 30
        while self.app._addons_build_queue:
            self.app.update()
            self.assertLess(time.monotonic(), deadline,
                            "the build never finished")
            time.sleep(0.002)
            if self.app._addons_build_queue:
                self.assertIsNot(self.shown(), self.app._addons_inner,
                                 "a half-built list is on screen")
        self.app.update()

    def test_collapse_and_expand_swap_in_a_finished_list(self):
        cv = self.app._addons_canvas
        full = self.shown()
        rows_full = len(full.winfo_children())
        cv.yview_moveto(0.5)
        self.app.update()
        before = cv.yview()[0]

        self.click_header("MANAGED")
        self.assertFalse(self.app._addon_sections_open["MANAGED"])
        self.assertIs(self.shown(), full)        # still the old list
        self.assertTrue(full.winfo_exists())
        self.finish()

        new = self.shown()
        self.assertIsNot(new, full)
        self.assertFalse(full.winfo_exists())   # the old list is gone
        self.assertEqual(len(new.winfo_children()), rows_full - 1)
        # Scroll region set from the finished list, position kept.
        region = [float(v) for v in str(cv.cget("scrollregion")).split()]
        self.assertEqual(region[3], new.winfo_reqheight())
        self.assertAlmostEqual(cv.yview()[0], before, delta=0.02)

    def test_a_collapsed_section_has_no_rows(self):
        self.click_header("AVAILABLE")
        self.finish()
        # Three headers and the two "Nothing here." lines.
        self.assertEqual(len(self.shown().winfo_children()), 5)

    def test_a_superseded_build_is_discarded(self):
        self.app._render_addons()
        first = self.app._addons_inner
        self.app._render_addons()
        self.assertFalse(first.winfo_exists())
        self.finish()
        self.assertIs(self.shown(), self.app._addons_inner)


@unittest.skipUnless(HAVE_TK, "no display")
class TestLoginDoctorWindow(unittest.TestCase):
    """Settings -> Login Doctor: shows the checks, repairs only after
    confirming, refuses while the game runs, and runs again afterwards.
    The network checks are replaced; nothing here goes online."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-doctor-ui-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.m = app
        cls.app = app.EqUpdaterApp()
        for _ in range(4):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from unittest import mock
        ld = self.m.logindoctor
        self.client = tempfile.mkdtemp(prefix="client-", dir=self.tmp)
        with open(os.path.join(self.client, "WoW.exe"), "wb") as f:
            f.truncate(5_000_000)
        with open(os.path.join(self.client, "realmlist.wtf"), "wb") as f:
            f.write(b"set realmlist octowow.st\r\n")
        self.app._game_path.set(self.client)
        net = [ld.Check(ld.PASS, "{host} resolves", {"host": h}, "network")
               for h in ld.DNS_HOSTS]
        for p in (mock.patch.object(ld, "network_checks", return_value=net),
                  mock.patch.object(self.m, "get_client_version",
                                    return_value="1.18.1 (7272)"),
                  mock.patch.object(self.m.platforms, "client_in_use",
                                    return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        self.app._open_settings()
        self.app.update()

    def tearDown(self):
        # Not _close_settings(): closing Settings is "Confirm", which on a
        # fresh app (a first run) offers a reconcile -- and on Windows asks
        # about a Defender exclusion in a real dialog that nobody answers.
        if self.app._settings_overlay is not None:
            self.app._settings_overlay.destroy()
            self.app._settings_overlay = None
            self.app._doctor_overlay = None
        self.app._game_path.set("")

    def open_doctor(self):
        def find(root, text):
            if isinstance(root, self.m.tk.Label) and root.cget("text") == text:
                return root
            for child in root.winfo_children():
                hit = find(child, text)
                if hit is not None:
                    return hit
        find(self.app._settings_overlay,
             self.m.tr("Login Doctor…")).event_generate("<Button-1>")
        self.wait()

    def wait(self):
        deadline = time.monotonic() + 10
        while self.app._doctor_state["network"] is None:
            self.app.update()
            time.sleep(0.01)
            self.assertLess(time.monotonic(), deadline)
        self.app.update()

    def text(self):
        return self.app._doctor_text.get("1.0", "end")

    def test_shows_problems_then_repairs_and_runs_again(self):
        from unittest import mock
        self.open_doctor()
        self.assertIn("✗  realmlist.wtf uses the old address octowow.st", self.text())
        self.assertNotIn("No local login problem", self.text())
        self.assertEqual(self.app._doctor_repair_btn.cget("cursor"), "hand2")
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as ask:
            self.app._doctor_repair_btn.event_generate("<Button-1>")
            self.wait()
        self.assertIn("realmlist.wtf", ask.call_args[0][1])     # files listed
        self.assertIn(".octobak", ask.call_args[0][1])
        with open(os.path.join(self.client, "realmlist.wtf"), "rb") as f:
            self.assertEqual(f.read(), b"set realmlist play.octowow.st\r\n")
        self.assertTrue(os.path.exists(
            os.path.join(self.client, "realmlist.wtf.octobak")))
        self.assertIn("✓  realmlist.wtf uses play.octowow.st", self.text())
        self.assertIn("No local login problem was found.", self.text())
        self.assertNotEqual(self.app._doctor_repair_btn.cget("cursor"), "hand2")

    def test_declining_changes_nothing(self):
        from unittest import mock
        self.open_doctor()
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            self.app._repair_login_config()
        with open(os.path.join(self.client, "realmlist.wtf"), "rb") as f:
            self.assertEqual(f.read(), b"set realmlist octowow.st\r\n")

    def test_refuses_while_the_game_runs(self):
        from unittest import mock
        self.open_doctor()
        with mock.patch.object(self.m.platforms, "client_in_use", return_value=True), \
                mock.patch("tkinter.messagebox.showerror") as err, \
                mock.patch("tkinter.messagebox.askyesno") as ask:
            self.app._repair_login_config()
            self.wait()
        err.assert_called_once()
        ask.assert_not_called()
        self.assertIn("The game is running", self.text())
        self.assertNotEqual(self.app._doctor_repair_btn.cget("cursor"), "hand2")
        with open(os.path.join(self.client, "realmlist.wtf"), "rb") as f:
            self.assertEqual(f.read(), b"set realmlist octowow.st\r\n")


@unittest.skipUnless(HAVE_TK, "no display")
class TestAnnouncementsSource(unittest.TestCase):
    """Announcements: news.json first; when it fails, the last good
    announcement stays (on screen and in the cache); the forum is read only
    with nothing cached. A malformed, failed or validly empty feed never
    replaces the cache. All sources are replaced; nothing goes online."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-announce-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app as m, news
        cls.m, cls.news = m, news
        cls.app = m.EqUpdaterApp()
        for _ in range(4):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    FEED = {"id": "feed-1", "title": "From news.json", "date": "2026-10-08",
            "body": "feed body", "html": "", "author": None,
            "url": "https://octowow.st/forum/viewtopic.php?t=9"}
    FORUM = {"id": "2595", "title": "From the forum", "date": "", "body": "x",
             "html": "x", "author": "K", "url": "https://octowow.st/forum/viewtopic.php?t=2595"}
    CACHED = {"id": "old", "title": "Cached", "date": "2026-09-01", "body": "c",
              "html": "", "author": None, "url": None}

    def run_load(self, feed, forum=None, cached=None):
        """Load the Announcements with ``feed`` (an item, None for an empty
        feed, or an exception) and ``forum`` likewise; return (shown item,
        cached item, forum called)."""
        from unittest import mock
        m, a = self.m, self.app
        a._featured = cached
        m.update_config(lambda c: c.setdefault("news_cache", {}).__setitem__(
            "announcements", {"item": cached} if cached else {}))
        forum_calls = []

        def from_feed():
            if isinstance(feed, Exception):
                raise feed
            return feed

        def from_forum():
            forum_calls.append(1)
            if isinstance(forum, Exception):
                raise forum
            return forum
        class Inline:
            """The worker, run on this thread: its after(0, apply) then
            needs no running mainloop."""
            def __init__(self, target, **_kw):
                self.target = target

            def start(self):
                self.target()
        with mock.patch.object(m, "fetch_featured_post", from_feed), \
                mock.patch.object(m, "fetch_featured_post_from_forum", from_forum), \
                mock.patch.object(m.threading, "Thread", Inline):
            a._feat_loading = False
            a._load_featured()
            deadline = time.monotonic() + 10
            while a._feat_loading:
                a.update()
                time.sleep(0.01)
                self.assertLess(time.monotonic(), deadline)
        cache = m.load_config().get("news_cache", {}).get("announcements", {})
        return a._featured, cache.get("item"), bool(forum_calls)

    def malformed(self):
        return self.news.ForumError("news.json parse", self.news.NEWS_FEED_URL,
                                      "bad", short="the news feed was malformed")

    def test_feed_first(self):
        shown, cached, forum = self.run_load(self.FEED, self.FORUM, self.CACHED)
        self.assertEqual(shown["id"], "feed-1")
        self.assertEqual(cached["id"], "feed-1")
        self.assertFalse(forum)
        self.assertIsNone(shown["author"])          # not invented

    def test_failed_or_malformed_feed_keeps_the_last_good(self):
        import socket
        for err in (self.malformed(), socket.timeout("timed out"),
                    self.news.ForumBlockedError("news.json", "u", "challenge")):
            with self.subTest(err=type(err).__name__):
                shown, cached, forum = self.run_load(err, self.FORUM, self.CACHED)
                self.assertEqual(shown["id"], "old")
                self.assertEqual(cached["id"], "old")
                self.assertFalse(forum)             # cache before the forum

    def test_empty_feed_keeps_the_last_good(self):
        shown, cached, forum = self.run_load(None, self.FORUM, self.CACHED)
        self.assertEqual(shown["id"], "old")
        self.assertEqual(cached["id"], "old")
        self.assertFalse(forum)

    def test_forum_only_with_nothing_cached(self):
        shown, cached, forum = self.run_load(self.malformed(), self.FORUM, None)
        self.assertTrue(forum)
        self.assertEqual(shown["id"], "2595")
        self.assertEqual(cached["id"], "2595")

    def test_everything_failing_shows_no_content(self):
        err = self.news.ForumBlockedError("forum 2 listing", "u", "challenge")
        shown, cached, forum = self.run_load(self.malformed(), err, None)
        self.assertTrue(forum)
        self.assertIsNone(shown)
        self.assertIsNone(cached)


if __name__ == "__main__":
    unittest.main()
