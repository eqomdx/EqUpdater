"""Login Doctor: local login checks, safe network checks, and a repair that
touches only login lines -- and EqUpdater no longer writing the website's
address (octowow.st) as the realm into Config.wtf.

Nothing here touches the network: DNS, sockets and HTTP are all injected.
"""

import os
import shutil
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from equpdater import logindoctor as ld  # noqa: E402

GOOD = "1.18.1 (7272)"


def states(checks):
    return {(c.state, c.message) for c in checks}


def has(checks, state, fragment):
    return any(c.state == state and fragment in c.message for c in checks)


class Client:
    """A throwaway client folder with only what the doctor reads."""

    def __init__(self, root=b"set realmlist play.octowow.st\r\n", locale=None,
                 config=None, exe=True):
        self.dir = tempfile.mkdtemp(prefix="equ-doctor-")
        if exe:
            with open(self.path("WoW.exe"), "wb") as f:
                f.truncate(5_000_000)
        if root is not None:
            self.write("realmlist.wtf", root)
        if locale is not None:
            self.write(os.path.join("Data", "enUS", "realmlist.wtf"), locale)
        if config is not None:
            self.write(os.path.join("WTF", "Config.wtf"), config)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def write(self, rel, data: bytes):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "wb") as f:
            f.write(data)

    def read(self, rel):
        with open(self.path(rel), "rb") as f:
            return f.read()

    def checks(self, version=GOOD, running=False):
        return ld.local_checks(self.dir, version, running)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class DoctorCase(unittest.TestCase):
    def client(self, **kw):
        c = Client(**kw)
        self.addCleanup(c.close)
        return c


class TestClient(DoctorCase):
    def test_healthy(self):
        checks = self.client().checks()
        self.assertTrue(all(c.state == ld.PASS for c in checks), checks)
        self.assertIn((ld.PASS, "WoW.exe found"), states(checks))
        self.assertTrue(has(checks, ld.PASS, "Client build looks correct"))

    def test_missing_exe(self):
        checks = self.client(exe=False).checks(version="")
        self.assertTrue(has(checks, ld.FAIL, "WoW.exe not found"))

    def test_wrong_build(self):
        """Another build is a warning: it may be a newer OctoWoW client
        than this EqUpdater knows. The vanilla 1.12.1 build is not it."""
        for other in ("1.12.1 (5875)", "1.18.2 (7300)"):
            with self.subTest(build=other):
                checks = self.client().checks(version=other)
                self.assertTrue(has(checks, ld.WARN, "Unexpected client build"))
                self.assertFalse(any(c.state == ld.FAIL for c in checks))

    def test_unreadable_build(self):
        self.assertTrue(has(self.client().checks(version=""), ld.WARN,
                            "Could not read the client build"))

    def test_tiny_exe_is_not_the_client(self):
        c = self.client()
        with open(c.path("WoW.exe"), "wb") as f:
            f.write(b"MZ")
        self.assertTrue(has(c.checks(), ld.FAIL, "too small"))

    def test_running_game_is_reported(self):
        self.assertTrue(has(self.client().checks(running=True), ld.WARN,
                            "The game is running"))


class TestRealmlist(DoctorCase):
    def test_root_healthy(self):
        checks, host = ld.realmlist_checks(self.client().dir)
        self.assertEqual(host, "play.octowow.st")
        self.assertEqual([c.state for c in checks], [ld.PASS])

    def test_locale_healthy(self):
        c = self.client(locale=b"SET realmList play.octowow.st\n")
        checks, _ = ld.realmlist_checks(c.dir)
        self.assertEqual([c.state for c in checks], [ld.PASS, ld.PASS])
        self.assertIn(os.path.join("Data", "enUS", "realmlist.wtf"),
                      [c.values["file"] for c in checks])

    def test_missing_root(self):
        checks, host = ld.realmlist_checks(self.client(root=None).dir)
        self.assertIsNone(host)
        self.assertTrue(has(checks, ld.FAIL, "is missing"))

    def test_old_host(self):
        checks, _ = ld.realmlist_checks(
            self.client(root=b'set realmlist "octowow.st"\n').dir)
        self.assertTrue(has(checks, ld.FAIL, "old address"))

    def test_unknown_and_private_hosts(self):
        for host in (b"login.example.net", b"10.20.30.40", b"203.0.113.9:3724"):
            with self.subTest(host=host):
                checks, _ = ld.realmlist_checks(
                    self.client(root=b"set realmlist " + host + b"\n").dir)
                self.assertTrue(has(checks, ld.WARN, "non-standard"))
                self.assertTrue(any("stale" in c.message for c in checks))

    def test_alternative_route(self):
        checks, _ = ld.realmlist_checks(
            self.client(root=b"set realmlist normal.octowow.st\n").dir)
        self.assertTrue(has(checks, ld.WARN, "not the normal route"))

    def test_mismatched_realmlists(self):
        c = self.client(locale=b"set realmlist octowow.st\n")
        checks, _ = ld.realmlist_checks(c.dir)
        self.assertTrue(has(checks, ld.WARN, "does not match the root"))

    def test_malformed(self):
        for text in (b"set realmlist\n", b"realmlist play.octowow.st\n",
                     b"set realmlist bad host!\n", b"\n"):
            with self.subTest(text=text):
                checks, _ = ld.realmlist_checks(self.client(root=text).dir)
                self.assertTrue(any(c.state == ld.FAIL for c in checks), checks)

    def test_two_different_realm_lines(self):
        checks, host = ld.realmlist_checks(self.client(
            root=b"set realmlist octowow.st\nset realmlist play.octowow.st\n").dir)
        self.assertTrue(has(checks, ld.WARN, "more than once"))
        self.assertEqual(host, "play.octowow.st")       # the last one wins


