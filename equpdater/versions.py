"""Version parsing and ordering.

**Why this module exists.** The updater this grew out of decided an update was
available with

    latest_version != installed_version

which is not a comparison, it is an inequality. It cannot tell newer from
older, so a repository that reports an *older* release than the one already on
disk reads as "update available" and a normal Update All quietly replaces
UnitXP V90 with V89. That is the single worst thing an updater can do, because
the user did not ask for it and nothing on screen said it happened.

So: parse, then order, and be honest when ordering is not possible. A version
this module cannot confidently compare answers UNKNOWN, and every caller treats
UNKNOWN as "leave it alone" rather than "replace it".

Formats handled -- these are what real 1.12 mod and addon releases look like:

    v90  V90  90  1.2  1.2.3  v1.2.3  release-1.2  1.10  2026.09.01
    1.2.3-beta1   1.2.3b   0.99.291

Deliberately *not* handled: git commit shas. They are identifiers, not
versions, and asking this module to order two of them answers UNKNOWN. Commit
ancestry is a different question with a different answer -- see gitcompare.
"""

from __future__ import annotations

import re
from enum import Enum


class Ordering(Enum):
    """How a remote version relates to the installed one."""

    NEWER = "newer"        # remote > local: a real update
    SAME = "same"          # remote == local
    OLDER = "older"        # remote < local: the local copy is ahead
    UNKNOWN = "unknown"    # cannot be ordered: never touch it automatically

    def __str__(self) -> str:
        return self.value


# A version is a run of dot/dash/underscore-separated numbers, optionally
# preceded by junk ("v", "V", "release-", "build_") and optionally followed by
# a pre-release tail ("-beta1", "rc2", "b").
_LEAD_JUNK = re.compile(r"^[^0-9]*")
_NUM_RUN = re.compile(r"^\d+(?:[._-]\d+)*")


class Version:
    """A parsed version: an ordered tuple of numbers plus a pre-release tail.

    `parts` is what orders two versions; `pre` breaks the tie when the numbers
    are equal, because 1.2.3-beta ships before 1.2.3. `raw` is kept so the UI
    can show exactly what the file or the release said rather than a
    normalised guess at it.
    """

    __slots__ = ("parts", "pre", "raw")

    def __init__(self, parts: tuple, pre: str, raw: str):
        self.parts = parts
        self.pre = pre
        self.raw = raw

    def __repr__(self) -> str:                      # pragma: no cover - debug
        return f"Version({self.raw!r} -> {self.parts}{'-' + self.pre if self.pre else ''})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.parts == other.parts and self.pre == other.pre

    def __hash__(self) -> int:
        return hash((self.parts, self.pre))


def parse(text) -> Version | None:
    """Parse a version string, or None when there is no version in it.

    Returns None rather than a zero version for anything unparseable: a
    caller that cannot tell "0" from "no idea" will eventually overwrite
    somebody's files, and that is the whole failure this module exists to
    stop."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    # A 7+ character hex run with no separators is a commit sha, not a
    # version. Ordering two of those is meaningless and dangerous.
    if re.fullmatch(r"[0-9a-fA-F]{7,}", raw) and not raw.isdigit():
        return None

    body = _LEAD_JUNK.sub("", raw)
    m = _NUM_RUN.match(body)
    if not m:
        return None

    parts = tuple(int(p) for p in re.split(r"[._-]", m.group(0)))
    pre = body[m.end():].strip(" .-_") or ""
    return Version(parts, pre.lower(), raw)


def _comparable(a: Version, b: Version) -> bool:
    """Whether two parsed versions are the same *kind* of version.

    A single-number scheme (UnitXP's V90) and a dotted scheme (1.2.3) are
    different numbering systems that happen to both contain digits. Ordering
    across them is nonsense -- 90 is not "newer than" 1.2.3 -- so they are
    only ever compared with their own kind. Everything else is compared
    numerically with zero padding, which is what makes 1.10 correctly newer
    than 1.9 where a string comparison makes it older."""
    return (len(a.parts) == 1) == (len(b.parts) == 1)


def compare(local, remote) -> Ordering:
    """Order `remote` against `local`. The result describes the *remote*.

    Both arguments may be strings or already-parsed Versions. Anything that
    cannot be parsed, or two versions from incompatible numbering schemes,
    answers UNKNOWN -- which every caller must read as "do not touch"."""
    lv = local if isinstance(local, Version) else parse(local)
    rv = remote if isinstance(remote, Version) else parse(remote)

    if lv is None or rv is None:
        return Ordering.UNKNOWN
    if not _comparable(lv, rv):
        return Ordering.UNKNOWN

    # Zero-pad so 1.2 and 1.2.0 are the same version rather than two.
    n = max(len(lv.parts), len(rv.parts))
    a = lv.parts + (0,) * (n - len(lv.parts))
    b = rv.parts + (0,) * (n - len(rv.parts))

    if b > a:
        return Ordering.NEWER
    if b < a:
        return Ordering.OLDER

    # Numbers agree: a pre-release tail loses to a plain release, and two
    # different tails on the same numbers are not safely orderable (is "rc2"
    # after "beta3"? usually, but not always, and guessing here would let an
    # update run on a guess).
    if lv.pre == rv.pre:
        return Ordering.SAME
    if lv.pre and not rv.pre:
        return Ordering.NEWER
    if rv.pre and not lv.pre:
        return Ordering.OLDER
    return Ordering.UNKNOWN


def is_newer(local, remote) -> bool:
    """True only for a proven newer remote. Every other answer -- same, older,
    unparseable, incomparable -- is False, so this is safe to gate an
    automatic update on."""
    return compare(local, remote) is Ordering.NEWER


def describe(local, remote) -> str:
    """One line for the log explaining what the comparison decided."""
    order = compare(local, remote)
    if order is Ordering.NEWER:
        return f"{local} -> {remote}"
    if order is Ordering.SAME:
        return f"{local} is current"
    if order is Ordering.OLDER:
        return f"local {local} is newer than {remote}"
    return f"cannot compare {local} with {remote}"
