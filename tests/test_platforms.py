"""equpdater.platforms: what differs between Windows and Linux.

Each platform's behaviour is tested on any platform by switching the module's
WINDOWS/LINUX flags and mocking what it would call -- subprocess, PATH,
/proc -- so CI on Windows checks the Linux code and the other way round.
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def modules():
    """The app's own module objects (other test files reload the package,
    and a flag patched on a stale copy changes nothing)."""
    from equpdater import app
    return app, app.platforms


class On:
    """Pretend to be on one platform for the duration of a ``with``."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        _app, platforms = modules()
        self.patches = [mock.patch.object(platforms, "WINDOWS", self.name == "windows"),
                        mock.patch.object(platforms, "LINUX", self.name == "linux")]
        for p in self.patches:
            p.start()
        return platforms

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class TestOpening(unittest.TestCase):
    def test_windows_opens_folders_with_explorer(self):
        with On("windows") as platforms, \
                mock.patch.object(platforms.subprocess, "Popen") as popen:
            platforms.open_folder(r"D:\Games\OctoWoW")
        self.assertEqual(popen.call_args[0][0], ["explorer.exe", r"D:\Games\OctoWoW"])

    def test_linux_opens_folders_with_xdg_open(self):
        with On("linux") as platforms, \
                mock.patch.object(platforms.shutil, "which", lambda n: "/usr/bin/" + n), \
                mock.patch.object(platforms, "spawn_detached") as spawn:
            platforms.open_folder("/home/me/Games/OctoWoW")
        self.assertEqual(spawn.call_args[0][0], ["xdg-open", "/home/me/Games/OctoWoW"])

    def test_linux_without_xdg_open_says_so(self):
        with On("linux") as platforms, \
                mock.patch.object(platforms.shutil, "which", lambda n: None), \
                self.assertRaises(OSError):
            platforms.open_folder("/home/me")

    def test_linux_opens_web_pages_with_xdg_open(self):
        with On("linux") as platforms, \
                mock.patch.object(platforms.shutil, "which", lambda n: "/usr/bin/" + n), \
                mock.patch.object(platforms, "spawn_detached") as spawn:
            platforms.open_url("https://github.com/eqomdx/EqUpdater")
        self.assertEqual(spawn.call_args[0][0][0], "xdg-open")


class TestChildEnvironment(unittest.TestCase):
    """Programs EqUpdater starts get the player's environment, not the
    frozen app's library path or fontconfig file."""

    def test_original_values_come_back(self):
        with On("linux") as platforms:
            env = platforms.child_env({"LD_LIBRARY_PATH": "/tmp/_MEIxyz",
                                       "LD_LIBRARY_PATH_ORIG": "/opt/lib",
                                       "FONTCONFIG_FILE": "/mine/fonts.conf",
                                       "FONTCONFIG_FILE_ORIG": "/etc/custom.conf",
                                       "HOME": "/home/me"})
        self.assertEqual(env["LD_LIBRARY_PATH"], "/opt/lib")
        self.assertEqual(env["FONTCONFIG_FILE"], "/etc/custom.conf")
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", env)
        self.assertEqual(env["HOME"], "/home/me")

    def test_the_bundles_own_paths_are_dropped(self):
        bundle = os.path.abspath(os.path.join(tempfile.gettempdir(), "_MEIbundle"))
        with On("linux") as platforms, \
                mock.patch.object(sys, "_MEIPASS", bundle, create=True):
            env = platforms.child_env({"LD_LIBRARY_PATH": bundle,
                                       "EQUPDATER_FONTCONFIG": "/x/fonts.conf",
                                       "FONTCONFIG_FILE": "/x/fonts.conf"})
        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertNotIn("FONTCONFIG_FILE", env)
        self.assertNotIn("EQUPDATER_FONTCONFIG", env)

    def test_windows_is_untouched(self):
        with On("windows") as platforms:
            self.assertEqual(platforms.child_env({"PATH": "x"}), {"PATH": "x"})


