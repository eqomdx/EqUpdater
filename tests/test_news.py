"""The News tab's forum reader.

The fixtures follow phpBB 3.3 prosilver markup: a listing where old pinned
announcements sit above newer topics, where a pinned topic has a reply newer
than everything else, where every link carries a session id, and a topic page
whose opening post is followed by replies. Those are the traps the reader has
to walk around; the fetch tests check that every failure names its stage.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater import news                                  # noqa: E402

SID = "sid=0123456789abcdef0123456789abcdef"


def row(kind, tid, title, author, created, last_by, last_at, time_tag=True):
    started = (f'<time datetime="{created}">{created}</time>' if time_tag
               else created)
    return f'''
    <li class="row bg1 {kind}">
      <dl class="row-item {kind}_read">
        <dt title="No unread posts">
          <div class="list-inner">
            <a href="./viewtopic.php?t={tid}&amp;{SID}" class="topictitle">{title}</a>
            <br />
            <div class="responsive-show" style="display: none;">
              Last post by <a href="./memberlist.php?mode=viewprofile&amp;u=9&amp;{SID}"
                 class="username">{last_by}</a> &laquo;
              <a href="./viewtopic.php?p=99&amp;{SID}#p99">
                <time datetime="{last_at}">{last_at}</time></a>
            </div>
            <div class="topic-poster responsive-hide left-box">
              by <a href="./memberlist.php?mode=viewprofile&amp;u=2&amp;{SID}"
                 style="color: #AA0000;" class="username-coloured">{author}</a>
              &raquo; {started}
            </div>
          </div>
        </dt>
        <dd class="posts">4 <dfn>Replies</dfn></dd>
        <dd class="views">900 <dfn>Views</dfn></dd>
        <dd class="lastpost">
          <span><dfn>Last post </dfn>by
            <a href="./memberlist.php?mode=viewprofile&amp;u=9&amp;{SID}"
               class="username">{last_by}</a>
            <a href="./viewtopic.php?p=99&amp;{SID}#p99" title="Go to last post">»</a>
            <br /><time datetime="{last_at}">{last_at}</time>
          </span>
        </dd>
      </dl>
    </li>'''


ANNOUNCEMENTS = f'''<!DOCTYPE html><html><head><title>Announcements - OctoWoW</title></head>
<body id="phpbb"><div class="forumbg announcement"><ul class="topiclist topics">
{row("global-announce", 12, "Server Rules", "Kestrel",
     "2026-04-02T10:00:00+00:00", "Newbie", "2026-09-24T12:30:00+00:00")}
{row("sticky", 15, "Read before posting", "Kestrel",
     "2026-04-05T10:00:00+00:00", "Someone", "2026-09-20T08:00:00+00:00")}
</ul></div><div class="forumbg"><ul class="topiclist topics">
{row("", 2595, "DDoS Updates", "Kestrel",
     "2026-09-24T07:06:00+00:00", "Kestrel", "2026-09-24T07:06:00+00:00")}
{row("", 2594, "Whitelist Updates", "Kestrel",
     "2026-09-20T18:00:00+00:00", "Player", "2026-09-23T09:00:00+00:00")}
</ul></div></body></html>'''


def topic_page(tid, title, first_body, first_author="Kestrel",
               created="2026-09-23T16:00:00+00:00"):
    reply = '''
    <div id="p{pid}" class="post has-profile bg1">
      <div class="inner"><div class="postbody"><div id="post_content{pid}">
        <h3><a href="#p{pid}">Re: {title}</a></h3>
        <p class="author"><span class="responsive-hide">by <strong>
          <a href="./memberlist.php?u=9" class="username">Replier{pid}</a></strong>
          &raquo; </span><time datetime="2026-09-24T09:00:00+00:00">x</time></p>
        <div class="content">This is reply {pid}, not the patch notes.</div>
      </div></div></div>
    </div>'''
    return f'''<!DOCTYPE html><html><body id="phpbb">
    <div class="rules"><div class="inner"><div class="content">Forum rules text</div></div></div>
    <div id="p9000" class="post has-profile bg2">
      <div class="inner"><div class="postbody"><div id="post_content9000">
        <h3 class="first"><a href="#p9000">{title}</a></h3>
        <p class="author"><a class="unread" href="#"><span class="sr-only">Post</span></a>
          <span class="responsive-hide">by <strong>
          <a href="./memberlist.php?u=2" style="color:#AA0000"
             class="username-coloured">{first_author}</a></strong> &raquo; </span>
          <time datetime="{created}">Wed Sep 23, 2026 4:00 pm</time></p>
        <div class="content">{first_body}</div>
        <div id="sig9000" class="signature">my signature</div>
      </div></div></div>
    </div>
    {reply.format(pid=9001, title=title)}
    {reply.format(pid=9002, title=title)}
    <script>var x = "<div class='content'>not this</div>";</script>
    </body></html>'''


PATCH_BODY = ('<strong>Fixes</strong><br>Fixed Onyxia breath.<br>'
              '<ul><li>Hunters: pets no longer despawn</li>'
              '<li>Mages: blink works again</li></ul>'
              '<blockquote><div><cite>Dev wrote:</cite>quoted bit</div></blockquote>')

CHALLENGE = '''<!DOCTYPE HTML><html lang="en-US"><head>
<title>Just a moment please...</title><script src="/bf.jquery.max.js"></script>
</head><body>checking your browser</body></html>'''


class TestListing(unittest.TestCase):
    def setUp(self):
        self.rows = news.parse_forum_topics(ANNOUNCEMENTS, news.forum_url(2))

    def test_every_row_is_read(self):
        self.assertEqual({r.topic_id for r in self.rows}, {12, 15, 2595, 2594})

    def test_pinned_rows_are_not_newest(self):
        """Old pinned topics head the page; the newest post is further down."""
        self.assertEqual(self.rows[0].topic_id, 12)          # page order
        newest = news.newest_first(self.rows)
        self.assertEqual([r.topic_id for r in newest], [2595, 2594, 15, 12])
        self.assertEqual(newest[0].title, "DDoS Updates")

    def test_creation_date_not_last_post(self):
        """Topic 12 had a reply today; it was still started in April."""
        r = next(r for r in self.rows if r.topic_id == 12)
        self.assertEqual(r.created_at,
                         datetime(2026, 4, 2, 10, tzinfo=timezone.utc))
        self.assertEqual(r.author, "Kestrel")                # not "Newbie"
        self.assertEqual(r.kind, "announce")

    def test_urls_are_canonical(self):
        r = next(r for r in self.rows if r.topic_id == 2595)
        self.assertEqual(r.url, "https://octowow.st/forum/viewtopic.php?t=2595")
        self.assertNotIn("sid", r.url)

    def test_text_dates_on_older_templates(self):
        html = ("<ul>" + row("", 7, "Old style", "A", "Thu Sep 24, 2026 7:06 am",
                              "B", "2026-09-25T00:00:00+00:00", time_tag=False)
                + "</ul>")
        (r,) = news.parse_forum_topics(html)
        self.assertEqual(r.created_at,
                         datetime(2026, 9, 24, 7, 6, tzinfo=timezone.utc))

    def test_undated_rows_fall_back_to_topic_id(self):
        rows = [news.TopicRow(5, "a", None, None, "u"),
                news.TopicRow(9, "b", None, None, "u"),
                news.TopicRow(1, "c", None,
                              datetime(2020, 1, 1, tzinfo=timezone.utc), "u")]
        self.assertEqual([r.topic_id for r in news.newest_first(rows)], [1, 9, 5])

    def test_topic_ids_from_every_link_style(self):
        base = news.forum_url(2)
        for href, want in (("./viewtopic.php?f=2&t=31&sid=abc", 31),
                           ("viewtopic.php?t=31&amp;sid=abc", 31),
                           ("https://octowow.st/forum/viewtopic.php?t=31", 31),
                           ("./some-title-topic31.html", 31),
                           ("./viewtopic.php?p=99#p99", None)):
            with self.subTest(href=href):
                self.assertEqual(news.topic_id_from_href(href, base), want)


class TestFirstPost(unittest.TestCase):
    def test_opening_post_only(self):
        author, created, content = news.parse_first_post(
            topic_page(2600, "2026-09-23", PATCH_BODY))
        self.assertEqual(author, "Kestrel")
        self.assertEqual(created, datetime(2026, 9, 23, 16, tzinfo=timezone.utc))
        self.assertIn("Fixed Onyxia breath.", content)
        self.assertIn("• Hunters: pets no longer despawn", content)
        self.assertIn("• Mages: blink works again", content)
        for absent in ("reply 9001", "reply 9002", "Replier", "Forum rules",
                       "my signature", "not this"):
            self.assertNotIn(absent, content)

    def test_line_breaks_survive(self):
        _, _, content = news.parse_first_post(topic_page(1, "t", PATCH_BODY))
        self.assertIn("Fixes\nFixed Onyxia breath.", content)

    def test_page_without_a_post(self):
        self.assertIsNone(news.parse_first_post("<html><body>nothing</body></html>"))


class TestChallenge(unittest.TestCase):
    def test_detected_by_header(self):
        self.assertTrue(news.is_challenge_page("", {"X-BF-Challenge": "pending"}))

    def test_detected_by_page(self):
        self.assertTrue(news.is_challenge_page(CHALLENGE))

    def test_forum_is_not_a_challenge(self):
        self.assertFalse(news.is_challenge_page(ANNOUNCEMENTS, {}))


class _Headers(dict):
    def get_content_charset(self):
        return "utf-8"


class _Resp:
    def __init__(self, body, headers=None):
        self.body = body.encode("utf-8")
        self.headers = _Headers(headers or {})

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSite:
    """A forum reachable only through `opener`, recording what was asked."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def opener(self, req, timeout):
        url = req.full_url
        self.asked.append(url)
        for key, page in self.pages.items():
            if key in url:
                if isinstance(page, Exception):
                    raise page
                return _Resp(*page) if isinstance(page, tuple) else _Resp(page)
        raise OSError("404 " + url)


