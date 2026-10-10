"""A failed addon install or update comes back to the person who asked.

It used to be logged and then painted over: the worker stored the error,
the post-install rescan rebuilt the list, and a failed *update* -- its folder
still on disk -- had its error dropped as stale. The player saw the row stop
saying "downloading…" and nothing else.

Now each failure is put in a plain category naming the host that failed,
logged in full, and shown once: one dialog for one addon, one summary for a
batch. A failed update leaves the installed copy and its record alone.
"""

import errno
import io
import os
import shutil
import socket
import ssl
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_app_smoke import HAVE_TK, _close_app  # noqa: E402

OCTO = "https://octowow.st/git/someone/Questie"


def _http(code, url="https://octowow.st/git/someone/Questie/archive/x.zip"):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr("repo-sha/" + name, data)
    return buf.getvalue()


@unittest.skipUnless(HAVE_TK, "no display")
class TestClassification(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from equpdater import app
        cls.m = app

    def cat(self, e, url=OCTO):
        category, template, values = self.m.addon_failure(e, url)
        return category, template.format(**values)

    def wrapped(self, e):
        """As addon_remote_sha(raise_errors=True) raises it."""
        try:
            try:
                raise e
            except Exception as inner:
                raise RuntimeError(self.m._describe_net_error(inner)) from inner
        except RuntimeError as outer:
            return outer

    def test_timeout(self):
        for e in (urllib.error.URLError(socket.timeout("timed out")),
                  TimeoutError("timed out"), socket.timeout("timed out")):
            c, text = self.cat(e)
            self.assertEqual(c, "timeout")
            self.assertIn("octowow.st", text)
            self.assertNotIn("internet", text)

    def test_dns(self):
        e = urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))
        c, text = self.cat(e)
        self.assertEqual(c, "dns")
        self.assertIn("octowow.st", text)
        self.assertIn("DNS", text)

    def test_refused_connection_is_the_hosts_not_the_players(self):
        c, text = self.cat(urllib.error.URLError(ConnectionRefusedError(111, "refused")))
        self.assertEqual(c, "connection")
        self.assertNotIn("internet", text)

    def test_http(self):
        self.assertEqual(self.cat(_http(503))[0], "server")
        self.assertIn("HTTP 503", self.cat(_http(503))[1])
        self.assertEqual(self.cat(_http(404))[0], "not_found")
        self.assertEqual(self.cat(_http(403))[0], "forbidden")
        self.assertEqual(self.cat(_http(429))[0], "rate_limit")
        self.assertEqual(self.cat(_http(418))[0], "http")

    def test_http_names_the_host_that_answered(self):
        e = _http(502, "https://codeload.github.com/a/b/zip/x")
        self.assertIn("codeload.github.com", self.cat(e, OCTO)[1])

    def test_tls(self):
        e = urllib.error.URLError(ssl.SSLCertVerificationError(
            1, "certificate verify failed"))
        self.assertEqual(self.cat(e)[0], "tls")

    def test_ddos_challenge(self):
        c, text = self.cat(self.m.DdosCheckError(self.m.DDOS_CHECK))
        self.assertEqual(c, "challenge")
        self.assertIn("octowow.st", text)
        self.assertIn("Try again later", text)
        self.assertNotIn("internet", text)

    def test_lookup_errors_are_classified_by_their_cause(self):
        self.assertEqual(self.cat(self.wrapped(self.m.DdosCheckError("x")))[0],
                         "challenge")
        self.assertEqual(self.cat(self.wrapped(_http(500)))[0], "server")
        self.assertEqual(self.cat(self.wrapped(urllib.error.URLError(
            socket.gaierror(-3, "x"))))[0], "dns")
        self.assertEqual(self.cat(self.wrapped(ValueError("not json")))[0],
                         "lookup")
        self.assertEqual(self.cat(RuntimeError(
            "Could not resolve remote commit"))[0], "lookup")

    def test_corrupt_archive(self):
        self.assertEqual(self.cat(zipfile.BadZipFile("bad"))[0], "archive")

    def test_filesystem(self):
        self.assertEqual(self.cat(OSError(errno.ENOSPC, "No space"))[0],
                         "no_space")
        if not self.m.platforms.WINDOWS:
            self.assertEqual(self.cat(PermissionError(errno.EACCES, "denied"))[0],
                             "permission")
            # No antivirus advice off Windows.
            self.assertEqual(self.cat(FileNotFoundError(errno.ENOENT, "gone"))[0],
                             "write")

    def test_conflict_and_source(self):
        from equpdater import gamepaths
        state = gamepaths.AddonDirState("x", conflicts=[("Questie", "a", "b")])
        self.assertEqual(self.cat(gamepaths.AddonDirConflict(state))[0],
                         "conflict")
        self.assertEqual(self.cat(RuntimeError(
            "Addon URL is not from an allowed git host"))[0], "source")

    def test_every_category_formats_and_is_translated(self):
        from equpdater import i18n
        from equpdater.i18n import TRANSLATIONS
        values = dict(host="h", code=500, error="e")
        for template in self.m.ADDON_FAILURES.values():
            template.format(**values)
            for table in [t for t in TRANSLATIONS.values() if t]:
                table[template].format(**values)
        self.assertTrue(i18n.tr)


