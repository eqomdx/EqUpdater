"""Git hosts, OctoWoW Git included: a Gitea mounted under a path prefix.

OctoWoW's Gitea lives at https://octowow.st/git/, so its repositories are
/git/<owner>/<repo> and its API /git/api/v1. Everything that reads a
repository URL goes through gitcompare's host registry; these tests hold
OctoWoW Git to what every other host already does, and every other host to
what it did before.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater import gitcompare, mpq                                # noqa: E402
from equpdater.gitcompare import (Ancestry, GitHost, ancestry,       # noqa: E402
                                  compare_urls, parse_repo, repo_ref,
                                  same_repo)

OLD, NEW = "a" * 40, "b" * 40
REPO = "https://octowow.st/git/Dusk/GitAddonsManager"
API = "https://octowow.st/git/api/v1/repos/Dusk/GitAddonsManager"


class TestParsing(unittest.TestCase):
    def test_an_octowow_git_url(self):
        self.assertEqual(parse_repo(REPO),
                         ("octowow.st", "Dusk", "GitAddonsManager"))
        ref = repo_ref(REPO)
        self.assertEqual(ref.forge.name, "OctoWoW Git")
        self.assertEqual(ref.forge.kind, "gitea")
        self.assertEqual(ref.url, REPO)

    def test_git_suffix_and_trailing_slash(self):
        for url in (REPO + ".git", REPO + "/", REPO + ".git/",
                    "https://www.octowow.st/git/Dusk/GitAddonsManager",
                    "https://OCTOWOW.ST/Git/Dusk/GitAddonsManager"):
            with self.subTest(url=url):
                self.assertEqual(parse_repo(url),
                                 ("octowow.st", "Dusk", "GitAddonsManager"))
                self.assertEqual(repo_ref(url).url, REPO)

    def test_not_a_repository(self):
        for url in ("https://octowow.st/Dusk/GitAddonsManager",   # no /git/
                    "https://octowow.st/git/Dusk",                # owner only
                    "https://octowow.st/git/",
                    REPO + "/src/branch/main",                    # a page in it
                    "https://dl.octowow.st/git/Dusk/GitAddonsManager"):
            with self.subTest(url=url):
                self.assertIsNone(parse_repo(url))

    def test_a_prefixed_gitea_is_one_registry_entry(self):
        """Any Gitea under a path prefix, not just OctoWoW's: no special case
        anywhere else."""
        hosts = (GitHost("Forge", "example.org", "gitea", prefix="code/git"),)
        ref = repo_ref("https://example.org/code/git/me/thing.git", hosts)
        self.assertEqual((ref.host, ref.owner, ref.repo),
                         ("example.org", "me", "thing"))
        self.assertEqual(ref.url, "https://example.org/code/git/me/thing")
        self.assertEqual(ref.forge.api, "https://example.org/code/git/api/v1")
        self.assertIsNone(repo_ref("https://example.org/me/thing", hosts))


class TestSameRepo(unittest.TestCase):
    def test_spellings_of_one_octowow_repository(self):
        for other in (REPO + ".git", REPO + "/",
                      "https://octowow.st/git/dusk/gitaddonsmanager",
                      "http://www.octowow.st/git/Dusk/GitAddonsManager.git"):
            with self.subTest(other=other):
                self.assertTrue(same_repo(REPO, other))

    def test_same_names_elsewhere_are_different_repositories(self):
        self.assertFalse(same_repo(REPO, "https://codeberg.org/Dusk/GitAddonsManager"))
        self.assertFalse(same_repo(REPO, "https://github.com/Dusk/GitAddonsManager"))
        self.assertFalse(same_repo(REPO, "https://octowow.st/git/Other/GitAddonsManager"))


class TestCompare(unittest.TestCase):
    def test_octowow_compare_urls(self):
        forward, reverse, _reader = compare_urls(REPO + ".git", OLD, NEW)
        self.assertEqual(forward, f"{API}/compare/{OLD}...{NEW}")
        self.assertEqual(reverse, f"{API}/compare/{NEW}...{OLD}")

    def _fetch(self, forward, reverse, seen):
        def fetch(url, timeout=10):
            seen.append(url)
            return {"total_commits": forward if f"{OLD}...{NEW}" in url
                    else reverse}
        return fetch

    def test_gitea_ancestry_answers(self):
        for counts, expected in (((3, 0), Ancestry.REMOTE_AHEAD),
                                 ((0, 3), Ancestry.LOCAL_AHEAD),
                                 ((2, 5), Ancestry.DIVERGED),
                                 ((0, 0), Ancestry.IDENTICAL)):
            seen = []
            with self.subTest(counts=counts):
                self.assertIs(ancestry(REPO, OLD, NEW,
                                       fetch=self._fetch(*counts, seen)),
                              expected)
                self.assertTrue(all(u.startswith(API + "/compare/") for u in seen))

    def test_a_ddos_page_answers_unknown(self):
        """What octowow.st sends apps today: never grounds for replacing."""
        def fetch(url, timeout=10):
            raise RuntimeError("challenge page")
        self.assertIs(ancestry(REPO, OLD, NEW, fetch=fetch), Ancestry.UNKNOWN)
        self.assertIs(ancestry(REPO, OLD, NEW, fetch=lambda u, timeout=10: {}),
                      Ancestry.UNKNOWN)

    def test_existing_hosts_unchanged(self):
        expected = {
            "https://github.com/o/r":
                f"https://api.github.com/repos/o/r/compare/{OLD}...{NEW}",
            "https://codeberg.org/o/r":
                f"https://codeberg.org/api/v1/repos/o/r/compare/{OLD}...{NEW}",
            "https://gitea.com/o/r":
                f"https://gitea.com/api/v1/repos/o/r/compare/{OLD}...{NEW}",
            "https://gitlab.com/o/r":
                f"https://gitlab.com/api/v4/projects/o%2Fr/repository/compare"
                f"?from={OLD}&to={NEW}",
        }
        for url, forward in expected.items():
            with self.subTest(url=url):
                self.assertEqual(compare_urls(url, OLD, NEW)[0], forward)
        self.assertEqual(parse_repo("https://github.com/owner/repo.git"),
                         ("github.com", "owner", "repo"))
        self.assertIsNone(compare_urls("https://git.example.com/o/r", OLD, NEW))


class TestAddonSources(unittest.TestCase):
    """The app side: what may be installed, from where, and how."""

    @classmethod
    def setUpClass(cls):
        from equpdater import app
        cls.app = app

    def test_octowow_git_is_an_allowed_addon_source(self):
        is_allowed = self.app.is_allowed_git_url
        for url in (REPO, REPO + ".git", REPO + "/"):
            self.assertTrue(is_allowed(url), url)
        for url in ("http://octowow.st/git/Dusk/GitAddonsManager",
                    "https://octowow.st/Dusk/GitAddonsManager",
                    "https://git.example.com/o/r"):
            self.assertFalse(is_allowed(url), url)
        self.assertTrue(is_allowed("https://github.com/shagu/ShaguDPS"))
        self.assertIn("octowow.st/git", self.app.ADDON_GIT_HOSTS)

    def test_api_and_archive_paths_carry_the_prefix(self):
        self.assertEqual(self.app._git_parts(REPO + ".git"),
                         ("gitea", REPO, "Dusk", "GitAddonsManager",
                          "https://octowow.st/git/api/v1"))
        zip_url = self.app.addon_zip_url(REPO, NEW)
        self.assertEqual(zip_url, f"{REPO}/archive/{NEW}.zip")
        self.assertIn("octowow.st", self.app.ADDON_ZIP_HOSTS)

    def test_latest_commit_is_asked_of_the_prefixed_api(self):
        asked = []

        def api_json(url, timeout=10):
            asked.append(url)
            return [{"sha": NEW}]
        with mock.patch.object(self.app, "_api_json", api_json), \
                mock.patch.object(self.app, "load_config", lambda: {}), \
                mock.patch.object(self.app, "update_config", lambda f: {}):
            sha = self.app.addon_remote_sha(REPO, force=True)
        self.assertEqual(sha, NEW)
        self.assertEqual(asked, [f"{API}/commits?limit=1"])

    def test_the_ddos_page_is_named_not_called_a_bad_archive(self):
        class Response:
            headers = {"X-BF-Challenge": "pending"}

            def read(self):
                return b"<!DOCTYPE HTML><title>Just a moment please...</title>"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch.object(self.app, "secure_urlopen",
                               lambda *a, **k: Response()), \
                mock.patch.object(self.app, "load_config", lambda: {}):
            with self.assertRaises(RuntimeError) as ctx:
                self.app.addon_remote_sha(REPO, force=True, raise_errors=True)
        self.assertEqual(str(ctx.exception), self.app.DDOS_CHECK)

    def test_held_back_states_still_hold_on_octowow_git(self):
        """Diverged, local-newer and unknown answers from OctoWoW Git hold an
        update back exactly as they do on every other host."""
        # All from the app's own imports: other test files reload the
        # equpdater modules, and an Ancestry from one load is not equal to
        # the same member from another.
        plan, Action, Ancestry = self.app.plan, self.app.Action, self.app.Ancestry
        saved = self.app.new_addon_record(managed=True, git=REPO, sha=OLD)
        for result in (Ancestry.DIVERGED, Ancestry.LOCAL_AHEAD, Ancestry.UNKNOWN):
            with self.subTest(result=result):
                comp = self.app.addon_component(
                    "GitAddonsManager", saved, installed=True, remote_sha=NEW,
                    configured_source=REPO + ".git", ancestry_result=result)
                self.assertIsNot(plan(comp).action, Action.UPDATE)
        comp = self.app.addon_component(
            "GitAddonsManager", saved, installed=True, remote_sha=NEW,
            configured_source=REPO + "/", ancestry_result=Ancestry.REMOTE_AHEAD)
        self.assertIs(plan(comp).action, Action.UPDATE)


class TestTexturePackSources(unittest.TestCase):
    def test_an_octowow_git_repository(self):
        self.assertEqual(mpq.parse_source(REPO),
                         {"kind": "gitea_release", "forge": "octowow.st/git",
                          "owner": "Dusk", "repo": "GitAddonsManager",
                          "asset": None})

    def test_an_octowow_git_release_download(self):
        src = mpq.parse_source(REPO + "/releases/download/v1/patch-Z.mpq")
        self.assertEqual(src["asset"], "patch-Z.mpq")
        self.assertEqual(mpq.describe_source(src),
                         "octowow.st/git/Dusk/GitAddonsManager · patch-Z.mpq")

    def test_a_page_inside_the_repository_is_refused(self):
        with self.assertRaises(ValueError):
            mpq.parse_source(REPO + "/src/branch/main/patch-Z.mpq")
        with self.assertRaises(ValueError):
            mpq.parse_source("https://octowow.st/git/Dusk")

    def test_direct_octowow_links_still_work(self):
        url = "https://dl.octowow.st/client/latest/Data/patch-O.mpq"
        self.assertEqual(mpq.parse_source(url), {"kind": "url", "url": url})

    def test_registry_and_release_hosts_agree(self):
        labels = {h.label for h in gitcompare.GIT_HOSTS}
        self.assertTrue(set(mpq.RELEASE_HOSTS) <= labels)


if __name__ == "__main__":
    unittest.main()