class TestLaunching(unittest.TestCase):
    EXE = "/home/me/Games/OctoWoW/WoW.exe"
    DIR = "/home/me/Games/OctoWoW"

    def plan(self, settings=None, found=()):
        _app, platforms = modules()
        which = lambda name: f"/usr/bin/{name}" if name in found else None  # noqa: E731
        with On("linux"):
            return platforms.launch_plan(self.DIR, self.EXE, settings, which=which)

    def test_windows_runs_the_exe(self):
        with On("windows") as platforms:
            plan = platforms.launch_plan(r"D:\OctoWoW", r"D:\OctoWoW\WoW.exe")
        self.assertEqual(plan.argv, [r"D:\OctoWoW\WoW.exe"])
        self.assertEqual(plan.cwd, r"D:\OctoWoW")
        self.assertTrue(plan.ok)

    def test_linux_prefers_wine(self):
        plan = self.plan(found=("wine", "umu-run"))
        self.assertEqual(plan.argv, ["/usr/bin/wine", self.EXE])
        self.assertEqual(plan.runner, "wine")
        self.assertEqual(plan.cwd, self.DIR)

    def test_linux_falls_back_to_umu(self):
        plan = self.plan(found=("umu-run",))
        self.assertEqual(plan.argv, ["/usr/bin/umu-run", self.EXE])
        self.assertEqual(plan.env["GAMEID"], "umu-default")

    def test_linux_with_nothing_says_so(self):
        plan = self.plan(found=())
        self.assertFalse(plan.ok)

    def test_a_custom_command_comes_first(self):
        plan = self.plan({"launch_command": "gamemoderun wine {exe} -console"},
                         found=("wine",))
        self.assertEqual(plan.argv, ["gamemoderun", "wine", self.EXE, "-console"])
        self.assertEqual(plan.runner, "custom")

    def test_a_custom_command_without_exe_gets_it_appended(self):
        plan = self.plan({"launch_command": "/opt/proton/proton run"})
        self.assertEqual(plan.argv, ["/opt/proton/proton", "run", self.EXE])

    def test_a_custom_command_naming_the_folder_is_taken_as_written(self):
        plan = self.plan({"launch_command": "lutris lutris:rungame/octowow --dir {dir}"})
        self.assertEqual(plan.argv, ["lutris", "lutris:rungame/octowow", "--dir", self.DIR])

    def test_a_broken_command_is_not_run(self):
        self.assertFalse(self.plan({"launch_command": 'wine "unclosed'}).ok)

    def test_the_wine_prefix_is_passed(self):
        plan = self.plan({"wine_prefix": "~/Games/octowow-prefix"}, found=("wine",))
        self.assertEqual(plan.env["WINEPREFIX"],
                         os.path.expanduser("~/Games/octowow-prefix"))

    def test_windows_spawns_detached_from_the_job(self):
        with On("windows") as platforms, \
                mock.patch.object(platforms.subprocess, "Popen") as popen:
            platforms.spawn_detached([r"D:\OctoWoW\WoW.exe"], cwd=r"D:\OctoWoW")
        flags = popen.call_args.kwargs["creationflags"]
        self.assertEqual(popen.call_args[0][0], [r"D:\OctoWoW\WoW.exe"])
        if os.name == "nt":
            import subprocess
            self.assertTrue(flags & subprocess.DETACHED_PROCESS)

    def test_linux_spawns_in_its_own_session(self):
        with On("linux") as platforms, \
                mock.patch.object(platforms.subprocess, "Popen") as popen:
            platforms.spawn_detached(["/usr/bin/wine", self.EXE], cwd=self.DIR)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["cwd"], self.DIR)


