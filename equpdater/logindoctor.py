"""Login Doctor: what on this computer could stop the game logging in.

It looks only at local things EqUpdater can know and safely fix -- the
client, its realmlist files, the login settings in Config.wtf -- and at
whether this computer can reach OctoWoW at all. It never tries to log in,
never reads accounts, launcher sign-ins, tokens or cookies, and never
claims to know why a server refused someone: a healthy result says so and
points at the server or the account instead.

The login-port probe (TCP to 3724) is informational: a server under
protection may drop probes from a client that would still log in, so a
failed probe is a warning and never a local-login failure.

The checks are plain functions over a client folder and injectable network
calls, so they are tested without a display or a network. The window is in
app.py (EqUpdaterApp._open_login_doctor).

**The login route.** The client reads its login server from realmlist.wtf
(``set realmlist <host>``): the root one, and a Data/<locale>/ copy where a
client has one. The normal route is play.octowow.st. Older setups -- and
EqUpdater itself before 2.1 -- used octowow.st, the website's address. The
client also saves the value it used back into Config.wtf as
``SET realmList``, so a matching line there is normal and a disagreeing one
is a leftover; EqUpdater no longer writes that line itself.

**Repair** changes only login lines: the ``set realmlist`` line of each
realmlist file, and a stale ``SET realmList`` line in Config.wtf. Every
other line, file and setting is left byte for byte. Each changed file is
backed up first as <file>.octobak; an existing backup is never replaced,
so the first one -- the original -- is what stays.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import os
import re
import shutil
import socket
from dataclasses import dataclass, field

from .i18n import N_

#: The login server the client should use.
LOGIN_HOST = "play.octowow.st"
#: OctoWoW's own names that are not the normal login route: the website
#: (the old realmlist value) and the alternative login name.
OLD_HOSTS = ("octowow.st", "www.octowow.st")
ALT_ROUTES = ("normal.octowow.st",)
#: The port the 1.12 client logs in on.
LOGIN_PORT = 3724
#: What OctoWoW's client reports: 1.18.1, build 7272 (read from the
#: client EqUpdater syncs). Any other build is a warning, not a failure: a
#: newer client released after this EqUpdater is still the right one.
EXPECTED_VERSION = "1.18.1"
EXPECTED_BUILD = "7272"
#: The exact line repair writes; the client reads it case-insensitively.
REALMLIST_LINE = f"set realmlist {LOGIN_HOST}"
BACKUP_EXT = ".octobak"

#: Hosts whose names must resolve, and the HTTPS endpoints EqUpdater uses.
DNS_HOSTS = (LOGIN_HOST, "octowow.st", "dl.octowow.st")
HTTPS_CHECKS = (
    ("https://octowow.st/", N_("octowow.st website")),
    ("https://dl.octowow.st/download/client.torrent", N_("Client download server")),
)
DNS_TIMEOUT = 5.0
TCP_TIMEOUT = 5.0
HTTP_TIMEOUT = 8.0

PASS, WARN, FAIL = "pass", "warn", "fail"

_LOCALE_DIR = re.compile(r"^[a-z]{2}[A-Z]{2}$")
_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?$")
_REALMLIST = re.compile(r'^\s*set\s+realmlist\s+"?([^"\s]*)"?\s*$', re.I)
_CONFIG_SET = re.compile(r'^\s*SET\s+(\w+)\s+"?(.*?)"?\s*$', re.I)


@dataclass
class Check:
    """One line of the result: a state, an English message (translated
    where it is shown) and the values it is filled in with."""
    state: str
    message: str
    values: dict = field(default_factory=dict)
    group: str = "client"
    #: A signal worth showing that does not by itself mean something on
    #: this computer is wrong (the login-port probe); it never holds back
    #: the "no local login problem" summary.
    informational: bool = False


# ──────────────────────────────────────────────────────────────────────────────
#  Reading
# ──────────────────────────────────────────────────────────────────────────────

def realmlist_files(client_dir: str) -> list:
    """The realmlist files the client may read: the root one (always, even
    when missing) and Data/<locale>/realmlist.wtf where one exists."""
    paths = [os.path.join(client_dir, "realmlist.wtf")]
    data = os.path.join(client_dir, "Data")
    try:
        names = sorted(os.listdir(data))
    except OSError:
        names = []
    for name in names:
        candidate = os.path.join(data, name, "realmlist.wtf")
        if _LOCALE_DIR.match(name) and os.path.isfile(candidate):
            paths.append(candidate)
    return paths


def config_wtf(client_dir: str) -> str:
    return os.path.join(client_dir, "WTF", "Config.wtf")


def _read(path: str) -> str | None:
    """A text file's contents, byte for byte (latin-1), or None if absent."""
    try:
        with open(path, "rb") as f:
            return f.read().decode("latin-1")
    except FileNotFoundError:
        return None


