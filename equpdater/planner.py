"""One place that decides what happens to a component.

**Why it is one place.** In the updater this replaces, the mods list decided
what to draw, the addons list decided what to draw, the Apply worker decided
what to install, and Update All decided what to sweep -- four implementations
of the same judgement, which drifted apart exactly as you would expect. A row
could show "update" while the worker skipped it, and a component could be
swept by Update All that no row had ever offered.

So: every one of them calls `plan()`, and `plan()` is a pure function over
facts already gathered. No network, no disk, no Tk. That is what makes the
safety invariants testable -- see tests/test_planner.py, which asserts them
directly rather than hoping the UI enforces them.

The order of the checks below is the safety policy, and it is deliberate:
ownership before staleness, and every "I don't know" before every "go".
"""

from __future__ import annotations

from .gitcompare import Ancestry, same_repo
from .hashing import unchanged
from .states import Action, Plan, Status
from .versions import Ordering, compare


class Component:
    """Everything the planner needs to know about one installable thing.

    Mods, addons and texture packs all reduce to this. The caller gathers the
    facts -- from config, from disk, from the network -- and the planner does
    nothing but judge them, which is why it can be exercised exhaustively
    without a client installed."""

    __slots__ = (
        "id", "kind", "name",
        "installed", "managed", "enabled", "ignore_updates",
        "files_present", "installed_version", "remote_version",
        "installed_sha", "remote_sha", "ancestry",
        "installed_source", "configured_source", "custom_source",
        "recorded_hash", "current_hash",
        "lookup_failed", "error",
    )

    def __init__(self, id: str, kind: str = "mod", name: str | None = None,
                 installed: bool = False, managed: bool = False,
                 enabled: bool = True, ignore_updates: bool = False,
                 files_present: bool = True,
                 installed_version=None, remote_version=None,
                 installed_sha=None, remote_sha=None,
                 ancestry: Ancestry | None = None,
                 installed_source=None, configured_source=None,
                 custom_source: bool = False,
                 recorded_hash=None, current_hash=None,
                 lookup_failed: bool = False, error=None):
        self.id = id
        self.kind = kind
        self.name = name or id
        self.installed = installed
        self.managed = managed
        self.enabled = enabled
        self.ignore_updates = ignore_updates
        self.files_present = files_present
        self.installed_version = installed_version
        self.remote_version = remote_version
        self.installed_sha = installed_sha
        self.remote_sha = remote_sha
        self.ancestry = ancestry
        self.installed_source = installed_source
        self.configured_source = configured_source
        self.custom_source = custom_source
        self.recorded_hash = recorded_hash
        self.current_hash = current_hash
        self.lookup_failed = lookup_failed
        self.error = error

    @property
    def tracks_hash(self) -> bool:
        """Whether a fingerprint was recorded when this was installed.

        A record written before fingerprinting existed has none, and a
        component with none is not claimed to be unmodified -- it is simply
        not checked for modification. Treating "never fingerprinted" as
        "modified" would make every migrated install undismissable noise;
        treating a *recorded* fingerprint that no longer matches as fine
        would be the bug this exists to prevent."""
        return bool(self.recorded_hash)


def _source_changed(c: Component) -> bool:
    """Whether the configured source is a different repository from the one
    the component was installed from.

    A user-chosen source always wins: `custom_source` means they picked it,
    and the catalogue does not get to argue. Missing information on either
    side is not a change -- an absent installed source is an unknown, and
    unknowns do not trigger warnings that train people to ignore warnings."""
    if c.custom_source:
        return False
    if not c.installed_source or not c.configured_source:
        return False
    return not same_repo(c.installed_source, c.configured_source)


def _by_version(c: Component) -> tuple:
    order = compare(c.installed_version, c.remote_version)
    if order is Ordering.NEWER:
        return Action.UPDATE, Status.UPDATE_AVAILABLE
    if order is Ordering.SAME:
        return Action.SKIP_UP_TO_DATE, Status.UP_TO_DATE
    if order is Ordering.OLDER:
        return Action.SKIP_LOCAL_NEWER, Status.LOCAL_NEWER
    return Action.SKIP_UNVERIFIABLE, Status.UNVERIFIABLE


def _by_ancestry(c: Component) -> tuple:
    a = c.ancestry
    if a is Ancestry.REMOTE_AHEAD:
        return Action.UPDATE, Status.UPDATE_AVAILABLE
    if a is Ancestry.IDENTICAL:
        return Action.SKIP_UP_TO_DATE, Status.UP_TO_DATE
    if a is Ancestry.LOCAL_AHEAD:
        return Action.SKIP_LOCAL_NEWER, Status.LOCAL_NEWER
    if a is Ancestry.DIVERGED:
        return Action.SKIP_DIVERGED, Status.DIVERGED
    return Action.SKIP_UNVERIFIABLE, Status.UNVERIFIABLE


