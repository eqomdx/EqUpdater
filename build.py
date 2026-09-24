"""Build EqUpdater.

This is the whole build. It is short because there is nothing to patch: the
source in this repository *is* the product.

That is worth stating, because the updater EqUpdater grew out of was a fork
carried as a list of find-and-replace edits applied to somebody else's file at
build time. That made sense while the changes were a dozen fixes that wanted
re-applying to each new upstream release. It stopped making sense the moment
the schema, the safety model and half the UI vocabulary changed: at that point
the patch list is not a fork of the original, it is a rewrite pretending to be
one, and a rewrite should be readable as itself.

Upstream is credited in NOTICE and its licence terms are met in LICENSE.

**A folder build, not a single file, and that is deliberate.** A one-file
PyInstaller executable is a self-extracting archive: every launch unpacks
~30 MB into %TEMP% and runs from there. That is a hidden requirement for
free space on the system drive, which this updater does not otherwise need --
it lives on whichever drive the game does, and the people most likely to run
it are the people whose C: is full of games. When that space runs out the
failure is opaque:

    Failed to extract icon.ico: decompression resulted in return
    code -1!

which names a file that is not the problem, and in a --windowed build there
is no console to say anything better. A folder build never unpacks anything,
starts faster, and cannot fail that way.

Usage:
    python build.py             # dist/EqUpdater/EqUpdater.exe  (recommended)
    python build.py --onefile   # one portable file; needs %TEMP% space to run
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from equpdater import branding  # noqa: E402

NAME = branding.APP_NAME
ICON = os.path.join(HERE, "icon.ico")
ICON_PNG = os.path.join(HERE, "icon.png")
BACKGROUND = os.path.join(HERE, "bubbles.jpg")
FONTS_DIR = os.path.join(HERE, "fonts")
# The frozen build starts at the top-level launcher, not at the package's
# __main__: PyInstaller runs its entry script as `__main__` with no parent
# package, and the relative imports in equpdater/__main__.py raise
# ImportError there before a window ever appears. See EqUpdater.py.
ENTRY = os.path.join(HERE, f"{NAME}.py")

DIST = os.path.join(HERE, "dist")
WORK = os.path.join(HERE, "build")


def run(cmd: list) -> None:
    print("  $ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=HERE)
    if proc.returncode != 0:
        raise SystemExit(f"build failed (exit {proc.returncode})")


def main() -> None:
    onefile = "--onefile" in sys.argv

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller is not installed.\n"
            "    python -m pip install --user pyinstaller certifi pillow")

    cmd = [sys.executable, "-m", "PyInstaller",
           "--onefile" if onefile else "--onedir",
           "--windowed",
           "--name", NAME,
           "--noconfirm",
           "--distpath", DIST,
           "--workpath", WORK,
           "--specpath", HERE,
           # The package is imported by name from the entry script, and
           # PyInstaller's analysis does not always follow that; naming it is
           # cheap insurance.
           "--hidden-import", "equpdater.app"]

    if os.path.exists(ICON):
        # --icon brands the .exe *file*. --add-data puts the same file inside
        # the build, because that is what the running *window* reads (see
        # branding.icon_candidates). Doing only the first leaves an app with
        # the right icon in Explorer and Tk's feather on the taskbar.
        cmd += ["--icon", ICON, "--add-data", ICON + os.pathsep + "."]
    if os.path.exists(ICON_PNG):
        cmd += ["--add-data", ICON_PNG + os.pathsep + "."]
    if os.path.exists(BACKGROUND):
        cmd += ["--add-data", BACKGROUND + os.pathsep + "."]
    if os.path.isdir(FONTS_DIR):
        cmd += ["--add-data", FONTS_DIR + os.pathsep + "fonts"]

    cmd.append(ENTRY)
    kind = "one file" if onefile else "folder"
    print(f"Building {NAME} {branding.APP_VERSION}  ({kind})...")
    run(cmd)

    exe_name = NAME + (".exe" if os.name == "nt" else "")
    if onefile:
        built = os.path.join(DIST, exe_name)
    else:
        built = os.path.join(DIST, NAME, exe_name)

    if not os.path.exists(built):
        raise SystemExit(f"PyInstaller reported success but {built} is missing")

    print(f"\n  {built}")

    if onefile:
        # A single file is portable, so it is also worth having at the repo
        # root. A folder build is not copied anywhere: its executable only
        # works beside its own _internal directory, and half of a folder
        # build sitting at the root would be a trap.
        final = os.path.join(HERE, exe_name)
        try:
            shutil.copy2(built, final)
            print(f"  {final}")
        except PermissionError:
            print(f"  Could not copy over {final} - it is in use.")
            print("  Close EqUpdater and copy it yourself, or re-run this.")
        print("\n  Note: a one-file build unpacks to %TEMP% on every launch "
              "and\n  will not start if the system drive is full. The folder "
              "build\n  (python build.py) has no such requirement.")
    else:
        print("\n  Run the executable from inside that folder - it needs the "
              "\n  _internal directory beside it. Move the whole folder, "
              "never\n  the .exe on its own.")

    print("\nDone.")


if __name__ == "__main__":
    main()
