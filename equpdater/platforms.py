"""What differs between Windows and Linux, in one place.

EqUpdater is one program on both. Everything it does -- the client sync,
mods, addons, texture packs, tweaks, the WoW.exe patch -- is the same code;
this module holds only what genuinely depends on the operating system:

- starting other programs (no console window on Windows; on Linux, without
  the frozen app's own library path leaking into them);
- opening a folder or a web page;
- the directory link the torrent sync writes through;
- where aria2c comes from;
- whether the game is running (Windows locks a running WoW.exe; Linux runs
  it under Wine and locks nothing, so the processes are asked instead);
- how PLAY starts a Windows game client (directly on Windows; through Wine,
  UMU or the player's own command on Linux);
- how EqUpdater restarts itself.

The game client is the Windows WoW.exe on every platform and is read,
patched and launched as that file; nothing here changes it.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")

#: The client's executables, as the game names them on every platform.
GAME_EXE = "WoW.exe"
LOADER_EXE = "VanillaFixes.exe"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# ──────────────────────────────────────────────────────────────────────────────
#  Starting other programs
# ──────────────────────────────────────────────────────────────────────────────

def no_window_flags() -> int:
    """creationflags for a helper that must not flash a console (Windows)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if WINDOWS else 0


def own_env(var: str, value: str) -> None:
    """Set an environment variable for EqUpdater itself, remembering the
    player's own value so programs EqUpdater starts get theirs back (see
    child_env). The ``<VAR>_ORIG`` convention is PyInstaller's."""
    if var + "_ORIG" not in os.environ and var in os.environ:
        os.environ[var + "_ORIG"] = os.environ[var]
    os.environ[var] = value