def kw(site):
    return {"opener": site.opener, "user_agent": "EqUpdater/test", "timeout": 1}


CHANGELOG = ("<ul>" + row("sticky", 3, "How to report bugs", "Kestrel",
                          "2026-01-01T00:00:00+00:00", "X", "2026-09-24T11:00:00+00:00")
             + row("", 2600, "2026-09-23", "Kestrel", "2026-09-23T16:00:00+00:00",
                   "Replier9002", "2026-09-24T09:00:00+00:00")
             + row("", 2580, "2026-09-16", "Kestrel", "2026-09-16T16:00:00+00:00",
                   "Y", "2026-09-17T09:00:00+00:00") + "</ul>")


class TestFetch(unittest.TestCase):
    def test_announcement_is_the_newest_started_topic(self):
        site = FakeSite({"viewforum.php?f=2": ANNOUNCEMENTS,
                         "viewtopic.php?t=2595": topic_page(
                             2595, "DDoS Updates", "Mitigation is live.",
                             created="2026-09-24T07:06:00+00:00")})
        item = news.fetch_latest_post(2, **kw(site)).to_item()
        self.assertEqual(item["title"], "DDoS Updates")
        self.assertEqual(item["body"], "Mitigation is live.")
        self.assertEqual(item["url"], "https://octowow.st/forum/viewtopic.php?t=2595")
        self.assertEqual(item["date"], "2026-09-24T07:06:00+00:00")
        # Two requests: the listing and that one topic. Nothing else.
        self.assertEqual(site.asked, [news.forum_url(2), news.topic_url(2595)])

    def test_patch_notes_are_one_listing_request(self):
        site = FakeSite({"viewforum.php?f=4": CHANGELOG})
        rows = news.fetch_topic_list(4, 8, **kw(site))
        self.assertEqual(site.asked, [news.forum_url(4)])
        items = [r.to_item() for r in rows]
        self.assertEqual([i["title"] for i in items],
                         ["2026-09-23", "2026-09-16", "How to report bugs"])
        self.assertEqual(items[0]["author"], "Kestrel")          # not the replier
        self.assertEqual(items[0]["date"], "2026-09-23T16:00:00+00:00")
        self.assertEqual(items[0]["url"],
                         "https://octowow.st/forum/viewtopic.php?t=2600")

    def test_patch_note_limit(self):
        site = FakeSite({"viewforum.php?f=4": CHANGELOG})
        self.assertEqual(len(news.fetch_topic_list(4, 2, **kw(site))), 2)

    def test_first_post_of_a_patch_note_is_post_one(self):
        site = FakeSite({"t=2600": topic_page(2600, "2026-09-23", PATCH_BODY)})
        (row2600,) = [r for r in news.parse_forum_topics(CHANGELOG)
                      if r.topic_id == 2600]
        post = news.fetch_first_post(row2600, **kw(site))
        self.assertIn("Fixed Onyxia breath.", post.content)
        self.assertNotIn("reply", post.content)
        self.assertNotIn("quoted bit", post.content)             # quotes dropped
        self.assertEqual(post.author, "Kestrel")

    def test_listing_asks_for_creation_order(self):
        site = FakeSite({"viewforum.php?f=4": CHANGELOG})
        news.fetch_topic_list(4, 1, **kw(site))
        self.assertIn("sk=tt", site.asked[0])

    def test_challenge_is_named_not_reported_as_empty(self):
        site = FakeSite({"viewforum.php": (CHALLENGE, {"X-BF-Challenge": "pending"})})
        with self.assertRaises(news.ForumBlockedError) as cm:
            news.fetch_latest_post(2, **kw(site))
        self.assertEqual(cm.exception.stage, "forum 2 listing")
        self.assertIn("DDoS-protection", cm.exception.short)
        self.assertEqual(len(site.asked), 1)                     # no retry storm

    def test_challenge_on_the_topic_page(self):
        site = FakeSite({"viewforum.php?f=2": ANNOUNCEMENTS,
                         "viewtopic": CHALLENGE})
        with self.assertRaises(news.ForumBlockedError) as cm:
            news.fetch_latest_post(2, **kw(site))
        self.assertEqual(cm.exception.stage, "topic 2595")

    def test_a_page_with_no_topics_is_an_error(self):
        site = FakeSite({"viewforum.php": "<html><body>maintenance</body></html>"})
        with self.assertRaises(news.ForumError) as cm:
            news.fetch_topic_list(4, 8, **kw(site))
        self.assertEqual(cm.exception.stage, "forum 4 listing parse")

    def test_a_topic_page_with_no_post_is_an_error(self):
        site = FakeSite({"viewforum.php?f=2": ANNOUNCEMENTS,
                         "viewtopic": "<html><body>gone</body></html>"})
        with self.assertRaises(news.ForumError) as cm:
            news.fetch_latest_post(2, **kw(site))
        self.assertEqual(cm.exception.stage, "topic 2595 parse")

    def test_network_errors_name_the_stage(self):
        site = FakeSite({})
        with self.assertRaises(news.ForumError) as cm:
            news.fetch_latest_post(2, **kw(site))
        self.assertEqual(cm.exception.stage, "forum 2 listing")
        self.assertIn("forum 2 listing failed", str(cm.exception))

    def test_no_json_feed_is_consulted(self):
        site = FakeSite({"viewforum.php?f=4": CHANGELOG})
        news.fetch_topic_list(4, 8, **kw(site))
        self.assertFalse([u for u in site.asked
                          if "octonews" in u or u.endswith(".json")])
        self.assertFalse(hasattr(news, "OCTONEWS_URL"))