class TestConfig(DoctorCase):
    def test_matching_or_absent_realm(self):
        for cfg in (b'SET realmList "play.octowow.st"\r\n', b'SET gxWindow "1"\r\n'):
            with self.subTest(cfg=cfg):
                checks = self.client(config=cfg).checks()
                self.assertTrue(all(c.state == ld.PASS for c in checks), checks)

    def test_obsolete_realm(self):
        checks = self.client(config=b'SET realmList "octowow.st"\n').checks()
        self.assertTrue(has(checks, ld.WARN, "obsolete realmList"))

    def test_conflicting_realm(self):
        checks = self.client(config=b'SET realmList "normal.octowow.st"\n').checks()
        self.assertTrue(has(checks, ld.WARN, "disagrees with realmlist.wtf"))

    def test_private_realm_and_patchlist(self):
        c = self.client(root=b"set realmlist 10.0.0.5\n",
                        config=b'SET realmList "10.0.0.5"\nSET patchList "evil.example"\n')
        checks = c.checks()
        self.assertTrue(any(c.state == ld.WARN and c.values.get("host") == "10.0.0.5"
                            and "it may be stale" in c.message for c in checks))
        self.assertTrue(has(checks, ld.WARN, "patchList points somewhere other"))

    def test_malformed_values(self):
        checks = self.client(config=b'SET realmList ""\nSET patchList "a b"\n').checks()
        self.assertTrue(has(checks, ld.WARN, "malformed realmList"))
        self.assertTrue(has(checks, ld.WARN, "malformed patchList"))

    def test_missing_config_is_fine(self):
        self.assertTrue(has(self.client().checks(), ld.PASS, "No Config.wtf yet"))