class TestGameEnvironment(unittest.TestCase):
    """Settings -> Game launcher -> Environment variables: one NAME=value per
    line, given to the game only."""

    EXE = TestLaunching.EXE
    DIR = TestLaunching.DIR

    def parse(self, text):
        _app, platforms = modules()
        return platforms.parse_env_lines(text)

    def plan(self, settings, found=("wine",), on="linux"):
        _app, platforms = modules()
        which = lambda name: f"/usr/bin/{name}" if name in found else None  # noqa: E731
        with On(on):
            return platforms.launch_plan(self.DIR, self.EXE, settings, which=which)

    def test_lines_become_variables(self):
        text = ("DXVK_HUD=fps\n"
                "\n"
                "   \n"
                "  PROTON_LOG = 1\n"
                "WINEDLLOVERRIDES=d3d9=n,b;dxgi=n\n"
                "_UNDERSCORED=a value with  spaces \n"
                "EMPTY=\r\n"
                "DXVK_HUD=fps,frametimes\n")
        self.assertEqual(self.parse(text), ({
            "DXVK_HUD": "fps,frametimes",            # the later line wins
            "PROTON_LOG": " 1",                      # name trimmed, value as typed
            "WINEDLLOVERRIDES": "d3d9=n,b;dxgi=n",   # '=' inside the value
            "_UNDERSCORED": "a value with  spaces ",
            "EMPTY": "",
        }, []))

    def test_empty_configuration(self):
        for text in (None, "", "\n\n", "   \n\t\n"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), ({}, []))

    def test_every_bad_line_is_reported_with_its_number(self):
        text = ("GOOD=1\n"
                "no equals sign\n"
                "1BAD=x\n"
                "BAD-NAME=x\n"
                "=nameless\n"
                "  =x\n"
                "SP ACE=x\n"
                "export FOO=x\n"
                "$(rm -rf ~)=x\n"
                "NUL=a\0b\n"
                "ÜBER=x\n")
        variables, problems = self.parse(text)
        self.assertEqual(variables, {"GOOD": "1"})
        self.assertEqual(problems, [
            (2, "no_equals"), (3, "bad_name"), (4, "bad_name"),
            (5, "bad_name"), (6, "bad_name"), (7, "bad_name"),
            (8, "bad_name"), (9, "bad_name"), (10, "nul"), (11, "bad_name")])

    def test_values_are_never_expanded(self):
        variables, _ = self.parse("A=$HOME\nB=`id`\nC=$(id)\nD=~/x\nE=%PATH%\n")
        self.assertEqual(variables, {"A": "$HOME", "B": "`id`", "C": "$(id)",
                                     "D": "~/x", "E": "%PATH%"})

    def test_they_reach_the_game_on_linux(self):
        for settings in ({"env_vars": "DXVK_HUD=fps\nA=b=c"},
                         {"env_vars": "DXVK_HUD=fps\nA=b=c",
                          "launch_command": "gamemoderun wine {exe}"}):
            with self.subTest(settings=settings):
                plan = self.plan(settings, found=("wine", "umu-run"))
                self.assertTrue(plan.ok)
                self.assertEqual(plan.env["DXVK_HUD"], "fps")
                self.assertEqual(plan.env["A"], "b=c")

    def test_they_reach_the_game_on_windows(self):
        plan = self.plan({"env_vars": "DXVK_HUD=fps"}, on="windows")
        self.assertEqual(plan.argv, [self.EXE])
        self.assertEqual(plan.env["DXVK_HUD"], "fps")
        self.assertEqual(plan.env.get("PATH"), os.environ.get("PATH"))

    def test_merged_into_a_copy_of_the_environment(self):
        """Everything EqUpdater's own environment has is kept, the game gets
        the extra variables, and EqUpdater's environment is not touched."""
        before = dict(os.environ)
        with mock.patch.dict(os.environ, {"EQU_TEST_KEEP": "kept",
                                          "EQU_TEST_OVERRIDE": "old"}):
            plan = self.plan({"env_vars": "EQU_TEST_NEW=1\nEQU_TEST_OVERRIDE=new"})
            self.assertEqual(plan.env["EQU_TEST_KEEP"], "kept")
            self.assertEqual(plan.env["EQU_TEST_NEW"], "1")
            self.assertEqual(plan.env["EQU_TEST_OVERRIDE"], "new")
            self.assertNotIn("EQU_TEST_NEW", os.environ)
            self.assertEqual(os.environ["EQU_TEST_OVERRIDE"], "old")
            self.assertIsNot(plan.env, os.environ)
        self.assertEqual(dict(os.environ), before)

    def test_a_line_here_wins_over_the_defaults(self):
        plan = self.plan({"env_vars": "GAMEID=umu-12345\nWINEPREFIX=/pfx",
                          "wine_prefix": "/other"}, found=("umu-run",))
        self.assertEqual(plan.env["GAMEID"], "umu-12345")
        self.assertEqual(plan.env["WINEPREFIX"], "/pfx")

    def test_empty_leaves_launching_exactly_as_it_was(self):
        for empty in ({}, {"env_vars": ""}, {"env_vars": "\n  \n"}):
            with self.subTest(settings=empty):
                self.assertEqual(self.plan(empty, on="windows"),
                                 self.plan({}, on="windows"))
                self.assertIsNone(self.plan(empty, on="windows").env)
                self.assertEqual(self.plan(empty, found=("umu-run",)),
                                 self.plan({}, found=("umu-run",)))

    def test_a_bad_line_stops_the_launch(self):
        for on in ("linux", "windows"):
            with self.subTest(on=on):
                plan = self.plan({"env_vars": "GOOD=1\nnot a variable"}, on=on)
                self.assertFalse(plan.ok)
                self.assertEqual(plan.argv, [])
                self.assertEqual(plan.env_problems, [(2, "no_equals")])

    def test_spawned_without_a_shell(self):
        plan = self.plan({"env_vars": "X=$(touch /tmp/pwned)",
                          "launch_command": "wine {exe}"})
        _app, platforms = modules()
        with On("linux"), mock.patch.object(platforms.subprocess, "Popen") as popen:
            platforms.spawn_detached(plan.argv, cwd=plan.cwd, env=plan.env)
        kwargs = popen.call_args.kwargs
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(popen.call_args[0][0], ["wine", self.EXE])
        self.assertEqual(kwargs["env"]["X"], "$(touch /tmp/pwned)")

    def test_problems_are_explained_in_every_language(self):
        app, _platforms = modules()
        problems = [(2, "no_equals"), (3, "bad_name"), (4, "nul")]
        english = app.env_problem_text(problems)
        try:
            for lang in ("deDE", "ruRU", "zhCN", "esES", "ptBR"):
                with self.subTest(lang=lang):
                    app.i18n.set_language(lang)
                    text = app.env_problem_text(problems)
                    self.assertNotEqual(text, english)
                    lines = text.split("\n")
                    self.assertEqual(len(lines), 3)
                    for number, line in zip((2, 3, 4), lines):
                        self.assertIn(str(number), line)
        finally:
            app.i18n.set_language("enUS")