def parse_realmlist(text: str) -> tuple:
    """(hosts, malformed): every ``set realmlist`` value, and the lines
    that mention realmlist but are not a usable ``set realmlist <host>``."""
    hosts, malformed = [], []
    for line in text.splitlines():
        if "realmlist" not in line.lower() or line.strip().startswith(("#", "--")):
            continue
        m = _REALMLIST.match(line)
        if m and _HOST.match(m.group(1)):
            hosts.append(m.group(1))
        else:
            malformed.append(line.strip())
    return hosts, malformed


def parse_config(text: str) -> dict:
    """``SET name "value"`` lines of Config.wtf, by lower-case name; the
    last one wins, as in the client."""
    out = {}
    for line in text.splitlines():
        m = _CONFIG_SET.match(line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def host_kind(value: str) -> str:
    """"ok", "old", "alt", "ip", "unknown" or "malformed" for a realm host
    (a port, if given, is ignored)."""
    if not value or not _HOST.match(value):
        return "malformed"
    host = value.rsplit(":", 1)[0].lower() if value.count(":") == 1 else value.lower()
    if host == LOGIN_HOST:
        return "ok"
    if host in OLD_HOSTS:
        return "old"
    if host in ALT_ROUTES:
        return "alt"
    try:
        ipaddress.ip_address(host)
        return "ip"
    except ValueError:
        return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
#  Local checks
# ──────────────────────────────────────────────────────────────────────────────

def _host_check(kind: str, where: str, host: str, group: str) -> Check:
    v = {"file": where, "host": host, "expected": LOGIN_HOST}
    if kind == "ok":
        return Check(PASS, N_("{file} uses {host}"), v, group)
    if kind == "old":
        return Check(FAIL, N_("{file} uses the old address {host}"), v, group)
    if kind == "alt":
        return Check(WARN, N_("{file} uses {host}, not the normal route {expected}"),
                     v, group)
    if kind in ("ip", "unknown"):
        return Check(WARN, N_("{file} uses a non-standard address ({host}); it may "
                              "be stale, for example left behind by an interrupted "
                              "official launcher session"), v, group)
    return Check(FAIL, N_("{file} has a malformed realm address ({host})"), v, group)


def client_checks(client_dir: str, version: str, running: bool) -> list:
    """WoW.exe is there and is the expected 1.18.1 (7272) client.
    ``version`` is app.get_client_version's "1.18.1 (7272)" or ""."""
    exe = os.path.join(client_dir, "WoW.exe")
    if not os.path.isfile(exe):
        return [Check(FAIL, N_("WoW.exe not found in the game folder"), {})]
    out = [Check(PASS, N_("WoW.exe found"), {})]
    expected = f"{EXPECTED_VERSION} ({EXPECTED_BUILD})"
    if os.path.getsize(exe) < 1_000_000:
        out.append(Check(FAIL, N_("WoW.exe is too small to be the game client"), {}))
    elif not version:
        out.append(Check(WARN, N_("Could not read the client build from WoW.exe"), {}))
    elif version == expected:
        out.append(Check(PASS, N_("Client build looks correct ({version})"),
                         {"version": version}))
    else:
        out.append(Check(WARN, N_("Unexpected client build {version} (OctoWoW uses "
                                  "{expected})"),
                         {"version": version, "expected": expected}))
    if running:
        out.append(Check(WARN, N_("The game is running: repairs are disabled "
                                  "until it is closed"), {}))
    return out


def realmlist_checks(client_dir: str) -> tuple:
    """(checks, effective host or None). The root realmlist is the one the
    1.12 client reads; a locale copy is compared against it."""
    out, root_host = [], None
    for path in realmlist_files(client_dir):
        where = os.path.relpath(path, client_dir)
        text = _read(path)
        if text is None:
            out.append(Check(FAIL, N_("{file} is missing"), {"file": where}, "realmlist"))
            continue
        hosts, malformed = parse_realmlist(text)
        for line in malformed:
            out.append(Check(FAIL, N_("{file} has a malformed line: {line}"),
                             {"file": where, "line": line[:80]}, "realmlist"))
        if not hosts:
            if not malformed:
                out.append(Check(FAIL, N_("{file} has no realmlist line"),
                                 {"file": where}, "realmlist"))
            continue
        if len({h.lower() for h in hosts}) > 1:
            out.append(Check(WARN, N_("{file} sets the realm more than once "
                                      "({hosts})"),
                             {"file": where, "hosts": ", ".join(hosts)}, "realmlist"))
        host = hosts[-1]
        out.append(_host_check(host_kind(host), where, host, "realmlist"))
        if path == os.path.join(client_dir, "realmlist.wtf"):
            root_host = host
        elif root_host and host.lower() != root_host.lower():
            out.append(Check(WARN, N_("{file} ({host}) does not match the root "
                                      "realmlist ({root})"),
                             {"file": where, "host": host, "root": root_host},
                             "realmlist"))
    return out, root_host


def config_checks(client_dir: str, realm_host: str | None) -> list:
    """The login settings in Config.wtf, read only."""
    text = _read(config_wtf(client_dir))
    where = os.path.join("WTF", "Config.wtf")
    if text is None:
        return [Check(PASS, N_("No Config.wtf yet; the game creates it"),
                      {}, "config")]
    sets = parse_config(text)
    out = []
    realm = sets.get("realmlist")
    if realm is None:
        out.append(Check(PASS, N_("Config.wtf has no realmList of its own"),
                         {}, "config"))
    else:
        kind = host_kind(realm)
        if kind == "old":
            out.append(Check(WARN, N_("Config.wtf contains an obsolete realmList "
                                      "({host})"), {"host": realm}, "config"))
        elif kind == "malformed":
            out.append(Check(WARN, N_("Config.wtf has a malformed realmList "
                                      "({host})"), {"host": realm}, "config"))
        elif realm_host and realm.lower() != realm_host.lower():
            out.append(Check(WARN, N_("Config.wtf realmList ({host}) disagrees with "
                                      "realmlist.wtf ({root})"),
                             {"host": realm, "root": realm_host}, "config"))
        elif kind in ("ip", "unknown"):
            out.append(Check(WARN, N_("Config.wtf realmList uses a non-standard "
                                      "address ({host}); it may be stale"),
                             {"host": realm}, "config"))
        else:
            out.append(Check(PASS, N_("Config.wtf realmList matches ({host})"),
                             {"host": realm}, "config"))
    patch = sets.get("patchlist")
    if patch is not None:
        kind = host_kind(patch)
        if kind == "malformed":
            out.append(Check(WARN, N_("Config.wtf has a malformed patchList "
                                      "({host})"), {"host": patch}, "config"))
        elif kind in ("ip", "unknown"):
            out.append(Check(WARN, N_("Config.wtf patchList points somewhere other "
                                      "than OctoWoW ({host})"), {"host": patch},
                             "config"))
    return out


def local_checks(client_dir: str, version: str, running: bool) -> list:
    out = client_checks(client_dir, version, running)
    realm, root_host = realmlist_checks(client_dir)
    return out + realm + config_checks(client_dir, root_host)


# ──────────────────────────────────────────────────────────────────────────────
#  Network checks
# ──────────────────────────────────────────────────────────────────────────────

def _resolve(host: str) -> list:
    return sorted({a[4][0] for a in socket.getaddrinfo(host, None,
                                                       type=socket.SOCK_STREAM)})


def _connect(host: str, port: int, timeout: float) -> None:
    socket.create_connection((host, port), timeout=timeout).close()


def network_checks(fetch, resolve=_resolve, connect=_connect,
                   dns_timeout: float = DNS_TIMEOUT,
                   tcp_timeout: float = TCP_TIMEOUT,
                   http_timeout: float = HTTP_TIMEOUT) -> list:
    """Name lookups, a TCP connect to the login port, and one request to
    each HTTPS endpoint. Nothing is logged into. ``fetch(url, timeout)``
    returns the HTTP status (any answer, a DDoS-protection page included,
    means the host was reached) or raises. Bounded by the timeouts; meant
    for a worker thread."""
    out = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(DNS_HOSTS))
    try:
        futures = {h: pool.submit(resolve, h) for h in DNS_HOSTS}
        resolved = {}
        for host, fut in futures.items():
            try:
                addrs = fut.result(timeout=dns_timeout)
                if not addrs:
                    raise OSError("no addresses")
                resolved[host] = addrs
                out.append(Check(PASS, N_("{host} resolves"), {"host": host}, "network"))
            except concurrent.futures.TimeoutError:
                out.append(Check(FAIL, N_("{host} did not resolve (timed out)"),
                                 {"host": host}, "network"))
            except Exception:
                out.append(Check(FAIL, N_("{host} does not resolve"),
                                 {"host": host}, "network"))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    v = {"host": LOGIN_HOST, "port": LOGIN_PORT}
    if LOGIN_HOST in resolved:
        try:
            connect(LOGIN_HOST, LOGIN_PORT, tcp_timeout)
            out.append(Check(PASS, N_("Login server reachable ({host}:{port})"),
                             v, "network"))
        except socket.timeout:
            out.append(Check(WARN, N_("Login server did not answer a test connection "
                                      "({host}:{port}, timed out). This alone does not "
                                      "mean login will fail: the server may ignore "
                                      "probes or be busy"), v, "network", True))
        except OSError:
            out.append(Check(WARN, N_("Login server refused a test connection "
                                      "({host}:{port}). This alone does not mean "
                                      "login will fail: the server may ignore probes "
                                      "or be busy"), v, "network", True))
    else:
        out.append(Check(WARN, N_("Login server not tested: {host} does not "
                                  "resolve"), v, "network", True))

    for url, label in HTTPS_CHECKS:
        try:
            fetch(url, http_timeout)
            out.append(Check(PASS, N_("{name} reachable"), {"name": label}, "network"))
        except Exception:
            out.append(Check(FAIL, N_("{name} not reachable"), {"name": label},
                             "network"))
    return out