@unittest.skipUnless(HAVE_TK, "no display")
class TestFailedUpdateKeepsTheInstalledCopy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from equpdater import app
        cls.m = app

    def setUp(self):
        self.client = tempfile.mkdtemp(prefix="equ-upd-")
        self.addons = os.path.join(self.client, "Interface", "AddOns")
        self.dest = os.path.join(self.addons, "Questie")
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "Questie.toc"), "w") as f:
            f.write("old")

    def tearDown(self):
        shutil.rmtree(self.client, ignore_errors=True)

    def install(self, data):
        with mock.patch.object(self.m, "_download_archive", return_value=data):
            self.m.install_addon_files(self.client, "Questie", OCTO, "f" * 40)

    def assert_intact(self):
        with open(os.path.join(self.dest, "Questie.toc")) as f:
            self.assertEqual(f.read(), "old")
        self.assertEqual(os.listdir(self.addons), ["Questie"])  # no tmp left

    def test_corrupt_archive(self):
        with self.assertRaises(zipfile.BadZipFile):
            self.install(b"<html>not a zip</html>")
        self.assert_intact()

    def test_extraction_failure(self):
        real_open = open

        def failing_open(path, mode="r", *a, **kw):
            if "w" in mode and ".tmp_install" in str(path):
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(path, mode, *a, **kw)
        with mock.patch("builtins.open", failing_open), \
                self.assertRaises(OSError):
            self.install(_zip({"Questie.toc": "new"}))
        self.assert_intact()

    def test_write_failure_on_replace(self):
        real = os.replace

        def replace(src, dst):
            if str(src).endswith(".tmp_install"):
                raise PermissionError(errno.EACCES, "denied")
            return real(src, dst)
        with mock.patch.object(self.m.os, "replace", replace), \
                self.assertRaises(PermissionError):
            self.install(_zip({"Questie.toc": "new"}))
        self.assert_intact()

    def test_a_good_archive_still_installs(self):
        self.install(_zip({"Questie.toc": "new"}))
        with open(os.path.join(self.dest, "Questie.toc")) as f:
            self.assertEqual(f.read(), "new")


class _InlineThread:
    def __init__(self, target=None, daemon=None, **_kw):
        self.target = target

    def start(self):
        self.target()


