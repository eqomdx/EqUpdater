"""Put a built EqUpdater where it always lives, and point shortcuts at it.

EqUpdater used to run from wherever its download was unpacked, so every
version lived in its own folder and the desktop shortcut kept pointing at
whichever one first created it: 2.0.5 installed, 2.0.4 still launched. Now
the application has one permanent home,

    %LOCALAPPDATA%\\Programs\\EqUpdater\\EqUpdater.exe

and an update replaces what is there. The player's state -- settings,
managed addons and mods, backups, logs -- is in %LOCALAPPDATA%\\EqUpdater and
is never touched here.

The replacement is staged so a failure cannot leave the player without a
working copy:

    1. copy the new build to  EqUpdater.new
    2. rename EqUpdater     -> EqUpdater.old
    3. rename EqUpdater.new -> EqUpdater        (on failure: .old goes back)
    4. delete EqUpdater.old

A run interrupted between steps is repaired by the next one, so running the
installer again is always safe.

Then every EqUpdater shortcut -- desktop, Start menu, pinned to the taskbar
-- that points at some other copy (a version folder, a source checkout's
dist\\) is rewritten to the permanent one. Old download folders are left
alone: they are the player's files, and the installer says they can go.

    python install/deploy.py --build dist\\EqUpdater [--yes | --no-shortcut]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

APP = "EqUpdater"
EXE = APP + ".exe"


def default_install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP)


class DeployError(RuntimeError):
    """The new version could not be put in place. The old one still works."""


# ──────────────────────────────────────────────────────────────────────────────
#  The application folder
# ──────────────────────────────────────────────────────────────────────────────

def _exe_in_use(folder: str) -> bool:
    """Whether EqUpdater.exe in ``folder`` is running. Windows will not let a
    running executable be opened for writing."""
    exe = os.path.join(folder, EXE)
    if not os.path.isfile(exe):
        return False
    try:
        with open(exe, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _remove(path: str) -> bool:
    try:
        shutil.rmtree(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def carry_over(old: str, install_dir: str) -> bool:
    """Move into the new installation everything in the old one that is not
    part of EqUpdater itself, and say whether all of it moved.

    The app folder is the app's, but a player's files can still end up in
    it -- in 2.0.6 and earlier the first-run default game folder was
    <app folder>\\OctoWoW. Deleting the old folder must never delete those:
    an update that wipes the game client is the worst thing an updater can
    do. Only what the new build itself has (EqUpdater.exe, _internal) is
    replaced."""
    ok = True
    for name in os.listdir(old):
        if os.path.exists(os.path.join(install_dir, name)):
            continue
        try:
            shutil.move(os.path.join(old, name), os.path.join(install_dir, name))
        except OSError:
            ok = False
    return ok


def _retire(old: str, install_dir: str) -> None:
    """Delete the replaced copy once the player's files are out of it. If
    any could not be moved, keep it: the next run tries again."""
    if carry_over(old, install_dir):
        _remove(old)


def repair(install_dir: str) -> None:
    """Finish or undo a replacement an earlier run did not complete."""
    new, old = install_dir + ".new", install_dir + ".old"
    if not os.path.isdir(install_dir) and os.path.isdir(old):
        os.rename(old, install_dir)          # it stopped between steps 2 and 3
    if os.path.isdir(old):
        _retire(old, install_dir)
    if os.path.isdir(new):
        _remove(new)


def deploy(build_dir: str, install_dir: str | None = None,
           rename=os.rename) -> str:
    """Install the folder build in ``build_dir`` as the application and
    return the path of its EqUpdater.exe. Raises DeployError, leaving the
    previous installation exactly as it was, when that cannot be done.

    ``rename`` is injectable so the tests can make a step fail."""
    install_dir = os.path.abspath(install_dir or default_install_dir())
    build_dir = os.path.abspath(build_dir)
    if not os.path.isfile(os.path.join(build_dir, EXE)):
        raise DeployError(f"{build_dir} has no {EXE}: the build is incomplete.")
    if _same_path(build_dir, install_dir):
        return os.path.join(install_dir, EXE)

    os.makedirs(os.path.dirname(install_dir), exist_ok=True)
    repair(install_dir)
    if _exe_in_use(install_dir):
        raise DeployError(f"{APP} is running. Close it and run the installer "
                          "again; nothing was changed.")

    new, old = install_dir + ".new", install_dir + ".old"
    try:
        shutil.copytree(build_dir, new)
    except OSError as e:
        _remove(new)
        raise DeployError(f"Could not copy the new version to {new}: {e}") from e

    had_old = os.path.isdir(install_dir)
    if had_old:
        try:
            rename(install_dir, old)
        except OSError as e:
            _remove(new)
            raise DeployError(
                f"Could not move the current version aside ({e}). If "
                f"{APP} is open, close it and run the installer again. "
                "Nothing was changed.") from e
    try:
        rename(new, install_dir)
    except OSError as e:
        if had_old:
            os.rename(old, install_dir)      # the old version comes back
        _remove(new)
        raise DeployError(f"Could not put the new version in place ({e}). "
                          "The previous version is unchanged.") from e
    if had_old:
        # The player's own files in the old folder come across first; if
        # something holds the old copy, the next run finishes the job.
        _retire(old, install_dir)
    return os.path.join(install_dir, EXE)


# ──────────────────────────────────────────────────────────────────────────────
#  Shortcuts
# ──────────────────────────────────────────────────────────────────────────────

def shortcut_folders() -> list:
    """Where a player's EqUpdater shortcuts can be: the desktop first, then
    the Start menu and the taskbar's pinned items."""
    user = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    folders = [_known_desktop() or os.path.join(user, "Desktop")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        folders.append(os.path.join(appdata, "Microsoft", "Windows",
                                    "Start Menu", "Programs"))
        folders.append(os.path.join(appdata, "Microsoft", "Internet Explorer",
                                    "Quick Launch", "User Pinned", "TaskBar"))
    return folders


def _known_desktop() -> str | None:
    """The real desktop folder (OneDrive moves it)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        CSIDL_DESKTOPDIRECTORY = 0x10
        if ctypes.windll.shell32.SHGetFolderPathW(
                None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) == 0:
            return buf.value
    except Exception:
        pass
    return None


# Shortcuts are COM objects; PowerShell speaks COM and ships with Windows.
# Paths travel in environment variables, never inside the script text, so no
# path can break the quoting.
_PS_READ = """
$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in ($env:EQU_LNKS -split [char]10)) {
    if (-not $lnk) { continue }
    try {
        $s = $shell.CreateShortcut($lnk)
        Write-Output ($lnk + [char]9 + $s.TargetPath + [char]9 + $s.WorkingDirectory)
    } catch { }
}
"""

_PS_WRITE = """
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:EQU_LNK)
$s.TargetPath = $env:EQU_TARGET
$s.WorkingDirectory = $env:EQU_WORKDIR
$s.IconLocation = $env:EQU_TARGET + ",0"
$s.Description = "EqUpdater - OctoWoW client, mods and addons"
$s.Save()
"""


def _powershell(script: str, **env) -> str:
    full_env = dict(os.environ)
    full_env.update({"EQU_" + k.upper(): v for k, v in env.items()})
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=full_env, capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise OSError(out.stderr.strip() or "PowerShell failed")
    return out.stdout


def read_shortcuts(lnks: list) -> dict:
    """{shortcut: (target, working directory)}, in one PowerShell call -- a
    Start menu holds dozens of them. Unreadable ones are left out."""
    if not lnks:
        return {}
    found = {}
    for line in _powershell(_PS_READ, lnks="\n".join(lnks)).splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            found[parts[0]] = (parts[1].strip(), parts[2].strip())
    return found


def read_shortcut(lnk: str) -> tuple:
    """(target, working directory) of one .lnk file."""
    return read_shortcuts([lnk]).get(lnk, ("", ""))


def write_shortcut(lnk: str, exe: str) -> None:
    """Create or rewrite ``lnk`` to start ``exe`` in its own folder, with its
    icon."""
    _powershell(_PS_WRITE, lnk=lnk, target=exe, workdir=os.path.dirname(exe))


def long_path(path: str) -> str:
    """``path`` with Windows' short 8.3 names (OLIVER~1) written out. The
    shell stores shortcut targets in the long form, so a comparison with a
    short-form path would call a correct shortcut wrong."""
    path = os.path.abspath(path)
    if os.name == "nt" and os.path.exists(path):
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.kernel32.GetLongPathNameW(path, buf, len(buf)):
                return buf.value
        except Exception:
            pass
    return path


def _same_path(a: str, b: str) -> bool:
    return (os.path.normcase(long_path(a)) == os.path.normcase(long_path(b)))


def fix_shortcuts(exe: str, folders=None) -> list:
    """Point every EqUpdater shortcut in ``folders`` at ``exe``. Returns
    [(shortcut, previous target)] for the ones that changed. A shortcut is
    EqUpdater's when it launches a file called EqUpdater.exe; anything else
    is left alone, and so is one already right."""
    lnks = []
    for folder in folders if folders is not None else shortcut_folders():
        if os.path.isdir(folder):
            lnks += [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                     if n.lower().endswith(".lnk")]
    try:
        found = read_shortcuts(lnks)
    except (OSError, subprocess.SubprocessError):
        return []
    changed = []
    for lnk in lnks:
        target, workdir = found.get(lnk, ("", ""))
        if os.path.basename(target).lower() != EXE.lower():
            continue
        if (_same_path(target, exe)
                and _same_path(workdir or "", os.path.dirname(exe))):
            continue
        try:
            write_shortcut(lnk, exe)
        except (OSError, subprocess.SubprocessError):
            continue
        changed.append((lnk, target))
    return changed


def copy_root(exe_folder: str) -> str:
    """The folder a copy was unpacked into: ...\\EqUpdater-2.0.4 for
    ...\\EqUpdater-2.0.4\\dist\\EqUpdater."""
    parts = os.path.normpath(exe_folder).split(os.sep)
    if len(parts) > 2 and [p.lower() for p in parts[-2:]] == ["dist", APP.lower()]:
        return os.sep.join(parts[:-2])
    return os.path.normpath(exe_folder)


def _is_checkout(folder: str) -> bool:
    """A git checkout is somebody's working copy, never "safe to delete"."""
    return os.path.exists(os.path.join(folder, ".git"))