class TestAria2(unittest.TestCase):
    def test_the_name_follows_the_platform_flag(self):
        """Decided when asked, not when the module was imported: on a Linux
        machine switched to Windows (and the other way round) the name must
        agree with the branch being taken."""
        with On("windows") as platforms:
            self.assertEqual(platforms.aria2c_name(), "aria2c.exe")
        with On("linux") as platforms:
            self.assertEqual(platforms.aria2c_name(), "aria2c")
        _app, platforms = modules()
        self.assertFalse(hasattr(platforms, "ARIA2C"),
                         "a platform-dependent constant fixed at import time")

    def test_windows_uses_the_pinned_download(self):
        with tempfile.TemporaryDirectory() as data:
            with On("windows") as platforms:
                self.assertIsNone(platforms.find_aria2c(data))
                open(os.path.join(data, "aria2c.exe"), "w").close()
                self.assertEqual(platforms.find_aria2c(data),
                                 os.path.join(data, "aria2c.exe"))

    def test_linux_prefers_the_bundled_one(self):
        with tempfile.TemporaryDirectory() as appdir:
            bundled = os.path.join(appdir, "usr", "bin", "aria2c")
            os.makedirs(os.path.dirname(bundled))
            with open(bundled, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(bundled, 0o755)
            with On("linux") as platforms, \
                    mock.patch.object(platforms.shutil, "which", lambda n: "/usr/bin/aria2c"), \
                    mock.patch.object(platforms.os, "access", lambda p, m: True), \
                    mock.patch.dict(os.environ, {"APPDIR": appdir}):
                self.assertEqual(platforms.find_aria2c("/unused"), bundled)

    def test_linux_falls_back_to_the_system_one(self):
        with On("linux") as platforms, \
                mock.patch.object(platforms, "bundled_aria2c", lambda: []), \
                mock.patch.object(platforms.shutil, "which",
                                  lambda n: "/usr/bin/aria2c" if n == "aria2c" else None):
            self.assertEqual(platforms.find_aria2c("/unused"), "/usr/bin/aria2c")

    def test_linux_without_aria2c_explains(self):
        app, platforms = modules()
        with On("linux"), \
                mock.patch.object(platforms, "find_aria2c", lambda d: None):
            with self.assertRaises(RuntimeError) as ctx:
                app.ensure_aria2c(lambda *a, **k: None)
        self.assertIn("aria2", str(ctx.exception))


class TestRunningGame(unittest.TestCase):
    """Linux: the processes are asked. Wine and its server are not the game;
    a WoW.exe in another folder is not this client's."""

    CLIENT = "/home/me/Games/OctoWoW"

    def running(self, *procs):
        _app, platforms = modules()
        with mock.patch.object(platforms, "_processes", lambda root="/proc": iter(procs)):
            return platforms.game_process_running(self.CLIENT)

    def test_wine_shows_the_game_as_a_z_drive_path(self):
        self.assertTrue(self.running(
            ("10", ["Z:\\home\\me\\Games\\OctoWoW\\WoW.exe"], None)))

    def test_a_unix_path(self):
        self.assertTrue(self.running(
            ("10", ["/usr/bin/wine", "/home/me/Games/OctoWoW/WoW.exe"], "/home/me")))

    def test_the_loader_counts(self):
        self.assertTrue(self.running(
            ("10", ["wine", "VanillaFixes.exe"], self.CLIENT)))

    def test_a_bare_name_in_the_client_folder(self):
        self.assertTrue(self.running(("10", ["WoW.exe"], self.CLIENT)))

    def test_wine_itself_is_not_the_game(self):
        self.assertFalse(self.running(
            ("1", ["/usr/bin/wineserver"], "/"),
            ("2", ["C:\\windows\\system32\\services.exe"], "/"),
            ("3", ["C:\\windows\\system32\\explorer.exe", "/desktop"], "/")))

    def test_another_install_is_not_this_one(self):
        self.assertFalse(self.running(
            ("10", ["/home/me/Other/WoW.exe"], "/home/me/Other"),
            ("11", ["WoW.exe"], "/home/me/Other")))

    def test_a_game_that_cannot_be_placed_counts(self):
        """C:\\ inside some prefix, no readable working folder: refusing to
        patch a file that might be running is the safe mistake."""
        self.assertTrue(self.running(
            ("10", ["C:\\Program Files\\OctoWoW\\WoW.exe"], None)))

    def test_linux_read_only_exe_counts(self):
        with tempfile.TemporaryDirectory() as client:
            open(os.path.join(client, "WoW.exe"), "w").close()
            with On("linux") as platforms, \
                    mock.patch.object(platforms, "game_process_running", lambda d: False), \
                    mock.patch.object(platforms.os, "access", lambda p, m: False):
                self.assertTrue(platforms.client_in_use(client))
            with On("linux") as platforms, \
                    mock.patch.object(platforms, "game_process_running", lambda d: True):
                self.assertTrue(platforms.client_in_use(client))
            with On("linux") as platforms, \
                    mock.patch.object(platforms, "game_process_running", lambda d: False):
                self.assertFalse(platforms.client_in_use(client))


class TestPaths(unittest.TestCase):
    def test_app_data_follows_each_platforms_convention(self):
        from equpdater import branding
        with mock.patch.object(branding.os, "name", "nt"), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\me\AppData\Local"}):
            self.assertEqual(branding.app_data_dir(),
                             os.path.join(r"C:\Users\me\AppData\Local", "EqUpdater"))
        with mock.patch.object(branding.os, "name", "posix"), \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/home/me/.local/share"}):
            self.assertEqual(branding.app_data_dir(),
                             os.path.join("/home/me/.local/share", "EqUpdater"))

    def test_frozen_builds_find_their_bundled_files(self):
        from equpdater import branding, ui
        with tempfile.TemporaryDirectory() as bundle:
            os.makedirs(os.path.join(bundle, "fonts"))
            open(os.path.join(bundle, "fonts", "OpenDyslexic-Regular.otf"), "w").close()
            open(os.path.join(bundle, "icon.png"), "w").close()
            with mock.patch.object(sys, "_MEIPASS", bundle, create=True):
                self.assertIn(os.path.join(bundle, "icon.png"),
                              branding.icon_candidates())
                self.assertIn(os.path.normpath(os.path.join(bundle, "fonts",
                                                            "OpenDyslexic-Regular.otf")),
                              ui._bundled_font_paths())

    def test_an_appimage_restarts_as_the_appimage(self):
        _app, platforms = modules()
        with tempfile.NamedTemporaryFile(suffix=".AppImage", delete=False) as f:
            appimage = f.name
        try:
            with mock.patch.dict(os.environ, {"APPIMAGE": appimage}):
                self.assertEqual(platforms.self_command("EqUpdater.py"), [appimage])
        finally:
            os.remove(appimage)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APPIMAGE", None)
            with mock.patch.object(sys, "frozen", True, create=True):
                self.assertEqual(platforms.self_command("x"), [sys.executable])

    def test_linux_links_with_a_symlink(self):
        with On("linux") as platforms, \
                mock.patch.object(platforms.os, "symlink") as symlink, \
                mock.patch.object(platforms.os.path, "isdir", lambda p: True):
            platforms.link_dir("/stage/client", "/home/me/Games/OctoWoW")
        symlink.assert_called_once_with("/home/me/Games/OctoWoW", "/stage/client",
                                        target_is_directory=True)


class TestTls(unittest.TestCase):
    """Certificates are always verified; the packaged builds must carry the
    CA bundle and find it."""

    def test_the_context_verifies(self):
        import ssl
        app, _platforms = modules()
        ctx, _loaded = app.make_ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertTrue(app.CA_SOURCES, "no CA bundle loaded at all")

    def test_a_frozen_build_finds_its_own_bundle(self):
        """Even when certifi's own lookup is unavailable."""
        import certifi
        app, _platforms = modules()
        with tempfile.TemporaryDirectory() as bundle:
            os.makedirs(os.path.join(bundle, "certifi"))
            pem = os.path.join(bundle, "certifi", "cacert.pem")
            shutil.copy(certifi.where(), pem)
            with mock.patch.object(sys, "_MEIPASS", bundle, create=True), \
                    mock.patch.dict(sys.modules, {"certifi": None}):
                self.assertIn(pem, app.ca_bundles())
                with mock.patch.object(app, "ca_bundles", lambda: [pem]):
                    _ctx, loaded = app.make_ssl_context()
            self.assertEqual(loaded, [pem])

    def test_linux_adds_the_distributions_bundle(self):
        app, _platforms = modules()
        with tempfile.NamedTemporaryFile(suffix=".crt", delete=False) as f:
            system = f.name
        try:
            with On("linux"), \
                    mock.patch.object(app, "SYSTEM_CA_BUNDLES", (system,)):
                self.assertIn(system, app.ca_bundles())
            with On("windows"), \
                    mock.patch.object(app, "SYSTEM_CA_BUNDLES", (system,)):
                self.assertNotIn(system, app.ca_bundles())
        finally:
            os.remove(system)


class TestFonts(unittest.TestCase):
    def test_fontconfig_file_includes_the_system_and_the_bundle(self):
        from equpdater import ui
        text = ui.fontconfig_file(["/tmp/b&b/fonts"], "/etc/fonts/fonts.conf",
                                  "/home/me/.cache/x")
        self.assertIn('<include ignore_missing="yes">/etc/fonts/fonts.conf</include>', text)
        self.assertIn("<dir>/tmp/b&amp;b/fonts</dir>", text)

    def test_arial_has_linux_stand_ins(self):
        from equpdater import ui
        self.assertIn("Liberation Sans", ui.ARIAL_FAMILIES)
        self.assertEqual(ui.ARIAL_FAMILIES[0], "Arial")


class TestInstaller(unittest.TestCase):
    """The Windows release installer: the packed build is unpacked safely
    and installed through deploy."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="equ-setup-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, entries):
        path = os.path.join(self.tmp, "payload.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return path

    def test_installs_the_packed_build(self):
        from equpdater import installer
        install_dir = os.path.join(self.tmp, "Programs", "EqUpdater")
        payload = self.payload({"EqUpdater.exe": "exe", "_internal/x.txt": "x"})
        exe, changed, created = installer.install(payload, install_dir, folders=[])
        self.assertEqual(exe, os.path.join(install_dir, "EqUpdater.exe"))
        self.assertTrue(os.path.isfile(os.path.join(install_dir, "_internal", "x.txt")))
        self.assertFalse(os.path.exists(install_dir + ".payload"))
        self.assertEqual((changed, created), ([], []))

    def test_refuses_paths_outside_the_folder(self):
        from equpdater import deploy, installer
        payload = self.payload({"EqUpdater.exe": "exe", "../../evil.txt": "x"})
        with self.assertRaises(deploy.DeployError):
            installer.unpack(payload, os.path.join(self.tmp, "stage"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows shortcuts")
    def test_first_install_adds_start_menu_and_asked_for_desktop(self):
        from equpdater import deploy, installer
        desktop = os.path.join(self.tmp, "Desktop")
        start = os.path.join(self.tmp, "Start")
        os.makedirs(desktop)
        os.makedirs(start)
        install_dir = os.path.join(self.tmp, "Programs", "EqUpdater")
        payload = self.payload({"EqUpdater.exe": "exe"})
        exe, _changed, created = installer.install(
            payload, install_dir, want_desktop=lambda: False, folders=[desktop, start])
        self.assertEqual(created, [os.path.join(start, "EqUpdater.lnk")])
        self.assertTrue(deploy._same_path(
            deploy.read_shortcut(os.path.join(start, "EqUpdater.lnk"))[0], exe))
        _exe, _changed, created = installer.install(
            payload, install_dir, want_desktop=lambda: True, folders=[desktop, start])
        self.assertEqual(created, [os.path.join(desktop, "EqUpdater.lnk")])


class TestSelfTest(unittest.TestCase):
    def test_source_tree_passes(self):
        """The check every release artifact runs, run on the source."""
        spec_path = os.path.join(ROOT, "EqUpdater.py")
        import importlib.util
        spec = importlib.util.spec_from_file_location("eq_entry", spec_path)
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        out = os.path.join(tempfile.mkdtemp(prefix="equ-st-"), "st.json")
        app, platforms = modules()
        with mock.patch.object(platforms, "find_aria2c", lambda d: sys.executable):
            code = entry.self_test(out, network=False)
        import json
        with open(out, encoding="utf-8") as f:
            report = json.load(f)
        self.assertEqual(code, 0, report["problems"])
        self.assertEqual(report["version"], app.branding.APP_VERSION)
        self.assertTrue(report["tls_verifies"])
        shutil.rmtree(os.path.dirname(out), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
