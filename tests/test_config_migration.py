"""Carrying Octo Updater's settings forward without carrying its assumptions.

The rule under test throughout: an old record proves the old updater
*installed* something. It proves nothing about whether the files on disk are
still what it installed.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater import branding, config                      # noqa: E402
from equpdater.gitcompare import Ancestry                   # noqa: E402
from equpdater.planner import Component, plan               # noqa: E402
from equpdater.states import Action                         # noqa: E402

LEGACY = {
    "octo_updater_version": "1.3.1",
    "out_dir": "D:/OctoWoW",
    "locale": "enUS",
    "tweaks": {"farClip": 1000},
    "updater_release_cache": {"tag": "v1.3.1", "timestamp": 1},
    "mods": {
        "ClassicAPI": {"enabled": True, "installed_version": "1.4",
                       "installed_files": ["ClassicAPI.dll"]},
        "UnitXP_SP3": {"enabled": True, "installed_version": "V90",
                       "installed_files": ["UnitXP_SP3.dll"],
                       "ignore_updates": True},
        "NeverInstalled": {"enabled": False},
    },
    "addons": {
        "pfUI": {"git": "https://github.com/shagu/pfUI", "sha": "a" * 40},
        "MyFork": {"git": "https://github.com/me/fork", "sha": "b" * 40,
                   "custom": True},
        "JustSeen": {},
    },
}


class TestMigrateRecords(unittest.TestCase):
    def setUp(self):
        self.out = config.migrate_records(LEGACY)

    def test_installed_mods_become_managed(self):
        """A recorded version means the old updater put it there, which is
        the one thing an old record does prove."""
        self.assertTrue(self.out["mods"]["ClassicAPI"]["managed"])
        self.assertEqual(self.out["mods"]["ClassicAPI"]["installed_version"],
                         "1.4")

    def test_a_record_with_no_version_is_not_claimed(self):
        """No version, no sha, no evidence anybody installed anything.
        Preserved and visible, but never swept."""
        self.assertFalse(self.out["mods"]["NeverInstalled"]["managed"])

    def test_ignore_updates_survives(self):
        """Somebody pinned UnitXP deliberately. A rename must not un-pin it."""
        self.assertTrue(self.out["mods"]["UnitXP_SP3"]["ignore_updates"])

    def test_addons_with_a_sha_become_managed(self):
        self.assertTrue(self.out["addons"]["pfUI"]["managed"])
        self.assertEqual(self.out["addons"]["pfUI"]["sha"], "a" * 40)

    def test_a_user_chosen_source_stays_user_chosen(self):
        """The catalogue must not reclaim a fork the user picked, before the
        rename or after it."""
        self.assertTrue(self.out["addons"]["MyFork"]["custom_source"])

    def test_an_addon_seen_but_never_installed_is_unmanaged(self):
        self.assertFalse(self.out["addons"]["JustSeen"]["managed"])

    def test_migrated_records_are_marked_as_inherited(self):
        """`installed_by` naming the previous product, and a fingerprint
        baseline of "migration" rather than "install", so the UI can be
        honest that the files predate this updater."""
        rec = self.out["mods"]["ClassicAPI"]
        self.assertEqual(rec["installed_by"], branding.UPSTREAM_NAME)
        self.assertTrue(rec["adopted"])


class TestMigrateConfig(unittest.TestCase):
    def setUp(self):
        self.out = config.migrate_config(LEGACY)

    def test_settings_are_carried(self):
        self.assertEqual(self.out["out_dir"], "D:/OctoWoW")
        self.assertEqual(self.out["locale"], "enUS")
        self.assertEqual(self.out["tweaks"], {"farClip": 1000})

    def test_caches_are_not_carried(self):
        """A cached release tag for a different product's repository is not a
        setting; it is stale data that would be believed."""
        self.assertNotIn("updater_release_cache", self.out)

    def test_dll_consent_is_not_inherited(self):
        """Octo Updater installed essential mods by default. Its stored "yes"
        was nobody's decision, so EqUpdater asks for itself."""
        out = config.migrate_config(dict(LEGACY, auto_install_mods=True))
        self.assertNotIn("auto_install_mods", out)

    def test_schema_is_stamped(self):
        self.assertEqual(self.out["schema"], config.SCHEMA_VERSION)

    def test_provenance_of_the_migration_itself_is_recorded(self):
        self.assertEqual(self.out["migrated_from"]["product"],
                         branding.UPSTREAM_NAME)


