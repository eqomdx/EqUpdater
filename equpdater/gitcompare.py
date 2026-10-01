"""Which of two commits came first.

**Why a whole module for this.** The updater this replaces decided an addon
was out of date with

    remote_sha != installed_sha

A commit sha is an identifier, not a position. Two different shas can mean the
remote moved on, or that the *local* checkout is the newer one, or that it
came off another branch, or that history was rebased under it, or that the
user deliberately installed a different fork. One of those five is an update.
The old logic called all five "out of date" and offered one button, which
overwrote the other four.

So ask the host instead. Every git host this updater talks to can answer
"does commit A contain commit B", which is the actual question. When it
cannot be asked -- no network, an unsupported host, a private repository, a
commit that no longer exists after a force-push -- the answer is UNKNOWN and
nothing is overwritten on the strength of it.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum


class Ancestry(Enum):
    """How a remote commit relates to the installed one."""

    IDENTICAL = "identical"          # same commit
    REMOTE_AHEAD = "remote ahead"    # installed is an ancestor: a real update
    LOCAL_AHEAD = "local ahead"      # remote is an ancestor of installed
    DIVERGED = "diverged"            # neither contains the other
    UNKNOWN = "unknown"              # could not be established

    def __str__(self) -> str:
        return self.value


# ──────────────────────────────────────────────────────────────────────────────
#  Git hosts
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GitHost:
    """A git host EqUpdater can read repositories from.

    ``prefix`` is the path a forge is mounted under, when it does not own
    the whole host: OctoWoW's Gitea lives at ``octowow.st/git/``, so its
    repositories are ``/git/<owner>/<repo>`` and its API ``/git/api/v1``.
    Everything that builds or reads a repository URL goes through this, so a
    prefixed forge needs one entry below and no special cases elsewhere."""

    name: str                       # what people call it: "OctoWoW Git"
    host: str                       # "octowow.st"
    kind: str                       # "github" | "gitlab" | "gitea"
    prefix: str = ""                # "git" -> https://octowow.st/git/...
    #: Hosts the repository archives (addon zips) are served from, besides
    #: the host itself. GitHub hands them to its CDN.
    archive_hosts: frozenset = frozenset()

    @property
    def root(self) -> str:
        """Where repositories start: https://<host>[/<prefix>]."""
        return f"https://{self.host}" + (f"/{self.prefix}" if self.prefix else "")

    @property
    def label(self) -> str:
        """The host as people type it: "github.com", "octowow.st/git"."""
        return self.host + (f"/{self.prefix}" if self.prefix else "")

    @property
    def api(self) -> str:
        if self.kind == "github":
            return "https://api.github.com"
        if self.kind == "gitlab":
            return f"{self.root}/api/v4"
        return f"{self.root}/api/v1"

    @property
    def downloads_from(self) -> frozenset:
        return frozenset({self.host}) | self.archive_hosts


#: Every host EqUpdater reads addon sources from. Adding a Gitea (or GitLab)
#: instance, prefixed or not, is one line here.
GIT_HOSTS = (
    GitHost("GitHub", "github.com", "github",
            archive_hosts=frozenset({"codeload.github.com"})),
    GitHost("GitLab", "gitlab.com", "gitlab"),
    GitHost("Gitea", "gitea.com", "gitea"),
    GitHost("Codeberg", "codeberg.org", "gitea"),
    GitHost("OctoWoW Git", "octowow.st", "gitea", prefix="git"),
)


@dataclass(frozen=True)
class RepoRef:
    """A repository: where it lives and what it is called. ``forge`` is None
    for a host EqUpdater does not know -- such a URL can still be compared
    with another, but nothing is fetched from it."""

    host: str
    owner: str
    repo: str
    forge: GitHost | None = None

    @property
    def url(self) -> str:
        root = self.forge.root if self.forge else f"https://{self.host}"
        return f"{root}/{self.owner}/{self.repo}"