@unittest.skipUnless(HAVE_TK, "no display")
class TestFailuresReachTheUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="equ-addon-fail-")
        os.environ["LOCALAPPDATA"] = cls.tmp
        os.environ["XDG_DATA_HOME"] = cls.tmp
        for mod in [m for m in list(sys.modules) if m.startswith("equpdater")]:
            del sys.modules[mod]
        from equpdater import app
        cls.m = app
        cls.app = app.EqUpdaterApp()
        for _ in range(8):
            cls.app.update()

    @classmethod
    def tearDownClass(cls):
        _close_app(cls.app)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.client = tempfile.mkdtemp(prefix="client-", dir=self.tmp)
        open(os.path.join(self.client, "WoW.exe"), "wb").close()
        self.addons = os.path.join(self.client, "Interface", "AddOns")
        os.makedirs(self.addons)
        self.app._game_path.set(self.client)
        for _ in range(4):
            self.app.update()
        a = self.app
        a._addons_busy = False
        a._addons_status = {"state": "done", "addons": {}, "available": []}
        a._addon_errors.clear()
        self.m.update_config(lambda c: c.pop("addons", None))

        self.logged = []
        self.asked = []
        self.logs_opened = []
        self.patches = [
            mock.patch.object(self.m.threading, "Thread", _InlineThread),
            mock.patch.object(self.m, "log",
                              lambda msg, tag="": self.logged.append(msg)),
            mock.patch.object(self.m, "addon_install_source", lambda g: g),
            mock.patch("tkinter.messagebox.askyesno",
                       lambda t, b, **kw: self.asked.append((t, b)) or True),
            mock.patch.object(a, "_addons_verify", lambda *x, **k: None),
            mock.patch.object(a, "_show_logs",
                              lambda: self.logs_opened.append(1)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def pump(self):
        for _ in range(6):
            self.app.update()

    def rec(self, folder, status="available", git=OCTO):
        return {"folder": folder, "status": status, "git": git,
                "branch": None, "ref": None, "toc": {}, "description": None,
                "error": None}

    def assert_not_stuck(self):
        a = self.app
        self.assertFalse(a._addons_busy)
        self.assertFalse(a._addons_installing)
        for r in a._addons_status["addons"].values():
            self.assertNotEqual(r["status"], "downloading")
        self.assertNotEqual(a._status_var.get(), self.m.tr("Downloading addons…"))

    def test_one_failed_install_says_why_and_offers_the_log(self):
        def sha(*a, **k):
            try:
                raise self.m.DdosCheckError(self.m.DDOS_CHECK)
            except Exception as e:
                raise RuntimeError("x") from e
        rec = self.rec("Questie")
        self.app._addons_status["available"] = [rec]
        with mock.patch.object(self.m, "addon_remote_sha", sha):
            self.app._addon_apply([rec])
            self.pump()
        self.assertEqual(len(self.asked), 1)
        title, body = self.asked[0]
        self.assertEqual(title, "Failed to install Questie")
        self.assertIn("octowow.st", body)
        self.assertIn("DDoS", body)
        self.assertIn("log", body)
        self.assertNotIn("Traceback", body)
        self.assertEqual(self.logs_opened, [1])
        self.assert_not_stuck()
        self.assertEqual(rec["status"], "available")
        self.assertNotIn("Questie", self.m.load_config().get("addons", {}))
        self.assertIn("Questie", self.app._addon_errors)   # under the row
        self.assertTrue(any("DdosCheckError" in line for line in self.logged))
        self.assertTrue(any("install failed" in line for line in self.logged))

    def test_buttons_come_back(self):
        busy = []
        with mock.patch.object(self.m, "addon_remote_sha",
                               side_effect=TimeoutError("timed out")), \
                mock.patch.object(self.app, "_refresh_ready_state",
                                  lambda: busy.append(1)):
            self.app._addon_apply([self.rec("Questie")])
            self.pump()
        self.assertEqual(busy, [1])
        self.assertIn("did not answer in time", self.asked[0][1])

    def test_failed_update_keeps_the_addon_and_its_record(self):
        dest = os.path.join(self.addons, "Questie")
        os.makedirs(dest)
        with open(os.path.join(dest, "Questie.toc"), "w") as f:
            f.write("old")
        old = self.m.new_addon_record(managed=True, git=OCTO, sha="a" * 40)
        self.m.update_config(lambda c: c.setdefault("addons", {})
                             .__setitem__("Questie", old))
        rec = self.rec("Questie", status="updateAvailable")
        self.app._addons_status["addons"]["Questie"] = rec
        with mock.patch.object(self.m, "addon_remote_sha",
                               return_value="b" * 40), \
                mock.patch.object(self.m, "_download_archive",
                                  return_value=b"<html>challenge</html>"):
            self.app._addon_apply([rec])
            self.pump()
        title, body = self.asked[0]
        self.assertEqual(title, "Failed to update Questie")
        self.assertIn("not a valid addon archive", body)
        self.assertIn("installed copy was left", body)
        with open(os.path.join(dest, "Questie.toc")) as f:
            self.assertEqual(f.read(), "old")
        self.assertEqual(sorted(os.listdir(self.addons)), ["Questie"])
        self.assertEqual(self.m.load_config()["addons"]["Questie"]["sha"],
                         "a" * 40)
        self.assertEqual(rec["status"], "updateAvailable")
        self.assert_not_stuck()

    def test_update_all_continues_and_reports_once(self):
        good = _zip({"Good.toc": "x"})

        def sha(git, *a, **k):
            if git.endswith("/Dns"):
                raise RuntimeError("x") from urllib.error.URLError(
                    socket.gaierror(-2, "x"))
            return "c" * 40

        def download(url):
            if "/Http/" in url:
                raise _http(503, url)
            return good
        recs = [self.rec(n, git=f"https://octowow.st/git/someone/{n}")
                for n in ("Dns", "Good", "Http")]
        with mock.patch.object(self.m, "addon_remote_sha", sha), \
                mock.patch.object(self.m, "_download_archive", download):
            self.app._addon_apply(recs)
            self.pump()
        self.assertEqual(len(self.asked), 1)
        title, body = self.asked[0]
        self.assertEqual(title, "Addons: 2 of 3 failed")
        self.assertIn("Dns:", body)
        self.assertIn("Http:", body)
        self.assertIn("HTTP 503", body)
        self.assertNotIn("Good:", body)
        self.assertIn("other 1 finished", body)
        managed = self.m.load_config().get("addons", {})
        self.assertIn("Good", managed)
        self.assertNotIn("Dns", managed)
        self.assertNotIn("Http", managed)
        self.assertTrue(os.path.isdir(os.path.join(self.addons, "Good")))
        self.assert_not_stuck()

    def test_success_shows_no_dialog(self):
        with mock.patch.object(self.m, "addon_remote_sha",
                               return_value="d" * 40), \
                mock.patch.object(self.m, "_download_archive",
                                  return_value=_zip({"Ok.toc": "x"})):
            self.app._addon_apply([self.rec("Ok")])
            self.pump()
        self.assertEqual(self.asked, [])
        self.assertIn("Ok", self.m.load_config().get("addons", {}))


if __name__ == "__main__":
    unittest.main()
