"""Texture packs: where a patch MPQ came from, and what that source says now.

A patch MPQ carries no version. The only comparison available is between
bytes: the file on disk, the file EqUpdater recorded, and the file the source
publishes today. That is enough to tell "untouched and behind its source"
from "edited" and from "somebody else's pack" -- but only if EqUpdater knows
which source the file belongs to.

For a pack EqUpdater installed, it knows. For one the user dropped into Data
by hand it does not, and guessing from the file name is the addon bug again:
a pack called patch-O.mpq is not necessarily Octo Raid Visuals. So the user
says where it came from -- *links* it -- and from then on it can be checked.

Linking changes no file. It records the source and a fingerprint of the pack
as it is. If those bytes are exactly what the source publishes, the pack is
tracked like one EqUpdater installed. If they are not, it is held as
"differs from source" until the user explicitly replaces it: a different
build of the same pack could be older, newer, or hand-edited, and nothing in
an MPQ says which.

Everything here is pure -- no network, no disk, no Tk -- so the judgement is
tested directly. The app resolves sources and hashes files, then asks.
"""

from __future__ import annotations

import fnmatch
from collections import namedtuple
from urllib.parse import unquote, urlsplit

from . import branding

#: Hosts a texture-pack source may live on. The same set the downloader is
#: allowed to fetch binaries from; a source that could be linked but never
#: downloaded would be a trap.
RELEASE_HOSTS = {"github.com": "github_release",
                 "codeberg.org": "codeberg_release"}
DIRECT_HOSTS = ("octowow.st", "dl.octowow.st")


#: What a source says right now. `sha` is the published SHA-256 when the
#: source publishes one. `marker` identifies a release asset (id plus upload
#: time) for sources that publish no checksum; it can tell "a new file was
#: published" but not "these are the same bytes". `url` is where to fetch it.
Remote = namedtuple("Remote", "sha marker url")


# ──────────────────────────────────────────────────────────────────────────────
#  Sources
# ──────────────────────────────────────────────────────────────────────────────

