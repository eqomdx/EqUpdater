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
verifying opener. CI runs it on every release artifact.
"""

import sys


def self_test(out_path: str, network: bool) -> int:
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
            sys.exit(self_test(arg.split("=", 1)[1], "--network" in sys.argv))

    from equpdater.app import EqUpdaterApp, _enable_dpi_awareness
    _enable_dpi_awareness()
    EqUpdaterApp().mainloop()


if __name__ == "__main__":
    main()