def summary(checks: list) -> str | None:
    """The closing message when nothing local is wrong, else None.
    Informational signals (the login-port probe) do not count."""
    if any(c.state != PASS and not c.informational for c in checks):
        return None
    return NO_LOCAL_PROBLEM


NO_LOCAL_PROBLEM = N_(
    "No local login problem was found.\n\n"
    "The problem may be server-side or account-specific. If OctoWoW is "
    "currently under attack or congestion, the official launcher's Priority "
    "Sign In may provide a different login route.")

PRIORITY_NOTE = N_(
    "If login stops at \u201cAuthenticating\u201d:\n"
    "\u2022 Turn off any VPN or proxy: OctoWoW's login can hang behind one.\n"
    "\u2022 Sign in once with Priority Sign In in the official OctoLauncher, "
    "then try PLAY in EqUpdater again.\n\n"
    "EqUpdater cannot currently use OctoLauncher's Priority Sign In directly. "
    "Warning: the official launcher may modify client files that EqUpdater "
    "manages.")


# ──────────────────────────────────────────────────────────────────────────────
#  Repair
# ──────────────────────────────────────────────────────────────────────────────

def _fixed_realmlist(text: str | None) -> str:
    """The realmlist with its realm line(s) set to REALMLIST_LINE and every
    other line kept; created when missing."""
    if text is None:
        return REALMLIST_LINE + "\r\n"
    newline = "\r\n" if "\r\n" in text else "\n"
    out, done = [], False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if "realmlist" in body.lower() and not body.strip().startswith(("#", "--")):
            if not done:
                out.append(REALMLIST_LINE + (line[len(body):] or newline))
                done = True
            continue                      # a second (conflicting) realm line goes
        out.append(line)
    if not done:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += newline
        out.append(REALMLIST_LINE + newline)
    return "".join(out)


