"""WoW's folders, found whatever their case.

The client was written for Windows, where ``Interface\\AddOns``,
``interface\\addons`` and ``Interface\\Addons`` are one folder. On Linux
they are three. A client that has lived under Wine, been copied by hand or
unpacked by another tool can hold any of them -- a tester's had
``Interface/Addons`` -- and EqUpdater, building ``Interface/AddOns``, made a
second, empty folder beside it, installed into that, and did not see the
player's addons at all.

So every WoW folder EqUpdater uses is found through here:

* ``game_path(client, "WTF", "Config.wtf")`` -- for reading and writing a
  known path: each part that exists in some case is used as it is; a part
  that does not exist yet gets the canonical spelling.
* ``addons_dir(client)`` -- the addons folder, always ``Interface/AddOns``
  once it has run, because the addons folder is the one EqUpdater writes
  into on every install:

  - only ``AddOns`` exists: used as it is;
  - only another case (``Addons``, ``ADDONS``...) exists: renamed to
    ``AddOns`` -- a case-only rename, every addon in it untouched, so the
    managed-addon records (keyed by folder name, with content hashes) still
    match;
  - ``AddOns`` and another case both exist: everything in the other one
    that ``AddOns`` does not have is moved across; a folder both have with
    *identical* contents is collapsed to the ``AddOns`` copy; a folder both
    have with *different* contents is left exactly where it is, and is a
    conflict. While a conflict stands, nothing may install into or remove
    from the addons folder (``AddonDirConflict``) until the player chooses
    which copy to keep (``resolve_conflicts``) -- the other one is moved
    aside, never deleted.

On Windows the filesystem is case-insensitive and none of this can happen;
nothing there is renamed or moved, and the paths are what they always were.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from dataclasses import dataclass, field

INTERFACE = "Interface"
ADDONS = "AddOns"

_LOCK = threading.RLock()


def _windows() -> bool:
    from . import platforms
    return platforms.WINDOWS


def case_variants(parent: str, name: str) -> list:
    """Entries of ``parent`` that are ``name`` in some case, exact first."""
    try:
        entries = os.listdir(parent)
    except OSError:
        return []
    want = name.casefold()
    found = [e for e in entries if e.casefold() == want]
    return sorted(found, key=lambda e: (e != name, e))


def game_path(client_dir: str, *parts: str) -> str:
    """``client_dir/parts...`` with each part that exists, in any case, as
    it exists -- the exact spelling first when there are several. A part
    that does not exist (and everything below it) keeps the given, canonical
    spelling. Nothing is created or renamed."""
    path = client_dir
    for i, part in enumerate(parts):
        found = case_variants(path, part) if not _windows() else []
        if not found:
            return os.path.join(path, *parts[i:])
        path = os.path.join(path, found[0])
    return path


# ──────────────────────────────────────────────────────────────────────────────
#  The addons folder
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AddonDirState:
    path: str                                      # the folder to use
    renamed: str | None = None                     # "Addons" -> "AddOns"
    moved: list = field(default_factory=list)      # entries moved across
    collapsed: list = field(default_factory=list)  # identical duplicates dropped
    conflicts: list = field(default_factory=list)  # (entry, other copy, AddOns copy)
    notes: list = field(default_factory=list)      # anything else worth logging


class AddonDirConflict(RuntimeError):
    """Two case variants of the addons folder hold different copies of the
    same addon; nothing may change the addons folder until it is resolved."""

    def __init__(self, state: AddonDirState):
        names = ", ".join(c[0] for c in state.conflicts)
        super().__init__(f"addon folders in conflict: {names}")
        self.state = state


def tree_digest(path: str) -> str:
    """A fingerprint of a file or folder: names (relative) and contents."""
    h = hashlib.sha256()
    if os.path.isfile(path):
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            h.update(rel.encode("utf-8", "surrogateescape") + b"\0")
            with open(full, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            h.update(b"\0")
    return h.hexdigest()


def _case_rename(parent: str, src: str, dst: str) -> None:
    """Rename ``src`` to ``dst`` in ``parent`` where the two differ only in
    case: through a temporary name, so it also works on a case-insensitive
    filesystem (an NTFS or case-folding mount)."""
    tmp = os.path.join(parent, f".{dst}.eqrename-{os.getpid()}")
    os.rename(os.path.join(parent, src), tmp)
    os.rename(tmp, os.path.join(parent, dst))


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def prepare_addons_dir(client_dir: str) -> AddonDirState:
    """Find -- and, on a case-sensitive filesystem, settle -- the addons
    folder, as described in the module notes. Idempotent; safe to call
    before every scan, install, update or removal."""
    canonical_rel = os.path.join(INTERFACE, ADDONS)
    if _windows() or not client_dir:
        return AddonDirState(os.path.join(client_dir, canonical_rel))
    with _LOCK:
        state = AddonDirState(os.path.join(client_dir, canonical_rel))

        # Interface itself: one case variant is renamed to "Interface";
        # several are left alone (the exact one, else the first, is used).
        ifaces = case_variants(client_dir, INTERFACE)
        if not ifaces:
            return state
        if INTERFACE not in ifaces and len(ifaces) == 1:
            _case_rename(client_dir, ifaces[0], INTERFACE)
            state.notes.append(f"renamed {ifaces[0]} to {INTERFACE}")
            ifaces = [INTERFACE]
        elif len(ifaces) > 1:
            state.notes.append("several Interface folders: "
                               + ", ".join(ifaces) + f"; using {ifaces[0]}")
        iface = os.path.join(client_dir, ifaces[0])
        state.path = os.path.join(iface, ADDONS)

        variants = case_variants(iface, ADDONS)
        others = [v for v in variants if v != ADDONS
                  and os.path.isdir(os.path.join(iface, v))]
        if not others:
            return state
        if ADDONS not in variants and len(others) == 1:
            _case_rename(iface, others[0], ADDONS)
            state.renamed = others[0]
            return state
        if ADDONS not in variants:
            # Several wrong-case folders and no canonical one: the first
            # becomes AddOns, the rest are merged into it below.
            _case_rename(iface, others[0], ADDONS)
            state.renamed = others[0]
            others = others[1:]

        canonical = state.path
        for other in others:
            src_root = os.path.join(iface, other)
            for entry in sorted(os.listdir(src_root)):
                src = os.path.join(src_root, entry)
                matches = case_variants(canonical, entry)
                if not matches:
                    shutil.move(src, os.path.join(canonical, entry))
                    state.moved.append(f"{other}/{entry}")
                    continue
                dst = os.path.join(canonical, matches[0])
                if tree_digest(src) == tree_digest(dst):
                    _remove(src)
                    state.collapsed.append(f"{other}/{entry}")
                else:
                    state.conflicts.append((entry, src, dst))
            if not os.listdir(src_root):
                os.rmdir(src_root)
        return state


def addons_dir(client_dir: str) -> str:
    """The addons folder to read from (prepare_addons_dir's path)."""
    return prepare_addons_dir(client_dir).path


def writable_addons_dir(client_dir: str) -> str:
    """The addons folder to change, or AddonDirConflict while two case
    variants hold different copies of the same addon."""
    state = prepare_addons_dir(client_dir)
    if state.conflicts:
        raise AddonDirConflict(state)
    return state.path


def resolve_conflicts(client_dir: str, keep: str) -> tuple:
    """Settle every conflict: ``keep="addons"`` keeps the copies already in
    ``AddOns``; ``keep="other"`` puts the other folder's copies there. The
    copies not kept are moved -- never deleted -- into
    ``Interface/AddOns-conflicts-<time>/<folder they came from>/``, which the
    game does not load. Returns (the aside folder, the entries moved)."""
    if keep not in ("addons", "other"):
        raise ValueError(keep)
    with _LOCK:
        state = prepare_addons_dir(client_dir)
        if not state.conflicts:
            return None, []
        iface = os.path.dirname(state.path)
        aside = os.path.join(iface, time.strftime("AddOns-conflicts-%Y%m%d-%H%M%S"))
        moved = []
        for entry, other_copy, addons_copy in state.conflicts:
            if keep == "addons":
                losing, origin = other_copy, os.path.basename(os.path.dirname(other_copy))
            else:
                losing, origin = addons_copy, ADDONS
            target = os.path.join(aside, origin)
            os.makedirs(target, exist_ok=True)
            shutil.move(losing, os.path.join(target, os.path.basename(losing)))
            if keep == "other":
                shutil.move(other_copy, os.path.join(state.path, entry))
            moved.append(f"{origin}/{entry}")
        for v in case_variants(iface, ADDONS):
            p = os.path.join(iface, v)
            if v != ADDONS and os.path.isdir(p) and not os.listdir(p):
                os.rmdir(p)
        return aside, moved