class TestRepair(DoctorCase):
    CONFIG = (b'SET gxWindow "1"\r\nSET realmList "octowow.st"\r\n'
              b'SET realmName "Octo PvE"\r\nSET accountName "me"\r\n')

    def broken(self):
        return self.client(root=b"set realmlist octowow.st\r\nset patchlist octowow.st\r\n",
                           locale=b"set realmlist 10.1.2.3\n", config=self.CONFIG)

    def test_plan_names_exactly_the_login_files(self):
        c = self.broken()
        planned = sorted(os.path.relpath(p, c.dir) for p, _t in ld.repair_plan(c.dir))
        self.assertEqual(planned, sorted([
            "realmlist.wtf", os.path.join("Data", "enUS", "realmlist.wtf"),
            os.path.join("WTF", "Config.wtf")]))

    def test_repair_changes_only_login_lines_and_backs_up(self):
        c = self.broken()
        before = {rel: c.read(rel) for rel in (
            "realmlist.wtf", os.path.join("Data", "enUS", "realmlist.wtf"),
            os.path.join("WTF", "Config.wtf"), "WoW.exe")}
        changed = ld.repair(c.dir, running=lambda d: False)
        self.assertEqual(len(changed), 3)
        self.assertEqual(c.read("realmlist.wtf"),
                         b"set realmlist play.octowow.st\r\nset patchlist octowow.st\r\n")
        self.assertEqual(c.read(os.path.join("Data", "enUS", "realmlist.wtf")),
                         b"set realmlist play.octowow.st\n")
        self.assertEqual(c.read(os.path.join("WTF", "Config.wtf")),
                         b'SET gxWindow "1"\r\nSET realmName "Octo PvE"\r\n'
                         b'SET accountName "me"\r\n')
        self.assertEqual(c.read("WoW.exe"), before["WoW.exe"])
        for rel in changed:
            with open(rel + ld.BACKUP_EXT, "rb") as f:
                self.assertEqual(f.read(), before[os.path.relpath(rel, c.dir)])
        # Healthy now, nothing left to repair.
        self.assertEqual(ld.repair_plan(c.dir), [])
        self.assertTrue(all(x.state == ld.PASS for x in c.checks()))

    def test_an_existing_backup_is_kept(self):
        c = self.broken()
        c.write("realmlist.wtf" + ld.BACKUP_EXT, b"the original\n")
        ld.repair(c.dir, running=lambda d: False)
        self.assertEqual(c.read("realmlist.wtf" + ld.BACKUP_EXT), b"the original\n")

    def test_a_missing_root_realmlist_is_created(self):
        c = self.client(root=None)
        ld.repair(c.dir, running=lambda d: False)
        self.assertEqual(c.read("realmlist.wtf"), b"set realmlist play.octowow.st\r\n")
        self.assertFalse(os.path.exists(c.path("realmlist.wtf" + ld.BACKUP_EXT)))

    def test_refused_while_the_game_runs(self):
        c = self.broken()
        with self.assertRaises(ld.GameRunning):
            ld.repair(c.dir, running=lambda d: True)
        self.assertEqual(c.read("realmlist.wtf"),
                         b"set realmlist octowow.st\r\nset patchlist octowow.st\r\n")
        self.assertFalse(os.path.exists(c.path("realmlist.wtf" + ld.BACKUP_EXT)))

    def test_a_matching_config_realm_is_left_alone(self):
        c = self.client(config=b'SET realmList "play.octowow.st"\n')
        self.assertEqual(ld.repair_plan(c.dir), [])

    def test_nothing_outside_the_login_files_is_touched(self):
        c = self.broken()
        for rel in (os.path.join("Interface", "AddOns", "pfUI", "pfUI.toc"),
                    os.path.join("Data", "patch-O.mpq"), "dxgi.dll",
                    os.path.join("WDB", "creaturecache.wdb"),
                    os.path.join("WTF", "Account", "ME", "config-cache.wtf")):
            c.write(rel, b"untouched")
        snapshot = {}
        for base, _dirs, files in os.walk(c.dir):
            for name in files:
                p = os.path.join(base, name)
                snapshot[p] = os.stat(p).st_mtime_ns
        changed = set(ld.repair(c.dir, running=lambda d: False))
        for p, mtime in snapshot.items():
            if p not in changed:
                self.assertEqual(os.stat(p).st_mtime_ns, mtime, p)


class TestNetwork(unittest.TestCase):
    def run_checks(self, resolve=None, connect=None, fetch=None, **kw):
        return ld.network_checks(
            fetch or (lambda url, t: 200),
            resolve=resolve or (lambda h: ["192.0.2.1"]),
            connect=connect or (lambda h, p, t: None), **kw)

    def test_all_reachable(self):
        calls = []
        checks = self.run_checks(connect=lambda h, p, t: calls.append((h, p)))
        self.assertTrue(all(c.state == ld.PASS for c in checks), checks)
        self.assertEqual(calls, [("play.octowow.st", 3724)])
        self.assertEqual({c.values.get("host") for c in checks
                          if "resolves" in c.message},
                         {"play.octowow.st", "octowow.st", "dl.octowow.st"})

    def test_dns_failure_skips_the_login_port(self):
        def resolve(h):
            if h == "play.octowow.st":
                raise socket.gaierror("no")
            return ["192.0.2.1"]
        connect = mock.Mock()
        checks = self.run_checks(resolve=resolve, connect=connect)
        self.assertTrue(has(checks, ld.FAIL, "does not resolve"))
        self.assertTrue(has(checks, ld.WARN, "Login server not tested"))
        connect.assert_not_called()

    def test_dns_timeout_does_not_hang(self):
        start = time.monotonic()
        checks = self.run_checks(resolve=lambda h: time.sleep(2) or ["x"],
                                 dns_timeout=0.2)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertTrue(has(checks, ld.FAIL, "timed out"))

    def test_login_port_timeout_and_refusal_are_only_informational(self):
        """A server under protection may drop probes from a client that
        would still log in: a failed 3724 probe is a warning, never a
        failure, and does not hold back the "no local problem" summary."""
        def timeout(h, p, t):
            raise socket.timeout("slow")

        def refused(h, p, t):
            raise ConnectionRefusedError()
        for connect, fragment in ((timeout, "did not answer"),
                                  (refused, "refused a test connection")):
            with self.subTest(fragment=fragment):
                checks = self.run_checks(connect=connect)
                probe = [c for c in checks if "Login server" in c.message]
                self.assertEqual(len(probe), 1)
                self.assertEqual(probe[0].state, ld.WARN)
                self.assertTrue(probe[0].informational)
                self.assertIn(fragment, probe[0].message)
                self.assertIn("does not mean login will fail", probe[0].message)
                self.assertFalse(any(c.state == ld.FAIL for c in checks))
                self.assertEqual(ld.summary(checks), ld.NO_LOCAL_PROBLEM)

    def test_http_errors(self):
        def fetch(url, t):
            raise OSError("unreachable")
        checks = self.run_checks(fetch=fetch)
        self.assertEqual(sum(has([c], ld.FAIL, "not reachable") for c in checks), 2)

    def test_a_protection_page_counts_as_reachable(self):
        """The app's fetch returns the status of any HTTP answer -- 403 or
        a DDoS-protection page -- and the doctor counts it as reached."""
        checks = self.run_checks(fetch=lambda url, t: 503)
        self.assertFalse(any(c.state == ld.FAIL for c in checks))


