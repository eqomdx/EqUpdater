"""Frozen-build entry point.

PyInstaller runs its entry script as `__main__` with no parent package, so
`equpdater/__main__.py`'s relative imports fail inside a built executable --
the app starts, raises ImportError before the window exists, and exits with
nothing on screen. (A --windowed build has no console to print it to, which
is why it looked like the exe simply did not run.)

So the frozen build starts here instead, with an absolute import.
`python -m equpdater` still goes through `equpdater/__main__.py`.

``--self-test=<file>`` checks a packaged build without opening a window:
it writes what the build carries (version, CA bundles and TLS settings,
aria2c, fonts, artwork) to <file> as JSON and exits 0 when all of it is
there. ``--network`` adds a real HTTPS request through the app's own
verifying opener. ``--gui`` (needs a display; CI uses Xvfb) also builds the
main window -- which renders the background through ImageTk.PhotoImage --
opens Settings and Login Doctor in it, and closes it again, so a build
missing Pillow's Tk bridge fails here and not on a player's screen. CI runs it on every release artifact.
"""

import sys


def _font_stack_check(report: dict, problems: list) -> None:
    """Linux, with a window open: the fontconfig Tk loaded must be the
    host's, and the bundle must carry none of the host font stack -- an old
    bundled fontconfig reading a newer host /etc/fonts is what flooded a
    Fedora tester's terminal with errors (platforms.HOST_FONT_STACK)."""
    import ctypes
    import os
    from equpdater import platforms
    if not platforms.LINUX:
        return
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        carried = [n for n in platforms.HOST_FONT_STACK
                   if os.path.lexists(os.path.join(bundle, n))]
        report["bundled_font_stack"] = carried
        if carried:
            problems.append("bundle carries the host font stack: "
                            + ", ".join(carried))
    lib = platforms.loaded_library("libfontconfig.so")
    report["fontconfig_library"] = lib
    if lib:
        try:
            v = ctypes.CDLL(lib).FcGetVersion()
            report["fontconfig_version"] = f"{v // 10000}.{v // 100 % 100}.{v % 100}"
        except (OSError, AttributeError):
            pass
        if bundle and os.path.abspath(lib).startswith(os.path.abspath(bundle)):
            problems.append(f"fontconfig loaded from the bundle: {lib}")


def _gui_check(report: dict, problems: list) -> None:
    """Build the real main window and check its background is an ImageTk
    PhotoImage, exactly as a player's first launch draws it."""
    import os
    import tkinter as tk
    os.environ["EQUPDATER_NO_LANGUAGE_PROMPT"] = "1"
    try:
        from PIL import ImageTk
        from equpdater.app import EqUpdaterApp
        win = EqUpdaterApp()
        try:
            win.update()
            photo = getattr(win, "_bg_photo", None)
            report["gui_background"] = type(photo).__name__
            if not isinstance(photo, ImageTk.PhotoImage):
                problems.append("background was not drawn through ImageTk")
            elif (photo.width(), photo.height()) != win._bg_pil.size:
                problems.append("background PhotoImage has the wrong size")
            # The Tk bridge itself, by name: what the frozen build dropped.
            # Imported by a computed name on purpose: a literal import here
            # would make PyInstaller bundle the module and hide the bug this
            # check exists to catch.
            import importlib
            importlib.import_module(".".join(("PIL", "_tkinter_finder")))
            report["gui_tk_bridge"] = True
            # Settings and its Login Doctor window, built in the packaged
            # app too: they add widgets and a worker the main window lacks.
            win._open_settings()
            win.update()
            win._open_login_doctor()
            win.update()
            text = win._doctor_text.get("1.0", "end").strip()
            report["gui_login_doctor"] = bool(text)
            if not text:
                problems.append("Login Doctor showed nothing")
            _font_stack_check(report, problems)
            # The bundled fonts reached Tk through that fontconfig.
            fonts = win._fonts
            report["gui_fonts"] = {"friz": fonts.friz,
                                   "opendyslexic": fonts.open_dyslexic}
            if not fonts.friz or not fonts.open_dyslexic:
                problems.append("bundled fonts not visible to Tk")
        finally:
            win.destroy()
    except (Exception, tk.TclError) as e:
        report["gui_tk_bridge"] = False
        problems.append(f"GUI start failed: {type(e).__name__}: {e}")


def self_test(out_path: str, network: bool, gui: bool = False) -> int:
    import json
    import os
    import platform
    import ssl
    import subprocess

    from equpdater import app, branding, platforms, ui

    report = {
        "version": branding.APP_VERSION,
        "platform": sys.platform,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "frozen": platforms.frozen(),
        "ca_sources": app.CA_SOURCES,
        "tls_verifies": (app.SSL_CTX.verify_mode == ssl.CERT_REQUIRED
                         and app.SSL_CTX.check_hostname),
        "tls_minimum": getattr(app.SSL_CTX.minimum_version, "name",
                               str(app.SSL_CTX.minimum_version)),
        "fonts": sorted(os.path.basename(p) for p in ui._bundled_font_paths()),
        "artwork": {name: any(os.path.exists(p) for p in candidates)
                    for name, candidates in (
                        ("background", branding.background_candidates()),
                        ("animated_background", branding.animated_background_candidates()),
                        ("icon", branding.icon_candidates()))},
        "aria2c": platforms.find_aria2c(app.APP_DATA_DIR),
        "problems": [],
    }
    problems = report["problems"]
    if not report["ca_sources"]:
        problems.append("no CA bundle loaded")
    if not report["tls_verifies"]:
        problems.append("TLS verification is not on")
    if not any(f.lower().startswith("opendyslexic") for f in report["fonts"]):
        problems.append("bundled fonts missing")
    problems += [f"{name} missing" for name, ok in report["artwork"].items() if not ok]
    if not platforms.WINDOWS:
        if not report["aria2c"]:
            problems.append("no aria2c")
        else:
            try:
                out = subprocess.run([report["aria2c"], "--version"],
                                     capture_output=True, text=True, timeout=30)
                report["aria2c_version"] = (out.stdout.splitlines() or [""])[0]
                if out.returncode != 0:
                    problems.append("aria2c does not run")
            except OSError as e:
                problems.append(f"aria2c does not run: {e}")
    if gui:
        _gui_check(report, problems)
    if network:
        try:
            with app.secure_urlopen("https://github.com/", timeout=20) as r:
                report["https_status"] = r.status
        except Exception as e:
            problems.append(f"HTTPS request failed: {e}")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return 0 if not problems else 1


def main() -> None:
    for arg in sys.argv[1:]:
        if arg.startswith("--self-test="):
            sys.exit(self_test(arg.split("=", 1)[1], "--network" in sys.argv,
                               "--gui" in sys.argv))

    from equpdater.app import EqUpdaterApp, _enable_dpi_awareness
    _enable_dpi_awareness()
    EqUpdaterApp().mainloop()


if __name__ == "__main__":
    main()