def child_env(base: dict | None = None) -> dict:
    """The environment for a program that is not part of EqUpdater: the
    game, its runner, a file manager, a browser.

    A frozen Linux build runs with its bundled libraries first on
    LD_LIBRARY_PATH (PyInstaller does that) and may point FONTCONFIG_FILE at
    its own fonts (ui.py). Wine or a browser started with those would load
    EqUpdater's copies of libraries instead of the system's and can crash.
    So each such variable gets its original value back, or goes."""
    env = dict(os.environ if base is None else base)
    if WINDOWS:
        return env
    bundle = getattr(sys, "_MEIPASS", None)
    for var in ("LD_LIBRARY_PATH", "FONTCONFIG_FILE"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            if orig:
                env[var] = orig
            else:
                env.pop(var, None)
        elif var == "LD_LIBRARY_PATH" and bundle and var in env:
            kept = [p for p in env[var].split(os.pathsep)
                    if p and not os.path.abspath(p).startswith(os.path.abspath(bundle))]
            if kept:
                env[var] = os.pathsep.join(kept)
            else:
                env.pop(var, None)
        elif var == "FONTCONFIG_FILE" and env.get("EQUPDATER_FONTCONFIG") == env.get(var):
            env.pop(var, None)
    env.pop("EQUPDATER_FONTCONFIG", None)
    return env


def spawn_detached(argv: list, cwd: str | None = None,
                   env: dict | None = None) -> subprocess.Popen:
    """Start a program that outlives EqUpdater (the game).

    Windows: a detached process outside EqUpdater's job, so closing the
    updater -- or the job a launcher put it in -- does not close the game;
    retried without the breakaway when the job does not allow it.
    Linux: its own session, with the original environment (child_env)."""
    if WINDOWS:
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
        try:
            return subprocess.Popen(argv, cwd=cwd, env=env,
                                    creationflags=flags, close_fds=True)
        except OSError:
            flags &= ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
            return subprocess.Popen(argv, cwd=cwd, env=env,
                                    creationflags=flags, close_fds=True)
    return subprocess.Popen(argv, cwd=cwd, env=child_env(env),
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True, close_fds=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Folders, links and web pages
# ──────────────────────────────────────────────────────────────────────────────

def open_folder(path: str) -> None:
    """Show ``path`` in the file manager. Raises OSError when it cannot.

    Windows: explorer.exe by name, not os.startfile -- ShellExecute
    resolves an extensionless path against PATHEXT/.lnk, so a desktop
    shortcut named like the folder ("OctoWoW.lnk") would be *run*.
    Linux: xdg-open, the desktop's own choice."""
    if WINDOWS:
        subprocess.Popen(["explorer.exe", path])
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if not shutil.which(opener):
        raise OSError(f"{opener} was not found")
    spawn_detached([opener, path])


def open_url(url: str) -> None:
    """Open a web page in the player's browser."""
    if WINDOWS or sys.platform == "darwin":
        import webbrowser
        webbrowser.open(url)
        return
    if shutil.which("xdg-open"):
        spawn_detached(["xdg-open", url])
        return
    import webbrowser
    webbrowser.open(url)


def link_dir(link: str, target: str) -> None:
    """Make ``link`` a directory link to ``target``. Windows: an NTFS
    junction (no administrator rights needed, unlike a symlink). Elsewhere:
    a symlink. Raises RuntimeError when the link did not appear."""
    if WINDOWS:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True,
                           creationflags=no_window_flags())
        detail = (r.stderr or r.stdout or "").strip()
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
            detail = ""
        except OSError as e:
            detail = str(e)
    if not os.path.isdir(link):
        raise RuntimeError("could not create download link: " + detail)


# ──────────────────────────────────────────────────────────────────────────────
#  aria2c
# ──────────────────────────────────────────────────────────────────────────────

def aria2c_name() -> str:
    """The aria2c executable's file name on this platform.

    A function, not a constant: every platform decision in this module reads
    WINDOWS/LINUX when it is made, so nothing here can disagree with them --
    a name fixed at import time would (the tests switch platforms, and a
    constant computed on Linux stayed "aria2c" inside a Windows branch)."""
    return "aria2c.exe" if WINDOWS else "aria2c"


def bundled_aria2c() -> list:
    """Where a packaged build carries its own aria2c: beside the executable
    (the AppImage puts it in usr/bin next to EqUpdater), in the AppImage's
    usr/bin, or inside the PyInstaller bundle."""
    name = aria2c_name()
    places = []
    if frozen():
        places.append(os.path.join(os.path.dirname(sys.executable), name))
    appdir = os.environ.get("APPDIR")
    if appdir:
        places.append(os.path.join(appdir, "usr", "bin", name))
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        places.append(os.path.join(bundle, name))
    return places


def find_aria2c(app_data_dir: str) -> str | None:
    """The aria2c to run, or None when the caller must provide one.

    Windows: the pinned, checksum-verified build EqUpdater downloads into its
    data folder (app.ensure_aria2c fetches it when this says None).
    Linux: a native aria2c -- the AppImage's own first, then the system's.
    A Windows aria2c.exe is never run under Wine."""
    if WINDOWS:
        path = os.path.join(app_data_dir, aria2c_name())
        return path if os.path.isfile(path) else None
    for path in bundled_aria2c():
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which(aria2c_name())


# ──────────────────────────────────────────────────────────────────────────────
#  Is the game running?
# ──────────────────────────────────────────────────────────────────────────────

_GAME_NAMES = (GAME_EXE.lower(), LOADER_EXE.lower())


def _exe_locked(path: str) -> bool:
    """Windows: a running executable cannot be opened for writing. "r+b"
    opens without truncating and nothing is written."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _windows_path_to_unix(arg: str) -> str | None:
    """A path as Wine shows it in a process's command line, as a Linux path:
    Z:\\home\\me\\Games\\OctoWoW\\WoW.exe (Wine's Z: is /) or an already-Unix
    path. Other drive letters live inside a Wine prefix; None for those."""
    if len(arg) >= 3 and arg[1] == ":" and arg[2] in "\\/":
        if arg[0].lower() == "z":
            return "/" + arg[3:].replace("\\", "/")
        return None
    if arg.startswith("/"):
        return arg
    return None


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except OSError:
        return False


def _processes(proc_root: str = "/proc"):
    """(pid, command-line arguments, working directory) of every process
    this user can see."""
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return
    for pid in pids:
        try:
            with open(os.path.join(proc_root, pid, "cmdline"), "rb") as f:
                raw = f.read()
        except OSError:
            continue
        args = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        try:
            cwd = os.readlink(os.path.join(proc_root, pid, "cwd"))
        except OSError:
            cwd = None
        yield pid, args, cwd


def game_process_running(client_dir: str, proc_root: str = "/proc") -> bool:
    """Linux: whether this client's WoW.exe (or VanillaFixes.exe) is running
    under Wine, Proton or anything else.

    A process counts when one of its arguments names WoW.exe or
    VanillaFixes.exe and it is *this* client's: the path (Wine shows
    Z:\\...\\WoW.exe or a Unix path) or the process's working directory is
    the client folder. wine, wineserver and the runner's other processes
    name no game executable and never count. When a game process cannot be
    placed in any folder -- a C:\\ path inside a prefix, no readable working
    directory -- it counts: refusing to patch a file that might be running
    is the safe mistake."""
    for _pid, args, cwd in _processes(proc_root):
        for arg in args:
            name = arg.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if name not in _GAME_NAMES:
                continue
            unix = _windows_path_to_unix(arg)
            if unix is not None:
                if _same_dir(os.path.dirname(unix), client_dir):
                    return True
                if "/" in arg or "\\" in arg:
                    break          # a WoW.exe in some other folder
            if cwd is None or _same_dir(cwd, client_dir):
                return True
            break
    return False


def client_in_use(client_dir: str) -> bool:
    """Whether the client's WoW.exe must not be written now.

    Windows asks the file: a running image cannot be opened for writing, so
    the answer is exact for the very file about to be patched (and covers a
    read-only WoW.exe too). Linux would happily let EqUpdater overwrite a
    running game, so it asks the processes instead."""
    exe = os.path.join(client_dir, GAME_EXE)
    if WINDOWS:
        return _exe_locked(exe)
    if os.path.exists(exe) and not os.access(exe, os.W_OK):
        return True                      # read-only: the same refusal
    if LINUX:
        return game_process_running(client_dir)
    return False


# ──────────────────────────────────────────────────────────────────────────────
#  PLAY
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class LaunchPlan:
    """How PLAY starts the game: the command line, its environment and
    folder, and which runner was chosen ("" when none could be)."""
    argv: list = field(default_factory=list)
    cwd: str = ""
    env: dict | None = None
    runner: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.argv)


def detect_runner(which=shutil.which) -> tuple:
    """(name, path) of the runner PLAY uses on Linux when the player has not
    set a launch command, or ("", "") when there is none.

    Wine first: it is the system's configured Wine, starts at once, and is
    what most people already run the game with. Then UMU (umu-run), which
    runs Proton outside Steam -- after Wine, because with no PROTONPATH set
    its first launch downloads a whole Proton build without saying so.
    Steam installs, Lutris and Faugus each keep their own configuration,
    which the player's launch command can name."""
    for name in ("wine", "umu-run"):
        path = which(name)
        if path:
            return name, path
    return "", ""


def launch_plan(client_dir: str, exe: str, settings: dict | None = None,
                which=shutil.which) -> LaunchPlan:
    """How to start ``exe`` (the client's WoW.exe or VanillaFixes.exe).

    Windows: the executable itself. Linux, in order:
      1. the player's launch command (Settings -> Game launcher). "{exe}" in
         it is replaced by the executable's path and "{dir}" by the client
         folder; with neither, the path is added at the end;
      2. Wine, then UMU, from PATH (detect_runner);
      3. nothing -- the plan is not ok, and PLAY says what is missing.
    A Wine prefix from Settings is passed as WINEPREFIX to all of them."""
    settings = settings or {}
    if WINDOWS:
        return LaunchPlan([exe], client_dir, None, "windows")

    env = child_env()
    prefix = (settings.get("wine_prefix") or "").strip()
    if prefix:
        env["WINEPREFIX"] = os.path.expanduser(prefix)

    command = (settings.get("launch_command") or "").strip()
    if command:
        try:
            parts = shlex.split(command)
        except ValueError:
            return LaunchPlan(runner="")
        if not parts:
            return LaunchPlan(runner="")
        uses_exe = any("{exe}" in p for p in parts)
        uses_dir = any("{dir}" in p for p in parts)
        argv = [os.path.expanduser(p.replace("{exe}", exe).replace("{dir}", client_dir))
                for p in parts]
        if not uses_exe and not uses_dir:
            argv.append(exe)
        return LaunchPlan(argv, client_dir, env, "custom")

    name, path = detect_runner(which)
    if not name:
        return LaunchPlan(runner="")
    if name == "umu-run":
        env.setdefault("GAMEID", "umu-default")
    return LaunchPlan([path, exe], client_dir, env, name)


# ──────────────────────────────────────────────────────────────────────────────
#  Restarting EqUpdater
# ──────────────────────────────────────────────────────────────────────────────

def self_command(source_entry: str) -> list:
    """The command that starts this EqUpdater again.

    An AppImage is the AppImage file ($APPIMAGE): the executable inside it
    lives on a mount that disappears when this process exits."""
    appimage = os.environ.get("APPIMAGE")
    if appimage and os.path.isfile(appimage):
        return [appimage]
    if frozen():
        return [sys.executable]
    return [sys.executable, source_entry]
