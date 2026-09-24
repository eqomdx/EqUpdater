"""Texture packs: linking a manually installed pack to its source, and what
may be done to it afterwards.

The rule under test: a pack is only ever updated on proof. Proof that it is
the bytes its source sent (it was installed from there, or it matched when
linked), and proof that the source now publishes something else. A pack
that merely *differs* from a source is never replaced without the user
choosing to.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater import mpq                                   # noqa: E402
from equpdater.mpq import Remote                            # noqa: E402

A, B, C = "a" * 64, "b" * 64, "c" * 64
GH = {"kind": "github_release", "owner": "o", "repo": "r", "asset": None}


class TestParseSource(unittest.TestCase):
    def test_a_repository(self):
        self.assertEqual(mpq.parse_source("https://github.com/o/r"), GH)
        self.assertEqual(mpq.parse_source("https://github.com/o/r/releases"), GH)
        self.assertEqual(mpq.parse_source(" https://github.com/o/r.git "), GH)

    def test_a_release_download_names_its_file(self):
        src = mpq.parse_source(
            "https://github.com/o/r/releases/download/v2/patch-Z.mpq")
        self.assertEqual(src["asset"], "patch-Z.mpq")

    def test_codeberg(self):
        self.assertEqual(mpq.parse_source("https://codeberg.org/o/r")["kind"],
                         "codeberg_release")

    def test_a_direct_octowow_link(self):
        url = "https://dl.octowow.st/client/latest/Data/patch-O.mpq"
        self.assertEqual(mpq.parse_source(url), {"kind": "url", "url": url})

    def test_refusals_say_why(self):
        for bad in ("", "http://github.com/o/r", "https://github.com/o",
                    "https://github.com/o/r/blob/main/x.mpq",
                    "https://github.com/o/r/releases/download/v1/x.zip",
                    "https://example.com/patch-Z.mpq",
                    "https://dl.octowow.st/client/latest/"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mpq.parse_source(bad)


class TestPickAsset(unittest.TestCase):
    ASSETS = [{"name": "patch-Z.mpq"}, {"name": "patch-Y.MPQ"},
              {"name": "readme.txt"}]

    def test_a_named_asset(self):
        self.assertEqual(mpq.pick_asset(self.ASSETS, "PATCH-Y.mpq", "x")["name"],
                         "patch-Y.MPQ")

    def test_a_named_asset_that_is_gone(self):
        with self.assertRaises(ValueError):
            mpq.pick_asset(self.ASSETS, "patch-Q.mpq", "x")

    def test_one_mpq_is_unambiguous(self):
        self.assertEqual(mpq.pick_asset([{"name": "hd.mpq"}], None,
                                        "patch-Z.mpq")["name"], "hd.mpq")

    def test_several_resolve_by_local_name(self):
        self.assertEqual(mpq.pick_asset(self.ASSETS, None, "patch-z.mpq")["name"],
                         "patch-Z.mpq")

    def test_several_with_no_match_are_asked_not_guessed(self):
        with self.assertRaises(ValueError):
            mpq.pick_asset(self.ASSETS, None, "patch-Q.mpq")

    def test_github_digest(self):
        r = mpq.asset_remote({"id": 7, "updated_at": "t", "digest": "sha256:" + A.upper(),
                              "browser_download_url": "https://github.com/x"})
        self.assertEqual((r.sha, r.marker), (A, "7:t"))
        self.assertIsNone(mpq.asset_remote({"id": 7}).sha)


class TestLinking(unittest.TestCase):
    def test_linking_a_matching_pack_tracks_it(self):
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(A, "1:t", "u"))
        self.assertTrue(rec["managed"] and rec["adopted"] and rec["matched_source"])
        self.assertIsNone(rec["installed_by"])

    def test_linking_a_different_pack_holds_it(self):
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(B, "1:t", "u"))
        self.assertFalse(rec["matched_source"])
        self.assertIsNone(rec["release_marker"])

    def test_no_checksum_proves_nothing(self):
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(None, "1:t", "u"))
        self.assertFalse(rec["matched_source"])

    def test_legacy_records_are_catalogue_installs(self):
        self.assertEqual(mpq.source_of({"managed": True, "sha": A}, "patch-O.mpq"),
                         mpq.catalogue_source("patch-O.mpq"))
        self.assertIsNone(mpq.source_of(None, "patch-O.mpq"))
        self.assertIsNone(mpq.source_of({"managed": False}, "patch-O.mpq"))


class TestJudge(unittest.TestCase):
    def installed(self, **kw):
        return dict(mpq.installed_record(sha=A, source=GH,
                                         remote=Remote(A, "1:t", "u"),
                                         installed_by="EqUpdater"), **kw)

    def test_unlinked_is_never_touched(self):
        self.assertEqual(mpq.judge(None, A, Remote(B, None, "u")),
                         ("unmanaged", False))

    def test_an_edited_pack_is_held(self):
        self.assertEqual(mpq.judge(self.installed(), C, Remote(B, None, "u")),
                         ("modified", False))

    def test_an_unreachable_source_is_not_news(self):
        self.assertEqual(mpq.judge(self.installed(), A, None, lookup_failed=True),
                         ("unverifiable", False))

    def test_same_bytes_are_current(self):
        self.assertEqual(mpq.judge(self.installed(), A, Remote(A, None, "u")),
                         ("upToDate", False))

    def test_an_untouched_install_follows_its_source(self):
        self.assertEqual(mpq.judge(self.installed(), A, Remote(B, None, "u")),
                         ("updateAvailable", True))

    def test_a_matched_link_follows_its_source(self):
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(A, "1:t", "u"))
        self.assertEqual(mpq.judge(rec, A, Remote(B, "2:t", "u")),
                         ("updateAvailable", True))

    def test_a_link_that_never_matched_is_never_updated(self):
        """The headline case. Their pack and the source's differ; nothing in
        an MPQ says which is newer, so it is theirs to decide."""
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(B, "1:t", "u"))
        for remote in (Remote(B, "1:t", "u"), Remote(C, "2:t", "u")):
            with self.subTest(remote=remote):
                self.assertEqual(mpq.judge(rec, A, remote),
                                 ("sourceDiffers", False))

    def test_no_checksum_follows_release_identity_only_when_installed(self):
        rec = self.installed(release_marker="1:t")
        self.assertEqual(mpq.judge(rec, A, Remote(None, "1:t", "u")),
                         ("upToDate", False))
        self.assertEqual(mpq.judge(rec, A, Remote(None, "2:t", "u")),
                         ("updateAvailable", True))
        linked = mpq.linked_record(sha=A, source=GH, remote=Remote(None, "1:t", "u"))
        self.assertEqual(mpq.judge(linked, A, Remote(None, "2:t", "u")),
                         ("unconfirmed", False))

    def test_a_record_with_no_fingerprint_is_never_updated(self):
        rec = self.installed(sha=None)
        self.assertEqual(mpq.judge(rec, A, Remote(B, None, "u")),
                         ("unconfirmed", False))

    def test_legacy_catalogue_install(self):
        """Written before linking: managed, a sha, a url, nothing else."""
        rec = {"managed": True, "installed_by": "EqUpdater", "sha": A,
               "url": "https://dl.octowow.st/x/patch-O.mpq"}
        self.assertEqual(mpq.judge(rec, A, Remote(B, None, "u")),
                         ("updateAvailable", True))


class TestSettle(unittest.TestCase):
    def test_a_link_proven_identical_later_becomes_tracked(self):
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(B, "1:t", "u"))
        new = mpq.settle(rec, A, Remote(A, "2:t", "u"))
        self.assertTrue(new["matched_source"])
        self.assertEqual(mpq.judge(new, A, Remote(C, "3:t", "u")),
                         ("updateAvailable", True))

    def test_nothing_to_settle(self):
        rec = mpq.linked_record(sha=A, source=GH, remote=Remote(B, "1:t", "u"))
        self.assertIsNone(mpq.settle(rec, A, Remote(B, "1:t", "u")))
        self.assertIsNone(mpq.settle(rec, C, Remote(C, "1:t", "u")))  # edited
        self.assertIsNone(mpq.settle(None, A, Remote(A, None, "u")))


if __name__ == "__main__":
    unittest.main()
