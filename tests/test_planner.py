"""The safety invariants, asserted directly.

Every test here is a thing EqUpdater promises never to do. They are written
against `plan()` rather than against the UI on purpose: the UI, Update All,
the badges and the preview all consume these decisions, so proving the
decision proves all four at once -- which is the whole reason the planner was
pulled out of the UI in the first place.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater.gitcompare import Ancestry                      # noqa: E402
from equpdater.planner import (Component, plan, plan_all,       # noqa: E402
                               skipped_notably, updatable)
from equpdater.states import Action, Status                     # noqa: E402


def mod(**kw) -> Component:
    """A managed, enabled, installed DLL mod -- the only shape that is ever
    eligible for an automatic update. Tests override one field at a time so
    each asserts exactly one rule."""
    base = dict(id="TestMod", kind="mod", installed=True, managed=True,
                enabled=True, files_present=True,
                installed_version="1.0", remote_version="1.0")
    base.update(kw)
    return Component(**base)


def addon(**kw) -> Component:
    base = dict(id="TestAddon", kind="addon", installed=True, managed=True,
                enabled=True, files_present=True,
                installed_sha="a" * 40, remote_sha="a" * 40,
                ancestry=Ancestry.IDENTICAL,
                installed_source="https://github.com/owner/repo",
                configured_source="https://github.com/owner/repo")
    base.update(kw)
    return Component(**base)


class Invariant1NeverDowngrade(unittest.TestCase):
    """Normal update operations never intentionally downgrade a known
    version."""

    def test_unitxp_v90_against_repository_v89(self):
        p = plan(mod(id="UnitXP_SP3", installed_version="V90",
                     remote_version="V89"))
        self.assertIs(p.action, Action.SKIP_LOCAL_NEWER)
        self.assertIs(p.status, Status.LOCAL_NEWER)
        self.assertFalse(p.will_update)

    def test_dotted_downgrades(self):
        for local, remote in [("2.3", "2.2"), ("1.10", "1.9"),
                              ("1.2.4", "1.2.3")]:
            with self.subTest(local=local, remote=remote):
                p = plan(mod(installed_version=local, remote_version=remote))
                self.assertIs(p.action, Action.SKIP_LOCAL_NEWER)

    def test_genuine_upgrades_still_run(self):
        """The protections are worth nothing if they also block real work."""
        for local, remote in [("V89", "V90"), ("1.9", "1.10"),
                              ("v1.2.3", "1.2.4"), ("1.4", "1.5")]:
            with self.subTest(local=local, remote=remote):
                p = plan(mod(installed_version=local, remote_version=remote))
                self.assertIs(p.action, Action.UPDATE)
                self.assertIs(p.status, Status.UPDATE_AVAILABLE)


class Invariant2NeverTouchUnmanaged(unittest.TestCase):
    """Update All never modifies an unmanaged addon."""

    def test_manually_installed_addon_matching_the_catalog(self):
        """Questie, installed by hand, folder name matching a catalogue
        entry. Finding a matching repository is not ownership."""
        p = plan(addon(id="Questie", managed=False,
                       installed_sha=None, ancestry=None,
                       installed_source=None,
                       configured_source="https://github.com/aero/questie"))
        self.assertIs(p.action, Action.SKIP_UNMANAGED)
        self.assertIs(p.status, Status.UNMANAGED)

    def test_unmanaged_wins_over_a_newer_remote(self):
        """Even with a provably newer remote: not ours, not touched."""
        p = plan(mod(managed=False, installed_version="1.0",
                     remote_version="2.0"))
        self.assertIs(p.action, Action.SKIP_UNMANAGED)

    def test_adopting_it_makes_it_eligible(self):
        """...and the moment the user hands it over, it behaves normally."""
        p = plan(mod(managed=True, installed_version="1.0",
                     remote_version="2.0"))
        self.assertIs(p.action, Action.UPDATE)


class Invariant3NeverOverwriteModified(unittest.TestCase):
    """Update All never overwrites a locally modified managed addon."""

    def test_changed_fingerprint_blocks_the_update(self):
        p = plan(addon(recorded_hash="aaa", current_hash="bbb",
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.SKIP_MODIFIED)
        self.assertIs(p.status, Status.MODIFIED)

    def test_matching_fingerprint_allows_it(self):
        p = plan(addon(recorded_hash="aaa", current_hash="aaa",
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.UPDATE)

    def test_no_fingerprint_recorded_is_not_treated_as_modified(self):
        """A record migrated from the old updater has no fingerprint. That is
        a gap in knowledge, not evidence of tampering -- flagging every
        migrated install as modified would be noise nobody could clear."""
        p = plan(addon(recorded_hash=None, current_hash="whatever",
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.UPDATE)

    def test_a_folder_that_cannot_be_read_is_not_assumed_unchanged(self):
        p = plan(addon(recorded_hash="aaa", current_hash=None,
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.SKIP_MODIFIED)


class Invariant4SourceChangeIsNotAnUpdate(unittest.TestCase):
    """Changing repository/fork is not treated as a normal update."""

    def test_catalog_pointing_at_a_different_fork(self):
        p = plan(addon(installed_source="https://github.com/example/original",
                       configured_source="https://github.com/example/newfork",
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.SKIP_SOURCE_CHANGED)
        self.assertIs(p.status, Status.DIFFERENT_SOURCE)

    def test_a_user_chosen_source_is_never_argued_with(self):
        """`custom_source` means the user picked it. The catalogue does not
        get to switch it back, this run or any later one."""
        p = plan(addon(custom_source=True,
                       installed_source="https://github.com/me/myfork",
                       configured_source="https://github.com/example/newfork",
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.UPDATE)

    def test_url_spelling_differences_are_not_a_source_change(self):
        """The same repo is written a dozen ways. A spurious warning here
        trains people to click through the real ones."""
        p = plan(addon(installed_source="https://github.com/Owner/Repo.git",
                       configured_source="https://github.com/owner/repo/",
                       remote_sha="b" * 40,
                       ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.UPDATE)


class Invariant5ShaMismatchIsNotProof(unittest.TestCase):
    """Different Git SHAs alone do not prove the remote is newer."""

    def test_ancestry_decides_each_case(self):
        for anc, action in [
            (Ancestry.REMOTE_AHEAD, Action.UPDATE),
            (Ancestry.IDENTICAL, Action.SKIP_UP_TO_DATE),
            (Ancestry.LOCAL_AHEAD, Action.SKIP_LOCAL_NEWER),
            (Ancestry.DIVERGED, Action.SKIP_DIVERGED),
            (Ancestry.UNKNOWN, Action.SKIP_UNVERIFIABLE),
        ]:
            with self.subTest(ancestry=anc):
                p = plan(addon(remote_sha="b" * 40, ancestry=anc))
                self.assertIs(p.action, action)

    def test_two_shas_and_no_ancestry_answer_is_never_an_update(self):
        """The old behaviour exactly: remote_sha != installed_sha. Without an
        ancestry answer that is an observation, not a direction."""
        p = plan(addon(remote_sha="b" * 40, ancestry=None))
        self.assertIs(p.action, Action.SKIP_UNVERIFIABLE)
        self.assertIs(p.status, Status.UNVERIFIABLE)


class Invariant6IgnoreMeansIgnore(unittest.TestCase):
    """Ignoring updates actually excludes the component from automatic update
    flows."""

    def test_ignored_with_a_newer_remote(self):
        p = plan(mod(ignore_updates=True, installed_version="1.0",
                     remote_version="9.9"))
        self.assertIs(p.action, Action.SKIP_IGNORED)
        self.assertIs(p.status, Status.IGNORED)

    def test_ignored_is_excluded_from_update_all(self):
        plans = plan_all([
            mod(id="a", installed_version="1.0", remote_version="2.0"),
            mod(id="b", installed_version="1.0", remote_version="2.0",
                ignore_updates=True),
        ])
        self.assertEqual([p.component_id for p in updatable(plans)], ["a"])


class Invariant7LookupFailureNeverReplaces(unittest.TestCase):
    """An error resolving the latest version never causes replacement."""

    def test_failed_lookup(self):
        p = plan(mod(lookup_failed=True, installed_version="1.0",
                     remote_version=None))
        self.assertIs(p.action, Action.SKIP_UNVERIFIABLE)

    def test_a_failed_lookup_that_still_carries_a_stale_remote(self):
        """The dangerous shape: a cached remote version left over from a
        previous run, with this run's lookup having failed."""
        p = plan(mod(lookup_failed=True, installed_version="1.0",
                     remote_version="0.5"))
        self.assertIs(p.action, Action.SKIP_UNVERIFIABLE)
        self.assertFalse(p.will_update)

    def test_component_in_error_state(self):
        p = plan(mod(error="download blocked"))
        self.assertIs(p.action, Action.ERROR)
        self.assertIs(p.status, Status.ERROR)


