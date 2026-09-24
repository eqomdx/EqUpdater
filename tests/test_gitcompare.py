"""Commit ancestry, with the network replaced by a table of canned answers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater.gitcompare import (Ancestry, ancestry, parse_repo,  # noqa: E402
                                  same_repo, short)

OLD, NEW = "a" * 40, "b" * 40


class TestParseRepo(unittest.TestCase):
    def test_shapes(self):
        for url in ["https://github.com/owner/repo",
                    "https://github.com/owner/repo.git",
                    "https://github.com/owner/repo/",
                    "http://www.github.com/owner/repo"]:
            with self.subTest(url=url):
                self.assertEqual(parse_repo(url), ("github.com", "owner", "repo"))

    def test_not_a_repo(self):
        self.assertIsNone(parse_repo(""))
        self.assertIsNone(parse_repo("https://github.com/owner"))


class TestSameRepo(unittest.TestCase):
    def test_spelling_variants_are_the_same_repo(self):
        self.assertTrue(same_repo("https://github.com/Owner/Repo.git",
                                  "https://github.com/owner/repo/"))

    def test_different_owner_is_a_different_repo(self):
        """A fork is a different addon that happens to share a folder name."""
        self.assertFalse(same_repo("https://github.com/a/repo",
                                   "https://github.com/b/repo"))

    def test_different_host(self):
        self.assertFalse(same_repo("https://github.com/a/repo",
                                   "https://codeberg.org/a/repo"))


class TestAncestryGitHub(unittest.TestCase):
    """GitHub states the relationship outright, so one call settles it."""

    def _fetch(self, status):
        def fetch(url, timeout=10):
            return {"status": status, "ahead_by": 3}
        return fetch

    def test_each_status(self):
        for status, expected in [("ahead", Ancestry.REMOTE_AHEAD),
                                 ("behind", Ancestry.LOCAL_AHEAD),
                                 ("identical", Ancestry.IDENTICAL),
                                 ("diverged", Ancestry.DIVERGED)]:
            with self.subTest(status=status):
                self.assertIs(
                    ancestry("https://github.com/o/r", OLD, NEW,
                             fetch=self._fetch(status)), expected)

    def test_unrecognised_status_is_unknown(self):
        self.assertIs(ancestry("https://github.com/o/r", OLD, NEW,
                               fetch=self._fetch("wat")), Ancestry.UNKNOWN)


class TestAncestryGitea(unittest.TestCase):
    """Codeberg answers with commit counts, so it takes two calls: what does
    the remote have that we don't, and what do we have that it doesn't."""

    def _fetch(self, forward, reverse):
        def fetch(url, timeout=10):
            # the forward call asks base...head, the reverse head...base
            return {"total_commits": forward if f"{OLD}...{NEW}" in url
                    else reverse}
        return fetch

    def test_remote_ahead(self):
        self.assertIs(ancestry("https://codeberg.org/o/r", OLD, NEW,
                               fetch=self._fetch(4, 0)), Ancestry.REMOTE_AHEAD)

    def test_local_ahead(self):
        self.assertIs(ancestry("https://codeberg.org/o/r", OLD, NEW,
                               fetch=self._fetch(0, 4)), Ancestry.LOCAL_AHEAD)

    def test_diverged(self):
        """Both sides carry commits the other does not: a rebase, a fork, or
        another branch. Never an update."""
        self.assertIs(ancestry("https://codeberg.org/o/r", OLD, NEW,
                               fetch=self._fetch(2, 3)), Ancestry.DIVERGED)

    def test_identical_history(self):
        self.assertIs(ancestry("https://codeberg.org/o/r", OLD, NEW,
                               fetch=self._fetch(0, 0)), Ancestry.IDENTICAL)


class TestAncestryFailsSafe(unittest.TestCase):
    """Every way this can go wrong answers UNKNOWN, because its answer
    authorises an overwrite."""

    def test_same_sha_needs_no_network(self):
        def boom(url, timeout=10):
            raise AssertionError("should not be called")
        self.assertIs(ancestry("https://github.com/o/r", OLD, OLD,
                               fetch=boom), Ancestry.IDENTICAL)

    def test_missing_shas(self):
        self.assertIs(ancestry("https://github.com/o/r", None, NEW),
                      Ancestry.UNKNOWN)
        self.assertIs(ancestry("https://github.com/o/r", OLD, None),
                      Ancestry.UNKNOWN)

    def test_unsupported_host(self):
        """An unknown host is not an error -- it just cannot be asked, and
        that protects the files rather than risking them."""
        self.assertIs(ancestry("https://git.example.com/o/r", OLD, NEW),
                      Ancestry.UNKNOWN)

    def test_network_failure(self):
        def fetch(url, timeout=10):
            raise OSError("no route to host")
        self.assertIs(ancestry("https://github.com/o/r", OLD, NEW,
                               fetch=fetch), Ancestry.UNKNOWN)

    def test_second_call_failing(self):
        """A force-push can delete the commit we hold; the reverse lookup 404s
        where the forward one worked."""
        calls = []

        def fetch(url, timeout=10):
            calls.append(url)
            if len(calls) == 1:
                return {"total_commits": 2}
            raise OSError("404")
        self.assertIs(ancestry("https://codeberg.org/o/r", OLD, NEW,
                               fetch=fetch), Ancestry.UNKNOWN)

    def test_garbage_payload(self):
        self.assertIs(ancestry("https://codeberg.org/o/r", OLD, NEW,
                               fetch=lambda u, timeout=10: {}),
                      Ancestry.UNKNOWN)


class TestShort(unittest.TestCase):
    def test(self):
        self.assertEqual(short("abcdef1234567"), "abcdef1")
        self.assertEqual(short(None), "")


if __name__ == "__main__":
    unittest.main()
