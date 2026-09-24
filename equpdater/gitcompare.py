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
import re
import urllib.parse
import urllib.request
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
#  URL parsing
# ──────────────────────────────────────────────────────────────────────────────

_GIT_URL = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def parse_repo(git_url: str):
    """(host, owner, repo) from a repository URL, or None when it is not one."""
    if not git_url:
        return None
    m = _GIT_URL.match(git_url.strip())
    if not m:
        return None
    host = m.group("host").lower()
    if host.startswith("www."):
        host = host[4:]
    return host, m.group("owner"), m.group("repo")


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

#: Hosts whose compare endpoint this module knows how to read. A host missing
#: from here is not an error, it simply answers UNKNOWN -- which protects the
#: files rather than risking them.
GITHUB_HOSTS = {"github.com"}
GITEA_HOSTS = {"codeberg.org", "gitea.com"}
GITLAB_HOSTS = {"gitlab.com"}


def _compare_urls(host: str, owner: str, repo: str, base: str, head: str):
    """(forward_url, reverse_url, reader) for a host, or None if unsupported.

    Two URLs because the generic answer is inferred from asking twice: how
    many commits does head have that base does not, and then the same
    question the other way round. GitHub answers outright in one call and the
    reader below uses that when it is there, but the two-call form works on
    every Gitea and GitLab as well, which is what keeps Codeberg addons
    honest."""
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")

    if host in GITHUB_HOSTS:
        base_url = f"https://api.github.com/repos/{owner_q}/{repo_q}/compare"
        return (f"{base_url}/{base}...{head}",
                f"{base_url}/{head}...{base}",
                _read_github)
    if host in GITEA_HOSTS:
        base_url = f"https://{host}/api/v1/repos/{owner_q}/{repo_q}/compare"
        return (f"{base_url}/{base}...{head}",
                f"{base_url}/{head}...{base}",
                _read_gitea)
    if host in GITLAB_HOSTS:
        proj = urllib.parse.quote(f"{owner}/{repo}", safe="")
        base_url = f"https://gitlab.com/api/v4/projects/{proj}/repository/compare"
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

    parts = parse_repo(git_url)
    if not parts:
        return Ancestry.UNKNOWN
    urls = _compare_urls(*parts, installed_sha, remote_sha)
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
