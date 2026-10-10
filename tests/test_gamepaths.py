"""WoW folders whatever their letter case (equpdater.gamepaths).

A Linux tester's client had Interface/Addons; EqUpdater made a second,
empty Interface/AddOns beside it and installed there. These run on a real
case-sensitive temporary folder (skipped where the filesystem folds case)
and check that nothing of the player's is ever deleted or overwritten.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _case_sensitive(path: str) -> bool:
    probe = os.path.join(path, "CaseProbe")
    open(probe, "w").close()
    try:
        return not os.path.exists(os.path.join(path, "caseprobe"))
    finally:
        os.remove(probe)


def modules():
    """The current package modules (other test files reload the package)."""
    from equpdater import gamepaths, platforms
    return sys.modules["equpdater.gamepaths"], sys.modules["equpdater.platforms"]


class Base(unittest.TestCase):
    def setUp(self):
        self.client = tempfile.mkdtemp(prefix="equ-case-")
        self.addCleanup(shutil.rmtree, self.client, True)
        if not _case_sensitive(self.client):
            self.skipTest("this filesystem is not case-sensitive")
        self.gp, self.platforms = modules()
        patch = mock.patch.object(self.platforms, "WINDOWS", False)
        patch.start()
        self.addCleanup(patch.stop)

    def addon(self, parent, name, files):
        d = os.path.join(self.client, "Interface", parent, name)
        os.makedirs(d, exist_ok=True)
        for rel, data in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(data)
        return d

    def listing(self, *parts):
        return sorted(os.listdir(os.path.join(self.client, *parts)))

    def read(self, *parts):
        with open(os.path.join(self.client, *parts)) as f:
            return f.read()


class TestOneFolder(Base):
    def test_only_canonical(self):
        self.addon("AddOns", "pfUI", {"pfUI.toc": "x"})
        state = self.gp.prepare_addons_dir(self.client)
        self.assertEqual(state.path, os.path.join(self.client, "Interface", "AddOns"))
        self.assertIsNone(state.renamed)
        self.assertEqual(self.listing("Interface"), ["AddOns"])

    def test_wrong_case_is_renamed_with_everything_in_it(self):
        for variant in ("Addons", "ADDONS", "addons"):
            with self.subTest(variant=variant):
                shutil.rmtree(os.path.join(self.client, "Interface"), True)
                self.addon(variant, "pfUI", {"pfUI.toc": "toc", "modules/a.lua": "a"})
                self.addon(variant, "Atlas", {"Atlas.toc": "t"})
                state = self.gp.prepare_addons_dir(self.client)
                self.assertEqual(state.renamed, variant)
                self.assertEqual(self.listing("Interface"), ["AddOns"])
                self.assertEqual(self.listing("Interface", "AddOns"), ["Atlas", "pfUI"])
                self.assertEqual(self.read("Interface", "AddOns", "pfUI", "modules", "a.lua"), "a")

    def test_managed_records_still_match_after_the_rename(self):
        """Records are keyed by folder name with a content hash: a case-only
        rename of the parent changes neither."""
        from equpdater.hashing import folder_hash
        d = self.addon("Addons", "pfUI", {"pfUI.toc": "toc", "x.lua": "x"})
        before = folder_hash(d)
        path = self.gp.addons_dir(self.client)
        self.assertEqual(folder_hash(os.path.join(path, "pfUI")), before)

    def test_wrong_case_interface_too(self):
        self.addon("Addons", "pfUI", {"pfUI.toc": "x"})
        os.rename(os.path.join(self.client, "Interface"),
                  os.path.join(self.client, "interface"))
        path = self.gp.addons_dir(self.client)
        self.assertEqual(path, os.path.join(self.client, "Interface", "AddOns"))
        self.assertEqual(self.listing(), ["Interface"])
        self.assertEqual(self.listing("Interface", "AddOns"), ["pfUI"])

    def test_no_interface_yet(self):
        path = self.gp.addons_dir(self.client)
        self.assertEqual(path, os.path.join(self.client, "Interface", "AddOns"))
        self.assertEqual(self.listing(), [])          # nothing created by a read

    def test_idempotent(self):
        self.addon("Addons", "pfUI", {"pfUI.toc": "x"})
        self.gp.prepare_addons_dir(self.client)
        state = self.gp.prepare_addons_dir(self.client)
        self.assertIsNone(state.renamed)
        self.assertEqual((state.moved, state.collapsed, state.conflicts), ([], [], []))


class TestBothFolders(Base):
    def setUp(self):
        super().setUp()
        # The tester's case: their addons in Addons; the native build's
        # install created AddOns beside it.
        self.addon("Addons", "pfUI", {"pfUI.toc": "theirs", "a.lua": "1"})
        self.addon("Addons", "Atlas", {"Atlas.toc": "same"})
        self.addon("Addons", "OnlyOld", {"OnlyOld.toc": "old"})
        self.addon("AddOns", "pfUI", {"pfUI.toc": "native", "a.lua": "2"})
        self.addon("AddOns", "Atlas", {"Atlas.toc": "same"})
        self.addon("AddOns", "OnlyNew", {"OnlyNew.toc": "new"})

    def test_merge_moves_collapses_and_keeps_conflicts(self):
        state = self.gp.prepare_addons_dir(self.client)
        self.assertEqual(state.moved, ["Addons/OnlyOld"])
        self.assertEqual(state.collapsed, ["Addons/Atlas"])
        self.assertEqual([c[0] for c in state.conflicts], ["pfUI"])
        self.assertEqual(self.listing("Interface", "AddOns"),
                         ["Atlas", "OnlyNew", "OnlyOld", "pfUI"])
        # The conflicting copies are both still there, untouched.
        self.assertEqual(self.listing("Interface", "Addons"), ["pfUI"])
        self.assertEqual(self.read("Interface", "Addons", "pfUI", "pfUI.toc"), "theirs")
        self.assertEqual(self.read("Interface", "AddOns", "pfUI", "pfUI.toc"), "native")

    def test_changes_are_refused_while_in_conflict(self):
        with self.assertRaises(self.gp.AddonDirConflict) as cm:
            self.gp.writable_addons_dir(self.client)
        self.assertEqual([c[0] for c in cm.exception.state.conflicts], ["pfUI"])
        # Reading still works.
        self.assertTrue(self.gp.addons_dir(self.client).endswith("AddOns"))

    def test_keep_the_other_copies(self):
        aside, moved = self.gp.resolve_conflicts(self.client, "other")
        self.assertEqual(moved, ["AddOns/pfUI"])
        self.assertEqual(self.read("Interface", "AddOns", "pfUI", "pfUI.toc"), "theirs")
        rel = os.path.relpath(aside, self.client)
        self.assertTrue(os.path.basename(rel).startswith("AddOns-conflicts-"))
        self.assertEqual(self.read(rel, "AddOns", "pfUI", "pfUI.toc"), "native")
        self.assertNotIn("Addons", self.listing("Interface"))   # emptied, removed
        self.gp.writable_addons_dir(self.client)                # no conflict now

    def test_keep_the_addons_copies(self):
        aside, moved = self.gp.resolve_conflicts(self.client, "addons")
        self.assertEqual(moved, ["Addons/pfUI"])
        self.assertEqual(self.read("Interface", "AddOns", "pfUI", "pfUI.toc"), "native")
        self.assertEqual(self.read(os.path.relpath(aside, self.client),
                                   "Addons", "pfUI", "pfUI.toc"), "theirs")

    def test_nothing_is_ever_lost(self):
        """Every file of either folder exists somewhere after merge and
        resolution, with its contents."""
        self.gp.prepare_addons_dir(self.client)
        self.gp.resolve_conflicts(self.client, "addons")
        everything = []
        for root, _d, files in os.walk(self.client):
            for f in files:
                with open(os.path.join(root, f)) as fh:
                    everything.append((f, fh.read()))
        for item in [("pfUI.toc", "theirs"), ("pfUI.toc", "native"), ("a.lua", "1"),
                     ("a.lua", "2"), ("Atlas.toc", "same"), ("OnlyOld.toc", "old"),
                     ("OnlyNew.toc", "new")]:
            self.assertIn(item, everything)


class TestAppUsesOneFolder(Base):
    """The app's addon code reaches the folder only through gamepaths."""

    def app(self):
        from equpdater import app
        return sys.modules["equpdater.app"]

    def test_install_after_migration_does_not_recreate_a_variant(self):
        m = self.app()
        self.addon("Addons", "pfUI", {"pfUI.toc": "x"})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Atlas-abc/Atlas.toc", "toc")
        with mock.patch.object(m, "_download_archive", return_value=buf.getvalue()):
            m.install_addon_files(self.client, "Atlas", "https://github.com/a/Atlas", "f" * 40)
        self.assertEqual(self.listing("Interface"), ["AddOns"])
        self.assertEqual(self.listing("Interface", "AddOns"), ["Atlas", "pfUI"])

    def test_install_is_refused_during_a_conflict(self):
        m = self.app()
        self.addon("Addons", "pfUI", {"pfUI.toc": "a"})
        self.addon("AddOns", "pfUI", {"pfUI.toc": "b"})
        with mock.patch.object(m, "_download_archive", return_value=b"") as dl:
            with self.assertRaises(self.gp.AddonDirConflict):
                m.install_addon_files(self.client, "pfUI", "https://github.com/a/pfUI", "f" * 40)
        dl.assert_not_called()
        self.assertEqual(self.read("Interface", "Addons", "pfUI", "pfUI.toc"), "a")
        self.assertEqual(self.read("Interface", "AddOns", "pfUI", "pfUI.toc"), "b")

    def test_no_other_addons_folder_is_built_by_hand(self):
        """One helper names the folder: no "AddOns" path joins elsewhere."""
        import re
        with open(os.path.join(ROOT, "equpdater", "app.py"), encoding="utf-8") as f:
            src = f.read()
        joins = re.findall(r'os\.path\.join\([^)]*"AddOns"', src)
        self.assertEqual(joins, [])


