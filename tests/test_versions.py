"""Version ordering -- the half of the UnitXP V90 -> V89 bug that lives in
arithmetic. The other half is ownership; see test_planner.py."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater.versions import Ordering, compare, is_newer, parse  # noqa: E402


class TestParse(unittest.TestCase):
    def test_release_formats(self):
        """Every shape a real 1.12 mod or addon release has been seen in."""
        for text, parts in [
            ("v90", (90,)), ("V90", (90,)), ("90", (90,)),
            ("1.2", (1, 2)), ("1.2.3", (1, 2, 3)), ("v1.2.3", (1, 2, 3)),
            ("release-1.2", (1, 2)), ("1.10", (1, 10)),
            ("0.99.291", (0, 99, 291)), ("2026.09.01", (2026, 9, 1)),
            ("  v1.4  ", (1, 4)),
        ]:
            with self.subTest(text=text):
                v = parse(text)
                self.assertIsNotNone(v, text)
                self.assertEqual(v.parts, parts)

    def test_prerelease_tail_is_kept_apart(self):
        v = parse("1.2.3-beta1")
        self.assertEqual(v.parts, (1, 2, 3))
        self.assertEqual(v.pre, "beta1")

    def test_unparseable_is_none_not_zero(self):
        """None, not (0,). A caller that cannot tell "version 0" from "no
        idea" eventually overwrites somebody's files."""
        for text in [None, "", "   ", "latest", "main", "unknown"]:
            with self.subTest(text=text):
                self.assertIsNone(parse(text))

    def test_commit_sha_is_not_a_version(self):
        """Shas are identifiers. Ordering two of them is meaningless, so they
        must not parse into something orderable."""
        self.assertIsNone(parse("abc1234"))
        self.assertIsNone(parse("def456789abcdef0123456789abcdef012345678"))

    def test_raw_is_preserved_for_display(self):
        self.assertEqual(parse("V90").raw, "V90")


class TestCompare(unittest.TestCase):
    def test_the_unitxp_case(self):
        """The exact scenario this product was rewritten around."""
        self.assertIs(compare("V90", "V89"), Ordering.OLDER)
        self.assertFalse(is_newer("V90", "V89"))
        self.assertIs(compare("V89", "V90"), Ordering.NEWER)
        self.assertTrue(is_newer("V89", "V90"))

    def test_numeric_not_lexical(self):
        """1.10 is newer than 1.9. String comparison says the opposite, which
        is why naive comparison is banned outright."""
        self.assertIs(compare("1.9", "1.10"), Ordering.NEWER)
        self.assertIs(compare("1.10", "1.9"), Ordering.OLDER)

    def test_zero_padding(self):
        self.assertIs(compare("1.2", "1.2.0"), Ordering.SAME)
        self.assertIs(compare("1.2", "1.2.1"), Ordering.NEWER)

    def test_same(self):
        self.assertIs(compare("v1.2.3", "1.2.3"), Ordering.SAME)
        self.assertIs(compare("V90", "90"), Ordering.SAME)

    def test_patch_bump(self):
        self.assertIs(compare("v1.2.3", "1.2.4"), Ordering.NEWER)

    def test_prerelease_loses_to_release(self):
        self.assertIs(compare("1.2.3-beta", "1.2.3"), Ordering.NEWER)
        self.assertIs(compare("1.2.3", "1.2.3-beta"), Ordering.OLDER)

    def test_two_different_prereleases_are_unknown(self):
        """Is rc2 after beta3? Usually. Not always. An update must not run on
        'usually'."""
        self.assertIs(compare("1.2.3-beta3", "1.2.3-rc2"), Ordering.UNKNOWN)

    def test_incompatible_schemes_are_unknown(self):
        """A single-number scheme and a dotted one are different numbering
        systems that both contain digits. 90 is not 'newer than' 1.2.3."""
        self.assertIs(compare("V90", "1.2.3"), Ordering.UNKNOWN)
        self.assertIs(compare("1.2.3", "V90"), Ordering.UNKNOWN)

    def test_unknown_on_either_side(self):
        self.assertIs(compare(None, "1.2"), Ordering.UNKNOWN)
        self.assertIs(compare("1.2", None), Ordering.UNKNOWN)
        self.assertIs(compare("latest", "1.2"), Ordering.UNKNOWN)

    def test_is_newer_is_false_for_everything_but_newer(self):
        """The gate an automatic update hangs off: only a proven newer remote
        opens it."""
        for local, remote in [("V90", "V89"), ("1.2", "1.2"),
                              ("1.2.3", "V90"), (None, "1.2"),
                              ("1.2", None), ("1.2", "latest")]:
            with self.subTest(local=local, remote=remote):
                self.assertFalse(is_newer(local, remote))


if __name__ == "__main__":
    unittest.main()
