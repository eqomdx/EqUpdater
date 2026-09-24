"""Build EqUpdater.exe.

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

Usage:
    python build.py            # build into dist/, then copy to the repo root
    python build.py --onedir   # a folder build, for debugging a frozen run
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
ICON = os.path.join(HERE, f"{NAME}.ico")
# The frozen build starts at the top-level launcher, not at the package's
# __main__: PyInstaller runs its entry script as `__main__` with no parent
# package, and the relative imports in equpdater/__main__.py raise
# ImportError there before a window ever appears. See EqUpdater.py.
ENTRY = os.path.join(HERE, f"{NAME}.py")


def run(cmd: list) -> None:
    print("  $ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=HERE)
    if proc.returncode != 0:
        raise SystemExit(f"build failed (exit {proc.returncode})")


def main() -> None:
    onedir = "--onedir" in sys.argv

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller is not installed.\n"
            "    python -m pip install --user pyinstaller certifi")

    cmd = [sys.executable, "-m", "PyInstaller",
           "--onedir" if onedir else "--onefile",
           "--windowed",
           "--name", NAME,
           "--noconfirm",
           "--distpath", os.path.join(HERE, "dist"),
           "--workpath", os.path.join(HERE, "build"),
           "--specpath", HERE,
           # The package is imported by name from the entry script, and
           # PyInstaller's analysis of a `python -m` style entry does not
           # always follow that; naming it is cheap insurance.
           "--hidden-import", "equpdater.app"]

    if os.path.exists(ICON):
        # --icon brands the .exe file. --add-data puts the same file inside
        # the bundle, because that is what the running *window* reads: see
        # branding.icon_candidates. Doing only the first leaves an app with
        # the right icon in Explorer and Tk's feather on the taskbar.
        cmd += ["--icon", ICON, "--add-data", ICON + os.pathsep + "."]

    cmd.append(ENTRY)
    print(f"Building {NAME} {branding.APP_VERSION}...")
    run(cmd)

    built = os.path.join(HERE, "dist",
                         NAME if onedir else (NAME + (".exe" if os.name == "nt"
                                                      else "")))
    if not os.path.exists(built):
        raise SystemExit(f"PyInstaller reported success but {built} is missing")

    if not onedir:
        final = os.path.join(HERE, os.path.basename(built))
        try:
            shutil.copy2(built, final)
            print(f"\n  {final}")
        except PermissionError:
            # Windows holds the file while it is running. Say so plainly
            # rather than failing with a raw OS error.
            print(f"\n  Built: {built}")
            print(f"  Could not copy over {final} - it is in use.")
            print("  Close EqUpdater and copy it yourself, or re-run this.")
            return
    print(f"\n  {built}")
    print("\nDone.")


if __name__ == "__main__":
    main()
