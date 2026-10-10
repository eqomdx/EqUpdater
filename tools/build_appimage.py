"""Build the Linux release: dist/EqUpdater-vX.Y.Z-Linux-x86_64.AppImage.

Runs on Linux (GitHub Actions: .github/workflows/release.yml). It

1. builds the folder build with build.py (PyInstaller: the Python runtime,
   Tk, Pillow, certifi's CA bundle, EqUpdater's artwork and fonts);
2. adds a native aria2c -- a pinned static build, checked against its
   sha256 -- so the client sync needs nothing from the system;
3. lays out an AppDir (AppRun, desktop entry, icon) and packs it with a
   pinned appimagetool, also checked against its sha256.

Nobody needs Python, pip or anything else to run the result: download it,
mark it executable, run it. The AppImage runtime appimagetool embeds is the
static one, so distributions without libfuse2 (Ubuntu 24.04) run it too.

    python3 tools/build_appimage.py
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from equpdater import branding  # noqa: E402

#: Pinned downloads: (url, sha256). Both checked before anything is used.
#: aria2 1.37.0, statically linked against musl (abcfy2/aria2-static-build):
#: one file, no libraries needed from the system.
ARIA2_STATIC = (
    "https://github.com/abcfy2/aria2-static-build/releases/download/1.37.0/"
    "aria2-x86_64-linux-musl_static.zip",
    "e0a09b12ef67f35f8a8e4fdddbec851d235b7c31da549d0578bff459032b499a")
APPIMAGETOOL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/"
    "appimagetool-x86_64.AppImage",
    "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0")

NAME = branding.APP_NAME
WORK = os.path.join(HERE, "build", "appimage")
APPDIR = os.path.join(WORK, f"{NAME}.AppDir")
DIST = os.path.join(HERE, "dist")

APPRUN = """#!/bin/sh
# EqUpdater's AppImage entry: run the bundled program from inside the mount.
HERE="${APPDIR:-$(dirname "$(readlink -f "$0")")}"
exec "$HERE/usr/bin/EqUpdater" "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=EqUpdater
GenericName=OctoWoW updater
Comment=Updates the OctoWoW client, mods, addons and texture packs
Exec=EqUpdater
Icon=equpdater
Terminal=false
Categories=Game;Utility;
StartupWMClass=EqUpdater
"""


def fetch(url: str, sha256: str) -> bytes:
    """Download ``url`` and refuse it unless its sha256 is the pinned one."""
    print(f"  fetching {url}")
    req = urllib.request.Request(url, headers={"User-Agent": branding.USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise SystemExit(f"checksum mismatch for {url}: {got} != {sha256}")
    return data


def make_executable(path: str) -> None:
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> str:
    if not sys.platform.startswith("linux"):
        raise SystemExit("The AppImage is built on Linux.")
    subprocess.run([sys.executable, os.path.join(HERE, "build.py")],
                   cwd=HERE, check=True)
    built = os.path.join(DIST, NAME)
    if not os.path.isfile(os.path.join(built, NAME)):
        raise SystemExit(f"{built}/{NAME} is missing: the build failed")

    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    usr_bin = os.path.join(APPDIR, "usr", "bin")
    shutil.copytree(built, usr_bin)

    # Native aria2c beside the program: platforms.find_aria2c looks there
    # first (the executable's own folder).
    with zipfile.ZipFile(io.BytesIO(fetch(*ARIA2_STATIC))) as zf:
        member = next(n for n in zf.namelist() if os.path.basename(n) == "aria2c")
        with open(os.path.join(usr_bin, "aria2c"), "wb") as f:
            f.write(zf.read(member))
    make_executable(os.path.join(usr_bin, "aria2c"))

    apprun = os.path.join(APPDIR, "AppRun")
    with open(apprun, "w", newline="\n") as f:
        f.write(APPRUN)
    make_executable(apprun)
    with open(os.path.join(APPDIR, "equpdater.desktop"), "w", newline="\n") as f:
        f.write(DESKTOP)
    icon = os.path.join(HERE, "icon.png")
    shutil.copy(icon, os.path.join(APPDIR, "equpdater.png"))
    shutil.copy(icon, os.path.join(APPDIR, ".DirIcon"))
    icons = os.path.join(APPDIR, "usr", "share", "icons", "hicolor", "256x256", "apps")
    os.makedirs(icons)
    shutil.copy(icon, os.path.join(icons, "equpdater.png"))

    tool = os.path.join(WORK, "appimagetool")
    with open(tool, "wb") as f:
        f.write(fetch(*APPIMAGETOOL))
    make_executable(tool)

    out = os.path.join(DIST, f"{NAME}-v{branding.APP_VERSION}-Linux-x86_64.AppImage")
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, ARCH="x86_64",
               # CI runners have no FUSE: let the tool unpack itself instead.
               APPIMAGE_EXTRACT_AND_RUN="1")
    subprocess.run([tool, "--no-appstream", APPDIR, out], env=env, check=True)
    make_executable(out)
    print(f"\n  {out}  ({os.path.getsize(out) // (1024 * 1024)} MB)")
    return out


if __name__ == "__main__":
    main()