def thread_page_newest_first():
    """Topic 2848 as phpBB serves it with sk=t&sd=d: the newest post first,
    a reply ("Re: ...") by a staff member, then older posts."""
    def post(pid, subject, author, when, body):
        return f'''
    <div id="p{pid}" class="post has-profile bg1">
      <div class="inner"><div class="postbody"><div id="post_content{pid}">
        <h3><a href="./viewtopic.php?p={pid}&amp;{SID}#p{pid}">{subject}</a></h3>
        <p class="author"><span class="responsive-hide">by <strong>
          <a href="./memberlist.php?u=2" class="username-coloured">{author}</a></strong>
          &raquo; </span><time datetime="{when}">x</time></p>
        <div class="content">{body}</div>
        <div id="sig{pid}" class="signature">sig</div>
      </div></div></div>
    </div>'''
    return ("<!DOCTYPE html><html><body id=\"phpbb\">"
            "<h2 class=\"topic-title\"><a href=\"#\">Announcements</a></h2>"
            + post(31010, "Re: Announcements", "Kestrel",
                   "2026-10-09T12:00:00+00:00", "Realm restart at 18:00.<br>Thanks!")
            + post(30500, "Re: Announcements", "Octo",
                   "2026-10-01T09:00:00+00:00", "Older news.")
            + post(28480, "Announcements", "Octo",
                   "2026-06-01T09:00:00+00:00", "Thread opened.")
            + "</body></html>")