class TestSummary(unittest.TestCase):
    def test_no_local_problem_wording(self):
        ok = [ld.Check(ld.PASS, "x", {})]
        text = ld.summary(ok)
        self.assertTrue(text.startswith("No local login problem was found."))
        self.assertIn("server-side or account-specific", text)
        self.assertIn("Priority Sign In may provide a different login route", text)
        self.assertNotIn("banned", text.lower())

    def test_an_informational_warning_keeps_the_summary(self):
        probe = ld.Check(ld.WARN, "probe", {}, "network", informational=True)
        self.assertEqual(ld.summary([ld.Check(ld.PASS, "x", {}), probe]),
                         ld.NO_LOCAL_PROBLEM)

    def test_no_summary_when_something_is_wrong(self):
        for state in (ld.WARN, ld.FAIL):
            self.assertIsNone(ld.summary([ld.Check(ld.PASS, "x", {}),
                                          ld.Check(state, "y", {})]))

    def test_priority_note_does_not_claim_support(self):
        self.assertIn("cannot currently use OctoLauncher's Priority Sign In",
                      ld.PRIORITY_NOTE)
        self.assertIn("may modify client files", ld.PRIORITY_NOTE)


try:
    import tkinter  # noqa: F401
    HAVE_TK = True
except ImportError:
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "the app needs tkinter")
class TestWriteConfigWtf(unittest.TestCase):
    """EqUpdater used to write SET realmList "octowow.st" -- the website's
    address -- into every fresh Config.wtf."""

    def test_no_realm_line_and_no_old_host(self):
        from equpdater import app
        tmp = tempfile.mkdtemp(prefix="equ-cfgwtf-")
        self.addCleanup(shutil.rmtree, tmp, True)
        app.write_config_wtf(tmp, dict(app.TWEAKS_DEFAULTS))
        with open(os.path.join(tmp, "WTF", "Config.wtf"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("realmlist", text.lower())
        self.assertNotIn('"octowow.st"', text.replace('SET patchList "octowow.st"', ""))
        self.assertIn('SET gxWindow "1"', text)     # the rest is still written
        sets = ld.parse_config(text)
        self.assertNotIn("realmlist", sets)
        self.assertEqual(ld.config_checks(tmp, "play.octowow.st")[0].state, ld.PASS)

    def test_written_on_every_platform(self):
        """It used to ask Windows for the display mode unconditionally, so
        on Linux a fresh Config.wtf raised before it was written."""
        from equpdater import app
        for windows in (False, True):
            with self.subTest(windows=windows), \
                    mock.patch.object(app.platforms, "WINDOWS", windows), \
                    mock.patch.object(app, "_query_display_info",
                                      side_effect=AttributeError("windll")):
                tmp = tempfile.mkdtemp(prefix="equ-cfgwtf-")
                self.addCleanup(shutil.rmtree, tmp, True)
                app.write_config_wtf(tmp, dict(app.TWEAKS_DEFAULTS))
                with open(os.path.join(tmp, "WTF", "Config.wtf")) as f:
                    self.assertIn('SET gxResolution "1920x1080"', f.read())


if __name__ == "__main__":
    unittest.main()
