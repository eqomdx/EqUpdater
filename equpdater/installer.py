"""The Windows release: one .exe that installs EqUpdater and starts it.

EqUpdater-vX.Y.Z-Windows.exe is this program with the folder build of
EqUpdater packed inside it (EqUpdater-app.zip). Run, it

1. unpacks the build next to the permanent home,
   %LOCALAPPDATA%\\Programs\\EqUpdater (same drive, so moves are renames);
2. installs it there with equpdater.deploy -- staged, the version that was
   there kept until the new one is in place, the player's own files in that
   folder carried across, nothing in %LOCALAPPDATA%\\EqUpdater touched;
3. points every EqUpdater shortcut at it, adds a Start-menu entry, and
   offers a desktop shortcut the first time;
4. starts EqUpdater, and closes.

Running a newer one later is the update; running the same one again
changes nothing. Why an installer and not EqUpdater itself as one file: a
one-file program unpacks itself into %TEMP% on every launch (and fails
opaquely when C: is full), and a downloaded copy run from Downloads would
leave the shortcut on the previous version -- the 2.0.5 bug.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import zipfile

from . import branding, deploy

PAYLOAD = "EqUpdater-app.zip"


def payload_path() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, PAYLOAD)


def unpack(payload: str, dest: str) -> str:
    """Extract the packed build into ``dest`` (replacing it) and return the
    folder holding EqUpdater.exe. Entries that would land outside ``dest``
    are refused."""
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    root = os.path.realpath(dest)
    with zipfile.ZipFile(payload) as zf:
        for info in zf.infolist():
            target = os.path.realpath(os.path.join(dest, info.filename))
            if target != root and not target.startswith(root + os.sep):
                raise deploy.DeployError(f"Unsafe path in the package: {info.filename}")
        zf.extractall(dest)
    for folder, _dirs, files in os.walk(dest):
        if deploy.EXE in files:
            return folder
    raise deploy.DeployError("The package holds no EqUpdater.exe.")


def install(payload: str, install_dir: str | None = None,
            want_desktop=lambda: True, folders=None) -> tuple:
    """Install from ``payload``; returns (exe, shortcuts changed, shortcuts
    created). Raises deploy.DeployError, with the previous version intact,
    when it cannot. ``want_desktop()`` is asked only when there is no
    desktop shortcut yet."""
    install_dir = os.path.abspath(install_dir or deploy.default_install_dir())
    staging = install_dir + ".payload"
    os.makedirs(os.path.dirname(install_dir), exist_ok=True)
    try:
        build = unpack(payload, staging)
        exe = deploy.deploy(build, install_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    # deploy.shortcut_folders(): the desktop first, then the Start menu.
    folders = folders if folders is not None else deploy.shortcut_folders()
    changed = deploy.fix_shortcuts(exe, folders)
    created = []
    start = folders[1] if len(folders) > 1 else None
    if start and os.path.isdir(start):
        lnk = os.path.join(start, deploy.APP + ".lnk")
        if not os.path.exists(lnk):
            deploy.write_shortcut(lnk, exe)
            created.append(lnk)
    desktop = os.path.join(folders[0], deploy.APP + ".lnk") if folders else None
    if desktop and not os.path.exists(desktop) and want_desktop():
        deploy.write_shortcut(desktop, exe)
        created.append(desktop)
    return exe, changed, created


def main() -> int:
    """The installer's window: one line of progress, a question the first
    time, a message if it fails."""
    import tkinter as tk
    from tkinter import messagebox

    from . import platforms

    title = f"{branding.APP_NAME} {branding.APP_VERSION}"
    root = tk.Tk()
    root.title(title)
    root.configure(bg="#081a35")
    root.resizable(False, False)
    for path in branding.icon_candidates():
        try:
            if path.lower().endswith(".png") and os.path.exists(path):
                root.iconphoto(True, tk.PhotoImage(file=path))
                break
        except tk.TclError:
            continue
    status = tk.Label(root, text=f"Installing {title}…", font=("Segoe UI", 11),
                      fg="#eee9dc", bg="#081a35", padx=32, pady=24)
    status.pack()
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2,
                              (root.winfo_screenheight() - h) // 3))

    result = {}
    asked = threading.Event()
    answer = {}

    def want_desktop():
        root.after(0, ask_desktop)
        asked.wait()
        return answer.get("yes", True)

    def ask_desktop():
        answer["yes"] = messagebox.askyesno(
            title, "Put an EqUpdater shortcut on the desktop?", parent=root)
        asked.set()

    def work():
        try:
            result["value"] = install(payload_path(), want_desktop=want_desktop)
        except Exception as e:                  # shown to the player below
            result["error"] = e

    def finish():
        if "error" not in result and "value" not in result:
            root.after(100, finish)
            return
        if "error" in result:
            messagebox.showerror(title, f"{branding.APP_NAME} could not be "
                                 f"installed:\n\n{result['error']}", parent=root)
            root.destroy()
            result["code"] = 1
            return
        exe = result["value"][0]
        try:
            platforms.spawn_detached([exe], cwd=os.path.dirname(exe))
        except OSError as e:
            messagebox.showerror(title, f"Installed to {exe}, but it could not "
                                 f"be started: {e}", parent=root)
        root.destroy()
        result["code"] = 0

    threading.Thread(target=work, daemon=True).start()
    root.after(100, finish)
    root.mainloop()
    return result.get("code", 1)