class TestAnnouncementsThread(unittest.TestCase):
    """Announcements are the newest post in topic 2848."""

    def test_newest_post_with_its_own_details(self):
        site = FakeSite({"viewtopic.php?t=2848": thread_page_newest_first()})
        item = news.fetch_newest_post_in_topic(2848, **kw(site)).to_item()
        self.assertEqual(item["title"], "Announcements")      # "Re: " dropped
        self.assertEqual(item["author"], "Kestrel")
        self.assertEqual(item["date"], "2026-10-09T12:00:00+00:00")
        self.assertEqual(item["body"], "Realm restart at 18:00.\nThanks!")
        self.assertNotIn("sig", item["body"])
        self.assertEqual(item["url"],
                         "https://octowow.st/forum/viewtopic.php?p=31010#p31010")

    def test_one_request_sorted_newest_first(self):
        site = FakeSite({"viewtopic.php?t=2848": thread_page_newest_first()})
        news.fetch_newest_post_in_topic(2848, **kw(site))
        self.assertEqual(site.asked, [
            "https://octowow.st/forum/viewtopic.php?t=2848&sk=t&sd=d"])
        self.assertEqual(news.ANNOUNCEMENTS_TOPIC_ID, 2848)

    def test_challenge_is_blocked_not_content(self):
        site = FakeSite({"viewtopic.php?t=2848": CHALLENGE})
        with self.assertRaises(news.ForumBlockedError) as cm:
            news.fetch_newest_post_in_topic(2848, **kw(site))
        self.assertEqual(cm.exception.stage, "topic 2848")

    def test_a_page_with_no_post_is_an_error(self):
        site = FakeSite({"viewtopic.php?t=2848": "<html><body>gone</body></html>"})
        with self.assertRaises(news.ForumError) as cm:
            news.fetch_newest_post_in_topic(2848, **kw(site))
        self.assertEqual(cm.exception.stage, "topic 2848 parse")

    def test_network_errors_name_the_stage(self):
        with self.assertRaises(news.ForumError) as cm:
            news.fetch_newest_post_in_topic(2848, **kw(FakeSite({})))
        self.assertEqual(cm.exception.stage, "topic 2848")

    def test_a_topic_page_still_yields_its_opening_post(self):
        """parse_first_post is unchanged by the subject/id capture."""
        page = topic_page(2600, "2026-09-23", PATCH_BODY)
        author, _created, content = news.parse_first_post(page)
        self.assertEqual(author, "Kestrel")
        self.assertIn("Fixed Onyxia breath.", content)


if __name__ == "__main__":
    unittest.main()