class TestOtherFolders(Base):
    def test_game_path_uses_the_existing_case(self):
        os.makedirs(os.path.join(self.client, "wtf"))
        with open(os.path.join(self.client, "wtf", "config.wtf"), "w") as f:
            f.write('SET gxWindow "1"\n')
        self.assertEqual(self.gp.game_path(self.client, "WTF", "Config.wtf"),
                         os.path.join(self.client, "wtf", "config.wtf"))
        # Missing parts keep the canonical spelling; nothing is created.
        self.assertEqual(self.gp.game_path(self.client, "Data", "enUS"),
                         os.path.join(self.client, "Data", "enUS"))
        self.assertEqual(self.listing(), ["wtf"])

    def test_config_wtf_is_written_into_the_existing_folder(self):
        m = sys.modules.get("equpdater.app") or __import__("equpdater.app").app
        os.makedirs(os.path.join(self.client, "wtf"))
        m.write_config_wtf(self.client, dict(m.TWEAKS_DEFAULTS))
        self.assertEqual(self.listing(), ["wtf"])
        self.assertEqual(self.listing("wtf"), ["Config.wtf"])

    def test_login_doctor_reads_wrong_case_files(self):
        from equpdater import logindoctor
        ld = sys.modules["equpdater.logindoctor"]
        with open(os.path.join(self.client, "Realmlist.wtf"), "w") as f:
            f.write("set realmlist play.octowow.st\n")
        os.makedirs(os.path.join(self.client, "WTF"))
        with open(os.path.join(self.client, "WTF", "config.wtf"), "w") as f:
            f.write('SET realmList "octowow.st"\n')
        checks, host = ld.realmlist_checks(self.client)
        self.assertEqual(host, "play.octowow.st")
        self.assertTrue(any("obsolete realmList" in c.message
                            for c in ld.config_checks(self.client, host)))