def plan(c: Component) -> Plan:
    """What may be done to one component, and why.

    Read the order of these blocks as the policy they are. Everything that
    can say "leave this alone" gets to say it before anything can say
    "replace this", because the cost of a wrong skip is a stale file and the
    cost of a wrong update is somebody's work."""

    def made(action: Action, status: Status, reason: str = "") -> Plan:
        return Plan(c.id, c.kind, action, status, reason or str(action),
                    local=c.installed_version or c.installed_sha,
                    remote=c.remote_version or c.remote_sha)

    # ── 1. states that are not about updating at all ─────────────────────────
    if c.error:
        return made(Action.ERROR, Status.ERROR, str(c.error))

    if not c.installed:
        # Installing something absent is an explicit act, never a sweep.
        return made(Action.SKIP_NOT_INSTALLED, Status.NOT_INSTALLED)

    if not c.enabled:
        return made(Action.SKIP_DISABLED, Status.DISABLED)

    # ── 2. ownership, before anything about versions ─────────────────────────
    #
    # This is the rule the whole product turns on. A file EqUpdater did not
    # install is not EqUpdater's to replace, however out of date it looks and
    # however confidently the catalogue thinks it knows better. The user can
    # hand it over -- explicitly, with a button -- and until they do the
    # answer to every automatic flow is no.
    if not c.managed:
        return made(Action.SKIP_UNMANAGED, Status.UNMANAGED)

    # An explicit "leave this alone" outranks every discovery below it,
    # including a perfectly good newer release.
    if c.ignore_updates:
        return made(Action.SKIP_IGNORED, Status.IGNORED)

    # ── 3. the local copy is not what was installed ──────────────────────────
    if not c.files_present:
        # Nothing to destroy, but also nothing that says the user wants it
        # back -- they may have removed it on purpose. Offered as a button,
        # never swept.
        return made(Action.REQUIRES_CONFIRMATION, Status.MISSING_FILES,
                    "installed files are missing; reinstall to restore them")

    if c.tracks_hash and not unchanged(c.recorded_hash, c.current_hash):
        return made(Action.SKIP_MODIFIED, Status.MODIFIED,
                    "local files differ from the version EqUpdater installed")

    # ── 4. the source is not the source it came from ─────────────────────────
    #
    # A different fork at the same folder name is a *different addon* that
    # happens to share a name. Swapping one for the other is a decision, and
    # decisions belong to the user.
    if _source_changed(c):
        return made(Action.SKIP_SOURCE_CHANGED, Status.DIFFERENT_SOURCE,
                    f"installed from {c.installed_source}, "
                    f"configured source is {c.configured_source}")

    # ── 5. only now, is there actually something newer ───────────────────────
    if c.lookup_failed:
        # Could not reach the source. An error resolving the latest version
        # must never be the reason files get replaced.
        return made(Action.SKIP_UNVERIFIABLE, Status.UNVERIFIABLE,
                    "could not determine the latest version")

    if c.ancestry is not None:
        action, status = _by_ancestry(c)
    elif c.remote_sha or c.installed_sha:
        # Revision-tracked but no ancestry answer: two different shas with
        # nothing to order them by. Never an update.
        if c.remote_sha and c.installed_sha and c.remote_sha == c.installed_sha:
            action, status = Action.SKIP_UP_TO_DATE, Status.UP_TO_DATE
        else:
            action, status = Action.SKIP_UNVERIFIABLE, Status.UNVERIFIABLE
    else:
        action, status = _by_version(c)

    p = made(action, status)
    if action is Action.UPDATE:
        p.reason = "a newer version is available"
    return p


def plan_all(components) -> list:
    """Every component's decision, in the order given."""
    return [plan(c) for c in components]


def updatable(plans) -> list:
    """The subset Update All is allowed to touch. This is the only function
    Update All may use to choose its work."""
    return [p for p in plans if p.will_update]


def skipped_notably(plans) -> list:
    """Skips worth telling the user about.

    Up-to-date, not-installed and disabled components are the normal state of
    an install and listing them is noise. Everything else is a component that
    *looks* like it wants updating and deliberately was not -- which is the
    one thing an updater must never do silently."""
    quiet = {Action.SKIP_UP_TO_DATE, Action.SKIP_NOT_INSTALLED,
             Action.SKIP_DISABLED}
    return [p for p in plans if p.skipped and p.action not in quiet]


def summarise(plans) -> dict:
    """Counts for the badges and the Update All preview."""
    return {
        "update": len(updatable(plans)),
        "skipped": len(skipped_notably(plans)),
        "total": len(plans),
    }
