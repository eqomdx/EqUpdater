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

**Tests gate releases, not installs.** ``--release`` runs the whole test
suite first (tools/check.py) and refuses to build if anything fails: that is
the build to hand to other people. A plain build -- what install.ps1 runs on
a user's own PC -- does not, because a GUI or timing test behaving
differently on one machine must not stop somebody installing the program.

Usage:
    python build.py             # dist/EqUpdater/EqUpdater.exe  (recommended)
    python build.py --release   # the same, only after the test suite passes
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
BACKGROUNDS = [os.path.join(HERE, branding.BACKGROUND_STATIC),
               os.path.join(HERE, branding.BACKGROUND_ANIMATED)]
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
        explain_antivirus_interruption()
        raise SystemExit(f"build failed (exit {proc.returncode})")


#: Printed when antivirus removed the executable mid-build. install.ps1
#: recognises the first line and adds Windows Defender's own record.
ANTIVIRUS_HINT = """
The build was interrupted by antivirus software.

PyInstaller had already packed EqUpdater and created
    {exe}
but the file was locked and then removed before the build could finish -- the
"Execution of ... failed ... Retrying" and "cannot find the file" lines above.
That is antivirus quarantining it: PyInstaller-built programs are a common
false positive, and a freshly built, unsigned .exe the most common.

To fix it:
  1. Open Windows Security -> Virus & threat protection -> Protection history
     (or your antivirus's quarantine list) and allow / restore EqUpdater.exe.
  2. Or add an exclusion for this folder:
         {folder}
  3. Run the installer again.
"""


def explain_antivirus_interruption() -> None:
    """After a failed PyInstaller run: if it got as far as packing the app
    (the .pkg is there) but the executable it builds from that is gone, the
    build did not fail on its own -- something removed the file. Say so,
    instead of leaving a retry log and a FileNotFoundError to decode."""
    if os.name != "nt":
        return
    work = os.path.join(WORK, NAME)
    packed = os.path.exists(os.path.join(work, NAME + ".pkg"))
    exe = os.path.join(work, NAME + ".exe")
    if packed and not os.path.exists(exe):
        print(ANTIVIRUS_HINT.format(exe=exe, folder=HERE))


def main() -> None:
    onefile = "--onefile" in sys.argv

    if "--release" in sys.argv:
        sys.path.insert(0, os.path.join(HERE, "tools"))
        from check import run_suite
        log = os.path.join(WORK, "test-log.txt")
        print("Release build: running the test suite first...")
        passed, report = run_suite(log)
        print(report)
        if not passed:
            raise SystemExit("The test suite failed. Not building a release.")

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
           "--hidden-import", "equpdater.app",
           # ImageTk finds its Tk binding through this module, which is
           # imported dynamically; without it every PhotoImage fails in a
           # frozen build (seen on Linux).
           "--hidden-import", "PIL._tkinter_finder"]

    if os.path.exists(ICON):
        # --icon brands the .exe *file*. --add-data puts the same file inside
        # the build, because that is what the running *window* reads (see
        # branding.icon_candidates). Doing only the first leaves an app with
        # the right icon in Explorer and Tk's feather on the taskbar.
        cmd += ["--icon", ICON, "--add-data", ICON + os.pathsep + "."]
    if os.path.exists(ICON_PNG):
        cmd += ["--add-data", ICON_PNG + os.pathsep + "."]
    for background in BACKGROUNDS:
        if os.path.exists(background):
            cmd += ["--add-data", background + os.pathsep + "."]
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