def _host_of(hostname: str) -> str:
    host = (hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def repo_ref(git_url: str, hosts=GIT_HOSTS) -> RepoRef | None:
    """The repository a URL names, or None when it does not name one.

    Accepts http(s), a trailing ``.git`` and a trailing slash. On a known
    host the path must be exactly ``[<prefix>/]<owner>/<repo>``: a page
    inside a repository (``/tree/main``) is not the repository, and on a
    prefixed host a path outside the prefix is not a repository at all."""
    if not git_url:
        return None
    try:
        parts = urllib.parse.urlsplit(git_url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.query or parts.fragment:
        return None
    host = _host_of(parts.hostname)
    segs = [s for s in parts.path.split("/") if s]
    if not host or not segs:
        return None
    if segs[-1].lower().endswith(".git"):
        segs[-1] = segs[-1][:-4]
    split = _split(host, segs, hosts)
    if split is not None:
        forge, owner, repo, rest = split
        return RepoRef(host, owner, repo, forge) if not rest else None
    # An unknown host keeps the plain /<owner>/<repo> reading, for comparing.
    if any(f.host == host for f in hosts) or len(segs) != 2 or not all(segs):
        return None
    return RepoRef(host, segs[0], segs[1], None)


def _split(host, segs, hosts):
    for forge in hosts:
        if forge.host != host:
            continue
        lead = [s for s in forge.prefix.split("/") if s]
        if [s.lower() for s in segs[:len(lead)]] != [s.lower() for s in lead]:
            continue
        rest = segs[len(lead):]
        if len(rest) >= 2 and rest[0] and rest[1]:
            repo = rest[1][:-4] if rest[1].lower().endswith(".git") else rest[1]
            return forge, rest[0], repo, rest[2:]
    return None


def split_repo_url(url: str, hosts=GIT_HOSTS):
    """(forge, owner, repo, rest) for a URL on a known host that goes on
    past the repository -- a release download, say -- or None. ``rest`` is
    the path after ``<owner>/<repo>``, as a list of segments."""
    try:
        parts = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme != "https":
        return None
    segs = [s for s in parts.path.split("/") if s]
    return _split(_host_of(parts.hostname), segs, hosts)


def forge_named(label: str, hosts=GIT_HOSTS):
    """The host whose label ("octowow.st/git") this is, or None."""
    return next((h for h in hosts if h.label == label), None)


def parse_repo(git_url: str):
    """(host, owner, repo) from a repository URL, or None when it is not one."""
    ref = repo_ref(git_url)
    return (ref.host, ref.owner, ref.repo) if ref else None


def same_repo(a: str, b: str) -> bool:
    """Whether two URLs name the same repository.

    Host, owner and repository name compared case-insensitively, with the
    `.git` suffix and trailing slashes ignored -- the same repo is written a
    dozen ways and a spurious "source changed" warning trains people to click
    through real ones."""
    pa, pb = parse_repo(a or ""), parse_repo(b or "")
    if not pa or not pb:
        return (a or "").strip().rstrip("/").lower() == (b or "").strip().rstrip("/").lower()
    return tuple(s.lower() for s in pa) == tuple(s.lower() for s in pb)


# ──────────────────────────────────────────────────────────────────────────────
#  Host APIs
# ──────────────────────────────────────────────────────────────────────────────

def compare_urls(git_url: str, base: str, head: str):
    """(forward_url, reverse_url, reader) for a repository, or None when its
    host is not one this module can ask -- which answers UNKNOWN and so
    protects the files rather than risking them.

    Two URLs because the generic answer is inferred from asking twice: how
    many commits does head have that base does not, and then the same
    question the other way round. GitHub answers outright in one call and the
    reader below uses that when it is there, but the two-call form works on
    every Gitea and GitLab as well, which is what keeps Codeberg addons
    honest."""
    ref = repo_ref(git_url)
    if ref is None or ref.forge is None:
        return None
    forge = ref.forge
    owner_q = urllib.parse.quote(ref.owner, safe="")
    repo_q = urllib.parse.quote(ref.repo, safe="")

    if forge.kind == "github":
        base_url = f"{forge.api}/repos/{owner_q}/{repo_q}/compare"
        return (f"{base_url}/{base}...{head}",
                f"{base_url}/{head}...{base}",
                _read_github)
    if forge.kind == "gitea":
        base_url = f"{forge.api}/repos/{owner_q}/{repo_q}/compare"
        return (f"{base_url}/{base}...{head}",
                f"{base_url}/{head}...{base}",
                _read_gitea)
    if forge.kind == "gitlab":
        proj = urllib.parse.quote(f"{ref.owner}/{ref.repo}", safe="")
        base_url = f"{forge.api}/projects/{proj}/repository/compare"
        return (f"{base_url}?from={base}&to={head}",
                f"{base_url}?from={head}&to={base}",
                _read_gitlab)
    return None


def _read_github(payload: dict):
    """(status, commits_ahead). GitHub states the relationship outright."""
    status = (payload or {}).get("status")
    return status, (payload or {}).get("ahead_by")


def _read_gitea(payload: dict):
    """Gitea's compare returns the commits head has that base does not.

    A response carrying neither field is not a compare response -- an error
    body, a redirect to a login page, a truncated read -- and must answer
    None rather than zero. Zero would read as "no commits either way", which
    is the word for identical, and calling two different commits identical is
    how a stale addon silently stops updating."""
    data = payload if isinstance(payload, dict) else {}
    if "total_commits" in data:
        return None, data.get("total_commits")
    if "commits" in data:
        return None, len(data.get("commits") or [])
    return None, None


def _read_gitlab(payload: dict):
    data = payload if isinstance(payload, dict) else {}
    if "commits" not in data:
        return None, None
    return None, len(data.get("commits") or [])


def _default_fetch(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # nosec - callers inject a hardened opener
        return json.load(r)


def ancestry(git_url: str, installed_sha: str, remote_sha: str,
             fetch=None, timeout: int = 10) -> Ancestry:
    """Where `remote_sha` sits relative to `installed_sha`.

    `fetch(url, timeout) -> dict` is injected so the app can pass its own
    certificate-pinned, host-allowlisted opener and the tests can pass a table
    of canned answers. Any failure anywhere in here answers UNKNOWN: this
    function's job is to authorise an overwrite, so it fails towards not
    authorising one."""
    if not installed_sha or not remote_sha:
        return Ancestry.UNKNOWN
    if installed_sha == remote_sha:
        return Ancestry.IDENTICAL

    urls = compare_urls(git_url, installed_sha, remote_sha)
    if urls is None:
        return Ancestry.UNKNOWN

    forward_url, reverse_url, reader = urls
    fetch = fetch or _default_fetch

    try:
        status, ahead = reader(fetch(forward_url, timeout))
    except Exception:
        return Ancestry.UNKNOWN

    # GitHub says it plainly; trust that and skip the second call.
    if status:
        return {"identical": Ancestry.IDENTICAL,
                "ahead": Ancestry.REMOTE_AHEAD,
                "behind": Ancestry.LOCAL_AHEAD,
                "diverged": Ancestry.DIVERGED}.get(status, Ancestry.UNKNOWN)

    if ahead is None:
        return Ancestry.UNKNOWN

    try:
        _, behind = reader(fetch(reverse_url, timeout))
    except Exception:
        return Ancestry.UNKNOWN
    if behind is None:
        return Ancestry.UNKNOWN

    if ahead == 0 and behind == 0:
        return Ancestry.IDENTICAL
    if ahead > 0 and behind == 0:
        return Ancestry.REMOTE_AHEAD
    if ahead == 0 and behind > 0:
        return Ancestry.LOCAL_AHEAD
    return Ancestry.DIVERGED


def short(sha: str, n: int = 7) -> str:
    """A sha trimmed for display. Empty string in, empty string out."""
    return (sha or "")[:n]