class TestBootstrap(unittest.TestCase):
    """The first-launch sequence, against a real temporary data directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="equ-cfg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.new_dir = os.path.join(self.tmp, "EqUpdater")
        self.old_dir = os.path.join(self.tmp, "OctoUpdater")
        os.makedirs(self.new_dir)
        os.makedirs(self.old_dir)

        self._saved = (config.APP_DATA_DIR, config.CONFIG_FILE,
                       config.BACKUP_DIR)
        config.APP_DATA_DIR = self.new_dir
        config.CONFIG_FILE = os.path.join(self.new_dir, "config.json")
        config.BACKUP_DIR = os.path.join(self.new_dir, "backups")
        self._saved_legacy = branding.legacy_app_data_dirs
        branding.legacy_app_data_dirs = lambda: [self.old_dir]
        config.branding.legacy_app_data_dirs = branding.legacy_app_data_dirs

        def restore():
            (config.APP_DATA_DIR, config.CONFIG_FILE,
             config.BACKUP_DIR) = self._saved
            branding.legacy_app_data_dirs = self._saved_legacy
            config.branding.legacy_app_data_dirs = self._saved_legacy
        self.addCleanup(restore)

    def write_legacy(self, data=LEGACY):
        config.save_config(data, os.path.join(self.old_dir, "config.json"))

    def test_fresh_machine(self):
        cfg = config.bootstrap_config()
        self.assertEqual(cfg["schema"], config.SCHEMA_VERSION)
        self.assertNotIn("migrated_from", cfg)

    def test_imports_the_previous_product(self):
        self.write_legacy()
        cfg = config.bootstrap_config()
        self.assertEqual(cfg["out_dir"], "D:/OctoWoW")
        self.assertTrue(cfg["mods"]["ClassicAPI"]["managed"])

    def test_the_old_config_is_left_where_it_was(self):
        """Somebody who does not like the new updater must be able to go back
        to the old one and find their settings intact."""
        self.write_legacy()
        config.bootstrap_config()
        self.assertTrue(os.path.isfile(
            os.path.join(self.old_dir, "config.json")))

    def test_a_backup_copy_is_kept(self):
        self.write_legacy()
        cfg = config.bootstrap_config()
        backup = cfg["migrated_from"]["backup"]
        self.assertTrue(backup and os.path.isfile(backup))

    def test_migration_does_not_run_twice(self):
        """Run once. A second launch must not re-import and stamp over
        whatever the user has changed since."""
        self.write_legacy()
        first = config.bootstrap_config()
        config.update_config(lambda c: c.__setitem__("out_dir", "E:/Moved"))
        second = config.bootstrap_config()
        self.assertEqual(second["out_dir"], "E:/Moved")
        self.assertEqual(first["migrated_from"]["at"],
                         second["migrated_from"]["at"])

    def test_an_existing_new_config_is_never_overwritten(self):
        self.write_legacy()
        config.save_config({"schema": config.SCHEMA_VERSION,
                            "out_dir": "F:/Mine"})
        cfg = config.bootstrap_config()
        self.assertEqual(cfg["out_dir"], "F:/Mine")

    def test_a_corrupt_config_does_not_crash_the_launch(self):
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        cfg = config.bootstrap_config()
        self.assertEqual(cfg["schema"], config.SCHEMA_VERSION)


class TestMigratedStateIsSafe(unittest.TestCase):
    """The migration is only correct if what comes out of it plans safely.
    These run the migrated records through the planner."""

    def setUp(self):
        self.out = config.migrate_records(LEGACY)

    def test_a_pinned_mod_stays_pinned_after_migration(self):
        rec = self.out["mods"]["UnitXP_SP3"]
        p = plan(Component(id="UnitXP_SP3", installed=True,
                           managed=rec["managed"],
                           ignore_updates=rec["ignore_updates"],
                           installed_version=rec["installed_version"],
                           remote_version="V89"))
        self.assertIs(p.action, Action.SKIP_IGNORED)

    def test_a_migrated_local_newer_mod_is_still_protected(self):
        """The headline case, surviving a product rename: V90 installed under
        the old updater, V89 in the repository, and nothing touches it."""
        rec = dict(self.out["mods"]["UnitXP_SP3"], ignore_updates=False)
        p = plan(Component(id="UnitXP_SP3", installed=True,
                           managed=rec["managed"],
                           installed_version=rec["installed_version"],
                           remote_version="V89"))
        self.assertIs(p.action, Action.SKIP_LOCAL_NEWER)

    def test_an_unclaimed_record_is_not_swept(self):
        rec = self.out["addons"]["JustSeen"]
        p = plan(Component(id="JustSeen", kind="addon", installed=True,
                           managed=rec["managed"], remote_sha="c" * 40,
                           ancestry=Ancestry.REMOTE_AHEAD))
        self.assertIs(p.action, Action.SKIP_UNMANAGED)


if __name__ == "__main__":
    unittest.main()