class Invariant8UnknownMeansPreserve(unittest.TestCase):
    """Unknown version ordering defaults to preservation, not replacement."""

    def test_unorderable_versions(self):
        for local, remote in [("V90", "1.2.3"), ("main", "1.2.3"),
                              ("1.2.3", "latest"), (None, "1.2.3"),
                              ("1.2.3", None)]:
            with self.subTest(local=local, remote=remote):
                p = plan(mod(installed_version=local, remote_version=remote))
                self.assertFalse(p.will_update, (local, remote))


class Invariant9And10Ownership(unittest.TestCase):
    """Existing client files are preserved during discovery, and every
    destructive operation comes from an explicit state or action."""

    def test_discovered_dll_is_unmanaged_until_adopted(self):
        """First run against an existing client: a DLL is found, identified,
        shown -- and not replaced with the updater's preferred build."""
        p = plan(mod(id="SuperWoW", managed=False, installed_version="1.2",
                     remote_version="1.3"))
        self.assertIs(p.status, Status.UNMANAGED)
        self.assertFalse(p.will_update)

    def test_missing_files_ask_rather_than_act(self):
        """Nothing to destroy, but nothing saying the user wants it back
        either -- they may have deleted it deliberately."""
        p = plan(mod(files_present=False))
        self.assertIs(p.action, Action.REQUIRES_CONFIRMATION)
        self.assertIs(p.status, Status.MISSING_FILES)
        self.assertFalse(p.will_update)

    def test_nothing_installed_is_never_swept_in(self):
        p = plan(mod(installed=False))
        self.assertIs(p.action, Action.SKIP_NOT_INSTALLED)
        self.assertFalse(p.will_update)

    def test_disabled(self):
        p = plan(mod(enabled=False, installed_version="1.0",
                     remote_version="2.0"))
        self.assertIs(p.action, Action.SKIP_DISABLED)