def _fixed_config(text: str, realm_host: str) -> str:
    """Config.wtf without a SET realmList that disagrees with ``realm_host``;
    every other line unchanged."""
    out = []
    for line in text.splitlines(keepends=True):
        m = _CONFIG_SET.match(line.rstrip("\r\n"))
        if m and m.group(1).lower() == "realmlist" \
                and m.group(2).lower() != realm_host.lower():
            continue
        out.append(line)
    return "".join(out)


def repair_plan(client_dir: str) -> list:
    """[(path, new text)] for every file repair would change; empty when
    the login configuration is already right."""
    plan = []
    for path in realmlist_files(client_dir):
        text = _read(path)
        fixed = _fixed_realmlist(text)
        if fixed != text:
            plan.append((path, fixed))
    cfg = config_wtf(client_dir)
    text = _read(cfg)
    if text is not None:
        fixed = _fixed_config(text, LOGIN_HOST)
        if fixed != text:
            plan.append((cfg, fixed))
    return plan


class GameRunning(RuntimeError):
    """Repair refused: the game is running and would rewrite these files."""


def backup(path: str) -> str | None:
    """Copy ``path`` to <path>.octobak unless a backup is already there;
    the first backup, the original, is never replaced. None if there was
    nothing to back up."""
    if not os.path.exists(path):
        return None
    dest = path + BACKUP_EXT
    if not os.path.exists(dest):
        shutil.copy2(path, dest)
    return dest


def repair(client_dir: str, running) -> list:
    """Apply repair_plan. ``running(client_dir)`` is asked first and a
    running game refuses the whole repair. Returns the changed paths."""
    if running(client_dir):
        raise GameRunning(client_dir)
    changed = []
    for path, text in repair_plan(client_dir):
        backup(path)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(text.encode("latin-1"))
        os.replace(tmp, path)
        changed.append(path)
    return changed