def parse_source(text: str) -> dict:
    """Turn what the user typed into a source record, or raise ValueError
    with a sentence they can act on.

    Accepted:
      https://github.com/<owner>/<repo>            latest release, its .mpq
      https://github.com/<owner>/<repo>/releases   (same)
      https://github.com/<o>/<r>/releases/download/<tag>/<file>.mpq
                                                   latest release, that file
      the same three shapes on codeberg.org
      https://dl.octowow.st/.../<file>.mpq         direct, with a .sha256
    """
    url = (text or "").strip()
    if not url:
        raise ValueError("Paste a link to where this pack comes from.")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("The link must start with https://")
    host = (parts.hostname or "").lower()
    path = [p for p in parts.path.split("/") if p]

    if host in RELEASE_HOSTS:
        if len(path) < 2:
            raise ValueError("Link the repository, e.g. "
                             "https://%s/owner/repo" % host)
        owner, repo = path[0], path[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        asset = None
        if len(path) >= 6 and path[2] == "releases" and path[3] == "download":
            asset = unquote(path[-1])
            if not asset.lower().endswith(".mpq"):
                raise ValueError("That download is not an .mpq file.")
        elif len(path) > 2 and path[2] != "releases":
            raise ValueError("Link the repository or one of its release "
                             "downloads, not a page inside it.")
        return {"kind": RELEASE_HOSTS[host], "owner": owner, "repo": repo,
                "asset": asset}

    if host in DIRECT_HOSTS:
        if not parts.path.lower().endswith(".mpq"):
            raise ValueError("A direct link must end in .mpq")
        return {"kind": "url", "url": url}

    raise ValueError("Texture packs can be linked to a GitHub or Codeberg "
                     "repository, or to dl.octowow.st.")


def catalogue_source(filename: str) -> dict:
    """A pack from EqUpdater's own list, referenced by file so a moved
    download URL in a later release does not strand the link."""
    return {"kind": "catalogue", "file": filename}


def source_of(record: dict | None, filename: str) -> dict | None:
    """The source a record tracks. Records written before linking existed
    carry only a URL and were always installed from the catalogue."""
    if not record or not record.get("managed"):
        return None
    if record.get("source"):
        return record["source"]
    return catalogue_source(filename)


def describe_source(src: dict | None) -> str:
    if not src:
        return "not linked"
    kind = src.get("kind")
    if kind == "catalogue":
        return "%s list (%s)" % (branding.APP_NAME, src.get("file"))
    if kind in ("github_release", "codeberg_release"):
        host = "github.com" if kind == "github_release" else "codeberg.org"
        where = "%s/%s/%s" % (host, src.get("owner"), src.get("repo"))
        return where + (" · %s" % src["asset"] if src.get("asset") else "")
    if kind == "url":
        parts = urlsplit(src.get("url") or "")
        return (parts.hostname or "") + parts.path
    return "unknown source"


def pick_asset(assets: list, asset: str | None, local_file: str) -> dict:
    """The release file a source means.

    A named asset must be there by that name. Otherwise the release's .mpq
    files are considered: one is unambiguous, and among several the one
    sharing the local file's name is chosen. Anything else is a question
    only the user can answer, so it is asked rather than guessed."""
    if asset:
        hit = next((a for a in assets
                    if a.get("name", "").lower() == asset.lower()), None)
        if hit is None:
            raise ValueError("The latest release has no file named %s." % asset)
        return hit
    mpqs = [a for a in assets if fnmatch.fnmatch(a.get("name", "").lower(), "*.mpq")]
    if not mpqs:
        raise ValueError("The latest release has no .mpq file.")
    if len(mpqs) == 1:
        return mpqs[0]
    same = [a for a in mpqs if a.get("name", "").lower() == local_file.lower()]
    if len(same) == 1:
        return same[0]
    raise ValueError("The latest release has several .mpq files (%s). Paste "
                     "the download link of the one you use."
                     % ", ".join(a.get("name", "?") for a in mpqs))


def asset_remote(asset: dict) -> Remote:
    """What a release asset says about itself. GitHub publishes a SHA-256
    digest for assets uploaded since mid-2025; older assets and Codeberg do
    not, and then only the asset's identity is known."""
    digest = (asset.get("digest") or "").lower()
    sha = digest[7:] if digest.startswith("sha256:") else None
    marker = "%s:%s" % (asset.get("id"), asset.get("updated_at") or "")
    return Remote(sha=sha or None, marker=marker,
                  url=asset.get("browser_download_url"))


# ──────────────────────────────────────────────────────────────────────────────
#  Records
# ──────────────────────────────────────────────────────────────────────────────

def installed_record(*, sha: str, source: dict, remote: Remote | None,
                     installed_by: str) -> dict:
    """A pack EqUpdater just wrote. Its bytes are the source's by
    construction, so it is tracked from the start."""
    return {"managed": True, "installed_by": installed_by, "adopted": False,
            "sha": sha, "source": source, "matched_source": True,
            "release_marker": remote.marker if remote else None}


def linked_record(*, sha: str, source: dict, remote: Remote) -> dict:
    """A pack the user says came from `source`. Nothing on disk changes.

    Tracked only if the bytes are provably the source's current copy. A
    release with no published checksum cannot prove that, so the link is
    kept but the pack stays unconfirmed until it is replaced from source."""
    matched = bool(remote.sha) and remote.sha == sha
    return {"managed": True, "installed_by": None, "adopted": True,
            "sha": sha, "source": source, "matched_source": matched,
            "release_marker": remote.marker if matched else None}


def link_outcome(record: dict) -> str:
    """One line for the log, saying what linking established."""
    if record.get("matched_source"):
        return ("It matches the source's current copy. Updates will be "
                "offered when the source publishes a new one.")
    return ("It is not the source's current copy, or the source publishes no "
            "checksum to prove it is. It will not be replaced unless you "
            "choose Replace.")


# ──────────────────────────────────────────────────────────────────────────────
#  Judgement
# ──────────────────────────────────────────────────────────────────────────────

#: States a row can show. `updateAvailable` is the only one that offers the
#: plain Update button.
STATES = ("unmanaged", "modified", "unverifiable", "upToDate",
          "updateAvailable", "sourceDiffers", "unconfirmed")

#: States where the user may deliberately overwrite the pack with the
#: source's copy, after a warning and with the current file kept.
REPLACEABLE = ("modified", "sourceDiffers", "unconfirmed")


def judge(record: dict | None, local_sha: str | None,
          remote: Remote | None, lookup_failed: bool = False) -> tuple:
    """(state, may_update) for one installed pack.

    The order is the policy, as in planner.plan: ownership first, then
    "is it still what was recorded", then "could the source be asked", and
    only then "is there something newer"."""
    if not record or not record.get("managed"):
        return "unmanaged", False

    if record.get("sha") and local_sha != record["sha"]:
        # Ours, but not as we left it: edited, or replaced since.
        return "modified", False

    if lookup_failed or remote is None:
        return "unverifiable", False

    # Linked or installed with no fingerprint (a record written before
    # fingerprints were kept): nothing proves the file is still the one
    # the source sent, so it is never updated on that basis.
    if not record.get("sha"):
        return "unconfirmed", False

    # Legacy records predate linking; every one of them was an install.
    matched = record.get("matched_source", not record.get("adopted"))

    if remote.sha:
        if remote.sha == local_sha:
            return "upToDate", False
        # Untouched since it arrived from this source, and the source now
        # publishes different bytes: the source has moved on. For a pack
        # that never matched the source, different bytes say nothing about
        # which is newer.
        return ("updateAvailable", True) if matched else ("sourceDiffers", False)

    # No checksum published: only the release asset's identity is known.
    if matched and record.get("release_marker") and remote.marker:
        if remote.marker == record["release_marker"]:
            return "upToDate", False
        return "updateAvailable", True
    return "unconfirmed", False


def settle(record: dict, local_sha: str | None, remote: Remote | None) -> dict | None:
    """The record updated after a check that proved the pack is the
    source's current copy, or None if nothing changed.

    A linked pack that differed at link time, and whose source has since
    published exactly these bytes, is from then on the source's copy --
    tracked like an install. Without this it would read "differs from
    source" at the next release despite having been proven identical."""
    if not (record and record.get("managed") and remote and remote.sha
            and local_sha and remote.sha == local_sha
            and record.get("sha") == local_sha):
        return None
    if record.get("matched_source") and record.get("release_marker") == remote.marker:
        return None
    return dict(record, matched_source=True, release_marker=remote.marker)