class UpdateAllComposition(unittest.TestCase):
    """The whole point, end to end: given one of everything, Update All
    touches exactly the safe ones."""

    def setUp(self):
        self.components = [
            mod(id="ClassicAPI", installed_version="1.4", remote_version="1.5"),
            mod(id="SuperWoW", installed_version="2.2", remote_version="2.3"),
            mod(id="UnitXP_SP3", installed_version="V90", remote_version="V89"),
            mod(id="Ignored", installed_version="1.0", remote_version="2.0",
                ignore_updates=True),
            mod(id="Disabled", enabled=False, installed_version="1.0",
                remote_version="2.0"),
            mod(id="Offline", lookup_failed=True, installed_version="1.0"),
            addon(id="aux-addon", remote_sha="b" * 40,
                  ancestry=Ancestry.REMOTE_AHEAD),
            addon(id="pfUI", recorded_hash="x", current_hash="y",
                  remote_sha="b" * 40, ancestry=Ancestry.REMOTE_AHEAD),
            addon(id="Questie", managed=False),
            addon(id="Forked", installed_source="https://github.com/a/x",
                  configured_source="https://github.com/b/x",
                  remote_sha="b" * 40, ancestry=Ancestry.REMOTE_AHEAD),
            addon(id="Rebased", remote_sha="b" * 40,
                  ancestry=Ancestry.DIVERGED),
        ]
        self.plans = plan_all(self.components)

    def test_only_safe_updates_run(self):
        self.assertEqual(
            sorted(p.component_id for p in updatable(self.plans)),
            ["ClassicAPI", "SuperWoW", "aux-addon"])

    def test_everything_unusual_is_reported_not_silent(self):
        """A skip nobody is told about is indistinguishable from a bug."""
        reported = {p.component_id for p in skipped_notably(self.plans)}
        self.assertEqual(
            reported,
            {"UnitXP_SP3", "Ignored", "Offline", "pfUI", "Questie",
             "Forked", "Rebased"})

    def test_routine_skips_stay_quiet(self):
        """Up to date and disabled are the normal state of an install;
        listing them every run is noise that hides the real warnings."""
        quiet = {p.component_id for p in self.plans if p.skipped} - \
                {p.component_id for p in skipped_notably(self.plans)}
        self.assertIn("Disabled", quiet)

    def test_every_skip_explains_itself(self):
        for p in skipped_notably(self.plans):
            with self.subTest(component=p.component_id):
                self.assertTrue(p.reason)
                self.assertIn("Skipping:", p.log_line())


if __name__ == "__main__":
    unittest.main()
