"""Whether the files on disk are still the files that were installed.

**Why this is not the same question as "which commit was installed".** The old
updater recorded the sha it installed from, which proves where the bytes came
from and nothing at all about where they are now. Somebody who edits one line
of pfUI's config, or drops a patched .lua in over the top, still has a config
record saying "installed from abc123" -- and the next update happily replaces
their work with abc124 and never mentions it.

A content hash closes that. Take a fingerprint of the managed files at install
time; compare it before touching them again. Different means somebody changed
something, and somebody changing something is exactly when an updater should
stop and ask rather than proceed.

Deliberately conservative: nothing is excluded except version-control
metadata and operating-system droppings. Guessing that a file is "just
runtime data" and skipping it is how a real modification gets missed.
"""

from __future__ import annotations

import hashlib
import os

#: Directory names never counted. `.git` because an addon installed from a
#: zip has none and one cloned by hand does, and that difference is not a
#: modification of the addon.
SKIP_DIRS = frozenset({".git", ".svn", ".hg", "__pycache__"})

#: Files never counted: written by the file manager, not by anybody.
SKIP_FILES = frozenset({"thumbs.db", ".ds_store", "desktop.ini"})

_CHUNK = 1 << 20


def _hash_file(path: str, digest) -> None:
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            digest.update(block)


def folder_hash(root: str) -> str | None:
    """A stable fingerprint of every file under `root`.

    None when the folder does not exist -- "gone" is a different state from
    "changed" and the caller has to be able to tell them apart.

    Paths go into the digest as well as contents, so renaming a file or adding
    an empty one registers. Separators are normalised and the walk is sorted,
    so the same folder answers the same on Windows and Linux."""
    if not root or not os.path.isdir(root):
        return None

    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames, key=str.lower):
            if name.lower() in SKIP_FILES:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            digest.update(rel.encode("utf-8", "replace"))
            digest.update(b"\0")
            try:
                digest.update(str(os.path.getsize(full)).encode())
                _hash_file(full, digest)
            except OSError:
                # Unreadable file: recorded as unreadable rather than
                # skipped, so it cannot silently drop out of the fingerprint
                # and make a changed folder look unchanged.
                digest.update(b"<unreadable>")
            digest.update(b"\0")
    return digest.hexdigest()


def files_hash(root: str, relative_paths) -> str | None:
    """The same fingerprint for a named list of files rather than a tree.

    This is the DLL-mod shape: a mod owns two or three files sitting in the
    client directory among hundreds it does not own, so the tree is not the
    unit -- the list is. A missing file is recorded as missing rather than
    skipped, for the reason above."""
    if not root:
        return None
    paths = [p for p in (relative_paths or []) if p]
    if not paths:
        return None

    digest = hashlib.sha256()
    for rel in sorted(paths, key=str.lower):
        full = os.path.join(root, rel.replace("/", os.sep))
        digest.update(rel.replace("\\", "/").encode("utf-8", "replace"))
        digest.update(b"\0")
        if os.path.isfile(full):
            try:
                digest.update(str(os.path.getsize(full)).encode())
                _hash_file(full, digest)
            except OSError:
                digest.update(b"<unreadable>")
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def unchanged(recorded: str | None, current: str | None) -> bool:
    """Whether a fingerprint still matches.

    **False when either side is missing**, and that is the important half.
    A record from before fingerprinting existed, or a folder that cannot be
    read, is not evidence that nothing changed -- and an updater that treats
    "I don't know" as "it's fine" overwrites the one user who edited their
    addon before this feature shipped."""
    if not recorded or not current:
        return False
    return recorded == current