def unused_copies(exe: str, build_dir: str, changed: list) -> list:
    """Folders that held an EqUpdater the player ran before -- the ones the
    shortcuts used to open, and the download being installed from -- and no
    longer need to keep. Never the permanent install, never a git checkout."""
    folders = {copy_root(os.path.dirname(old)) for _lnk, old in changed if old}
    folders.add(copy_root(os.path.abspath(build_dir)))
    home = os.path.dirname(exe)
    return sorted(f for f in folders
                  if os.path.isdir(f) and not _is_checkout(f)
                  and not _same_path(f, home))


# ──────────────────────────────────────────────────────────────────────────────
#  The installer's step
# ──────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build", required=True,
                    help="the PyInstaller folder build (dist\\EqUpdater)")
    ap.add_argument("--install-dir", default=None)
    ap.add_argument("--yes", action="store_true",
                    help="create a desktop shortcut without asking")
    ap.add_argument("--no-shortcut", action="store_true",
                    help="do not offer a new desktop shortcut (existing "
                         "EqUpdater shortcuts are still corrected)")
    args = ap.parse_args(argv)

    try:
        exe = deploy(args.build, args.install_dir)
    except DeployError as e:
        print(f"  {e}")
        return 1
    print(f"  OK installed: {exe}")

    folders = shortcut_folders()
    changed = fix_shortcuts(exe, folders)
    for lnk, old in changed:
        print(f"  OK shortcut {lnk}")
        print(f"     now opens {exe}")
        print(f"     (it opened {old})")

    desktop_lnk = os.path.join(folders[0], APP + ".lnk")
    if not os.path.exists(desktop_lnk) and not args.no_shortcut:
        answer = "y"
        if not args.yes:
            answer = input("  Put a shortcut on the desktop? [Y/n] ").strip() or "y"
        if answer.lower().startswith("y"):
            try:
                write_shortcut(desktop_lnk, exe)
                print(f"  OK shortcut {desktop_lnk}")
            except (OSError, subprocess.SubprocessError) as e:
                print(f"  Could not create the shortcut: {e}")

    print()
    print("  EqUpdater now always runs from:")
    print(f"    {os.path.dirname(exe)}")
    print("  Updates replace it there; your settings stay where they were.")
    unused = unused_copies(exe, args.build, changed)
    if unused:
        print("  Not used to run EqUpdater any more -- delete if you like:")
        for folder in unused:
            print(f"    {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