class TestWindowsUnchanged(unittest.TestCase):
    def test_nothing_renamed_or_resolved_on_windows(self):
        gp, platforms = modules()
        client = tempfile.mkdtemp(prefix="equ-win-")
        self.addCleanup(shutil.rmtree, client, True)
        os.makedirs(os.path.join(client, "Interface", "Addons", "pfUI"))
        with mock.patch.object(platforms, "WINDOWS", True):
            self.assertEqual(gp.addons_dir(client),
                             os.path.join(client, "Interface", "AddOns"))
            self.assertEqual(gp.game_path(client, "WTF", "Config.wtf"),
                             os.path.join(client, "WTF", "Config.wtf"))
        self.assertEqual(os.listdir(os.path.join(client, "Interface")), ["Addons"])


class TestCopiedWineSettings(unittest.TestCase):
    def test_foreign_paths(self):
        _gp, p = modules()
        with mock.patch.object(p, "WINDOWS", False):
            self.assertTrue(p.foreign_windows_path(r"Z:\home\me\Games\OctoWoW"))
            self.assertTrue(p.foreign_windows_path("C:/Games/OctoWoW"))
            self.assertFalse(p.foreign_windows_path("/home/me/Games/OctoWoW"))
            self.assertFalse(p.foreign_windows_path(""))
        with mock.patch.object(p, "WINDOWS", True):
            self.assertFalse(p.foreign_windows_path(r"C:\Games\OctoWoW"))

    @unittest.skipUnless(os.name == "posix", "Wine's Z: maps to a Linux root")
    def test_z_drive_maps_to_an_existing_native_folder(self):
        _gp, p = modules()
        d = tempfile.mkdtemp(prefix="equ-z-")
        self.addCleanup(shutil.rmtree, d, True)
        with mock.patch.object(p, "WINDOWS", False):
            self.assertEqual(p.native_path_for("Z:" + d.replace("/", "\\")), d)
            self.assertIsNone(p.native_path_for(r"Z:\no\such\folder"))
            self.assertIsNone(p.native_path_for(r"C:\Games\OctoWoW"))   # in a prefix


if __name__ == "__main__":
    unittest.main()
