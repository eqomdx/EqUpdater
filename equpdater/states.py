"""The vocabulary the whole updater decides in: what a component *is*, and
what may be done to it.

Two separate ideas live here and they are worth keeping apart.

`Status` is what the user is shown -- the honest description of a component as
it exists right now. `Action` is what an automatic update flow may do about it.
They are not the same list: several different statuses all mean "leave it
alone", and the reason they mean that is exactly what the user needs told.

The old updater collapsed both into one string, `outOfDate`, which every
mismatch resolved to: a newer local build, a fork the user chose, an addon
they installed by hand, a file they edited. One word, one button, and the
button overwrote all four.
"""

from __future__ import annotations

from enum import Enum


class Status(Enum):
    """What a component is. This is display vocabulary, deliberately plain."""

    NOT_INSTALLED = "Not installed"
    UP_TO_DATE = "Up to date"
    UPDATE_AVAILABLE = "Update available"

    # The local copy is ahead of what the configured source offers. The
    # scenario this product was rewritten around: UnitXP V90 installed, the
    # repository still publishing V89.
    LOCAL_NEWER = "Local version newer"

    # On disk, but EqUpdater did not put it there and has not been asked to
    # look after it. It is somebody else's file.
    UNMANAGED = "Installed manually"

    # Managed, but its files no longer match what was installed -- the user
    # edited them, or another tool wrote over them.
    MODIFIED = "Modified locally"

    # The configured source is not the source it was installed from. A
    # different fork is not a new version of the same thing.
    DIFFERENT_SOURCE = "Different source"

    # Commit histories that do not contain one another: a rebase, another
    # branch, another fork.
    DIVERGED = "Different revision"

    # A version or revision exists on both sides and cannot be ordered, or the
    # lookup failed. Never grounds for replacing anything.
    UNVERIFIABLE = "Unable to verify"

    IGNORED = "Ignored"
    DISABLED = "Disabled"
    MISSING_FILES = "Missing files"

    INSTALLING = "Installing…"
    UPDATING = "Updating…"
    ERROR = "Error"

    def __str__(self) -> str:
        return self.value


#: Statuses an automatic flow must never act on. Kept as a set rather than
#: spelled out at each call site so a status added later cannot quietly become
#: eligible for Update All by being forgotten in one `if`.
PROTECTED = frozenset({
    Status.LOCAL_NEWER,
    Status.UNMANAGED,
    Status.MODIFIED,
    Status.DIFFERENT_SOURCE,
    Status.DIVERGED,
    Status.UNVERIFIABLE,
    Status.IGNORED,
    Status.DISABLED,
    Status.ERROR,
})


class Action(Enum):
    """What an update flow decided to do, and when it decided not to, why.

    Only UPDATE does anything. Every SKIP_* carries its own reason so the log
    can say which one applied instead of falling silent."""

    UPDATE = "update"
    SKIP_UP_TO_DATE = "up to date"
    SKIP_LOCAL_NEWER = "local version is newer"
    SKIP_UNMANAGED = "not managed by EqUpdater"
    SKIP_MODIFIED = "local files have been modified"
    SKIP_IGNORED = "updates ignored"
    SKIP_DISABLED = "disabled"
    SKIP_NOT_INSTALLED = "not installed"
    SKIP_SOURCE_CHANGED = "configured source differs from the installed one"
    SKIP_DIVERGED = "local and remote histories have diverged"
    SKIP_UNVERIFIABLE = "cannot determine which is newer"
    REQUIRES_CONFIRMATION = "needs explicit confirmation"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


#: The one action Update All is allowed to carry out.
AUTOMATIC = frozenset({Action.UPDATE})


class Plan:
    """One component's decision: the action, the status behind it, and a
    sentence explaining it.

    Everything that needs to know what will happen to a component -- the row
    in the UI, the badge count, Update All, the preview, the log -- reads one
    of these. That is the point: before this existed the UI decided what to
    overwrite independently of the worker that did the overwriting, and the
    two could and did disagree."""

    __slots__ = ("component_id", "kind", "action", "status", "reason",
                 "local", "remote", "detail")

    def __init__(self, component_id: str, kind: str, action: Action,
                 status: Status, reason: str = "", local=None, remote=None,
                 detail=None):
        self.component_id = component_id
        self.kind = kind                # "mod" | "addon" | "mpq"
        self.action = action
        self.status = status
        self.reason = reason or str(action)
        self.local = local              # installed version / sha, for display
        self.remote = remote            # what the source offers
        self.detail = detail or {}

    @property
    def will_update(self) -> bool:
        return self.action in AUTOMATIC

    @property
    def skipped(self) -> bool:
        return self.action is not Action.UPDATE

    def log_line(self) -> str:
        """The multi-line explanation for the update log. A skip says what was
        installed, what the source offers and why nothing happened -- the
        three facts somebody needs to decide whether the updater was right."""
        out = [f"{self.component_id}:"]
        if self.local is not None:
            out.append(f"  Installed: {self.local}")
        if self.remote is not None:
            out.append(f"  Remote: {self.remote}")
        if self.action is Action.UPDATE:
            out.append("  Update available.")
        else:
            out.append(f"  Skipping: {self.reason}.")
        return "\n".join(out)

    def __repr__(self) -> str:                      # pragma: no cover - debug
        return (f"Plan({self.component_id} {self.kind} "
                f"{self.action.name} {self.status.name})")
