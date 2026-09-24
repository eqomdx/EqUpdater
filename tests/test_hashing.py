"""Local-modification detection, against real files in a temp directory."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater.hashing import (files_hash, folder_hash,      # noqa: E402
                               unchanged)


class Tree(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="equ-hash-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text="x"):
        path = os.path.join(self.root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path


class TestFolderHash(Tree):
    def test_stable_across_calls(self):
        self.write("Addon.toc", "## Title: Addon")
        self.write("core.lua", "print(1)")
        self.assertEqual(folder_hash(self.root), folder_hash(self.root))

    def test_edited_file_changes_it(self):
        """The whole point: one edited line and the updater must notice."""
        self.write("core.lua", "print(1)")
        before = folder_hash(self.root)
        self.write("core.lua", "print(2)")
        self.assertNotEqual(before, folder_hash(self.root))

    def test_added_file_changes_it(self):
        self.write("core.lua")
        before = folder_hash(self.root)
        self.write("extra.lua")
        self.assertNotEqual(before, folder_hash(self.root))

    def test_removed_file_changes_it(self):
        self.write("core.lua")
        self.write("extra.lua")
        before = folder_hash(self.root)
        os.remove(os.path.join(self.root, "extra.lua"))
        self.assertNotEqual(before, folder_hash(self.root))

    def test_renamed_file_changes_it(self):
        """Contents go in with their paths, so a rename registers even when
        every byte in the folder is the same."""
        self.write("core.lua", "same")
        before = folder_hash(self.root)
        os.rename(os.path.join(self.root, "core.lua"),
                  os.path.join(self.root, "renamed.lua"))
        self.assertNotEqual(before, folder_hash(self.root))

    def test_git_metadata_is_not_content(self):
        """An addon installed from a zip has no .git and one cloned by hand
        does. That difference is not a modification of the addon."""
        self.write("core.lua")
        before = folder_hash(self.root)
        self.write(".git/HEAD", "ref: refs/heads/main")
        self.assertEqual(before, folder_hash(self.root))

    def test_os_droppings_are_not_content(self):
        self.write("core.lua")
        before = folder_hash(self.root)
        self.write("Thumbs.db", "junk")
        self.assertEqual(before, folder_hash(self.root))

    def test_missing_folder_is_none_not_a_hash(self):
        """Gone is a different state from changed and callers must be able to
        tell them apart."""
        self.assertIsNone(folder_hash(os.path.join(self.root, "nope")))
        self.assertIsNone(folder_hash(""))

    def test_nested_content(self):
        self.write("libs/lib/one.lua", "a")
        before = folder_hash(self.root)
        self.write("libs/lib/one.lua", "b")
        self.assertNotEqual(before, folder_hash(self.root))


class TestFilesHash(Tree):
    """A DLL mod owns two or three files among hundreds it does not, so the
    list is the unit rather than the tree."""

    def test_only_the_named_files_count(self):
        self.write("Mine.dll", "a")
        self.write("SomebodyElses.dll", "b")
        before = files_hash(self.root, ["Mine.dll"])
        self.write("SomebodyElses.dll", "changed")
        self.assertEqual(before, files_hash(self.root, ["Mine.dll"]))

    def test_changing_a_named_file_registers(self):
        self.write("Mine.dll", "a")
        before = files_hash(self.root, ["Mine.dll"])
        self.write("Mine.dll", "b")
        self.assertNotEqual(before, files_hash(self.root, ["Mine.dll"]))

    def test_a_missing_file_is_recorded_as_missing(self):
        """Recorded, not skipped -- a skipped file would let a deleted one
        make a changed set look unchanged."""
        self.write("One.dll", "a")
        both = files_hash(self.root, ["One.dll", "Two.dll"])
        self.write("Two.dll", "b")
        self.assertNotEqual(both, files_hash(self.root, ["One.dll", "Two.dll"]))

    def test_order_does_not_matter(self):
        self.write("a.dll", "a")
        self.write("b.dll", "b")
        self.assertEqual(files_hash(self.root, ["a.dll", "b.dll"]),
                         files_hash(self.root, ["b.dll", "a.dll"]))

    def test_empty_list(self):
        self.assertIsNone(files_hash(self.root, []))
        self.assertIsNone(files_hash(self.root, None))


class TestUnchanged(unittest.TestCase):
    def test_match(self):
        self.assertTrue(unchanged("abc", "abc"))

    def test_mismatch(self):
        self.assertFalse(unchanged("abc", "def"))

    def test_missing_either_side_is_not_proof_of_anything(self):
        """A record from before fingerprinting existed, or a folder that
        cannot be read. An updater that reads "I don't know" as "it's fine"
        overwrites the one user who edited their addon first."""
        self.assertFalse(unchanged(None, "abc"))
        self.assertFalse(unchanged("abc", None))
        self.assertFalse(unchanged(None, None))
        self.assertFalse(unchanged("", ""))


if __name__ == "__main__":
    unittest.main()
