"""OctoWoW forum news for the News tab: Announcements and the Changelog.

Both come straight from the public phpBB forum:

    Announcements  topic 2848  https://octowow.st/forum/viewtopic.php?t=2848
    Changelog      topic 2816  https://octowow.st/forum/viewtopic.php?t=2816

Both are threads staff post into, one post per announcement or patch, so
both are read newest-first: phpBB is asked for the topic sorted by time,
descending (``sk=t&sd=d``), one request. The Announcements panel shows the
newest post (``fetch_newest_post_in_topic``); the Changelog lists the newest
few (``fetch_topic_posts``), each with its own date, author and link.

**news.json** (https://octowow.st/news.json, the public feed OctoLauncher
reads, generated from the forum) is the Announcements' fallback while the
forum cannot be read -- typically while it shows apps its DDoS check.
``parse_news_feed`` validates it against the launcher's NewsFeedSchema; a
feed that does not match is an error, never content.

The forum-listing readers below (``fetch_forum_topics``, ``fetch_latest_post``,
``fetch_topic_list``) are what the panels used before the threads; they
remain, tested, but nothing on screen uses them now.

Two steps, as a person reading the forum would take them:

1. ``fetch_forum_topics`` reads the forum listing and returns every topic row
   with its id, title, author and *creation* date, newest first. Pinned and
   announcement rows sit at the top of a phpBB listing whatever their age, and
   the "Last post" column moves an old topic up whenever someone replies, so
   neither the row order nor the last-post date says which topic is newest.
   Only the date the topic was started does.
2. ``fetch_first_post`` opens a topic and returns its first post -- the
   announcement itself -- never the replies beneath it.

The Changelog list is ``fetch_topic_list(4)``: one listing, nothing else.

The approach follows OctoBot's ``octotracker/announcements.py``: ``a.topictitle``
links, the topic id from ``t=``, the first ``.post``'s ``.content`` with quotes
and signatures dropped, and browser-verification detection. It differs where
OctoBot reads the first ``<time>`` and username in a row's ``.list-inner``:
on phpBB 3.3 that is the hidden mobile "Last post by ..." line, i.e. the
latest *reply*. Here the last-post parts of a row are skipped.

``octonews.php`` is not used. (``news.json`` once held two posts from April
2026; it is now generated from the forum, and is only a fallback here.)

**Every failure says which stage failed.** A listing with no topics is an
error, not an empty news feed: the forum always has topics, so zero means the
page was not the forum. That is what happens while the site's DDoS protection
(BlazingFast) answers non-browser clients with a JavaScript "Just a moment
please..." check -- HTTP 200, no forum in it -- which is named as such rather
than reported as "no topics". It is detected, never solved or evaded.

Pure parsing is separate from fetching so it is tested without a network.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

from .i18n import N_

BASE = "https://octowow.st/forum/"
ANNOUNCEMENTS_FORUM_ID = 2
#: OctoWoW's announcements thread; the panel shows its newest post.
ANNOUNCEMENTS_TOPIC_ID = 2848
#: OctoWoW's patch notes thread; the Changelog lists its newest posts.
PATCH_NOTES_TOPIC_ID = 2816
CHANGELOG_FORUM_ID = 4
#: The public news feed OctoLauncher reads (generated from the forum; no
#: sign-in). The Announcements' fallback while the forum is unreadable.
NEWS_FEED_URL = "https://octowow.st/news.json"

_HTML_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"
_JSON_ACCEPT = "application/json"


# ──────────────────────────────────────────────────────────────────────────────
#  Results and errors
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TopicRow:
    """One topic as the forum listing shows it."""
    topic_id: int
    title: str
    author: str | None
    created_at: datetime | None     # when the topic was started, UTC
    url: str                        # canonical, no session id
    kind: str = "normal"            # normal | sticky | announce

    def to_item(self) -> dict:
        """A list entry: no body, because a list needs none."""
        return {"id": str(self.topic_id), "title": self.title,
                "author": self.author, "date": _iso(self.created_at),
                "body": "", "html": "", "url": self.url}


@dataclass(frozen=True)
class ForumPost:
    """A topic's first post: what the News tab shows."""
    topic_id: int
    title: str
    author: str | None
    created_at: str                 # ISO 8601, or "" if the forum gave none
    url: str
    content: str

    def to_item(self) -> dict:
        """The dict shape the News renderer and the config cache use."""
        return {"id": str(self.topic_id), "title": self.title,
                "author": self.author, "date": self.created_at,
                "body": self.content, "html": self.content, "url": self.url}


class ForumError(RuntimeError):
    """A news fetch failed, and at which stage.

    ``short`` is a line fit for the News panel; ``str()`` carries the stage
    and URL for the log."""

    def __init__(self, stage: str, url: str, message: str, short: str = ""):
        super().__init__(f"{stage} failed: {message} [{url}]")
        self.stage, self.url, self.message = stage, url, message
        self.short = short or message


class ForumBlockedError(ForumError):
    """The site answered with its anti-bot check instead of the forum."""


# ──────────────────────────────────────────────────────────────────────────────
#  URLs
# ──────────────────────────────────────────────────────────────────────────────

def forum_url(forum_id: int, base: str = BASE) -> str:
    """A forum's listing, newest *created* topics first (phpBB's ``sk=tt``).
    Stickies still come first; ``newest_first`` puts them in their place."""
    return f"{base}viewforum.php?f={int(forum_id)}&sk=tt&sd=d"


def topic_url(topic_id: int, base: str = BASE) -> str:
    """The canonical address of a topic: no ``sid``, no forum id, page one,
    so its first post is the topic's opening post."""
    return f"{base}viewtopic.php?t={int(topic_id)}"


def newest_first_topic_url(topic_id: int, base: str = BASE) -> str:
    """A topic's first page with its posts sorted by time, newest first:
    the first post on it is the topic's latest."""
    return f"{base}viewtopic.php?t={int(topic_id)}&sk=t&sd=d"


def post_url(post_id: int, base: str = BASE) -> str:
    """The canonical address of one post, wherever it sits in its topic."""
    return f"{base}viewtopic.php?p={int(post_id)}#p{int(post_id)}"


def topic_id_from_href(href: str, base: str = BASE) -> int | None:
    """The topic id in a phpBB link, whether it is relative (``./viewtopic``),
    carries a session id, or uses an SEO-style ``topic123.html`` path."""
    if not href:
        return None
    absolute = urljoin(base, unescape(href))
    parts = urlparse(absolute)
    if "viewtopic" in parts.path:
        raw = (parse_qs(parts.query).get("t") or [""])[0]
        return int(raw) if raw.isdigit() else None
    m = re.search(r"topic(\d+)", parts.path)
    return int(m.group(1)) if m else None


# ──────────────────────────────────────────────────────────────────────────────
#  Dates
# ──────────────────────────────────────────────────────────────────────────────

_TEXT_DATE_FORMATS = (
    "%a %b %d, %Y %I:%M %p",    # phpBB default: Thu Sep 24, 2026 10:15 am
    "%a %b %d, %Y %H:%M",
    "%b %d, %Y %I:%M %p",
    "%d %b %Y, %H:%M",
    "%d %b %Y %H:%M",
    "%a %d %b, %Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M",
)


def parse_forum_date(value: str | None) -> datetime | None:
    """A phpBB date as an aware UTC datetime, or None.

    ``<time datetime>`` carries ISO 8601 with an offset. Older templates
    print only the board-formatted text; the common formats are tried and
    read as UTC, which is only ever used to order topics of one forum."""
    if not value:
        return None
    value = " ".join(unescape(value).split())
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        text = re.sub(r"\b(am|pm)\b", lambda m: m.group(1).upper(), value, flags=re.I)
        for fmt in _TEXT_DATE_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


# ──────────────────────────────────────────────────────────────────────────────
#  Anti-bot check
# ──────────────────────────────────────────────────────────────────────────────

def is_challenge_page(body: str, headers=None) -> bool:
    """Whether a response is a DDoS-protection interstitial, not the forum.

    BlazingFast marks it with an ``X-BF-Challenge`` header and serves it with
    HTTP 200, so the status code alone says nothing."""
    try:
        if headers is not None and headers.get("X-BF-Challenge"):
            return True
    except Exception:
        pass
    head = (body or "")[:4000].casefold()
    return any(marker in head for marker in (
        "<title>just a moment",           # BlazingFast, Cloudflare
        "verifying your browser",         # OctoBot's list
        "cf-chl-", "challenge-platform",  # Cloudflare
        "bf.jquery",                      # BlazingFast's challenge script
    ))


# ──────────────────────────────────────────────────────────────────────────────
#  Parsing: forum listing
# ──────────────────────────────────────────────────────────────────────────────

def _classes(attrs) -> set:
    return set((dict(attrs).get("class") or "").split())


class _ForumListParser(HTMLParser):
    """Topic rows from a phpBB (prosilver-family) forum listing.

    A row is ``<li class="row ...">``. Inside it the topic link is
    ``a.topictitle``; the starter and start date follow it ("by X » date",
    in a ``<time>`` on phpBB 3.3, as text on older boards). The last-post
    column (``dd.lastpost``) and its mobile copy (``.responsive-show``) carry
    a *reply's* author and date, and are ignored."""

    _IGNORE = ("lastpost", "responsive-show", "pagination")

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.rows: list[TopicRow] = []
        self._row = None          # dict while inside a row
        self._row_depth = 0
        self._ignore_depth = 0    # >0 while inside a last-post block
        self._ignore_tag = None
        self._in_title = False
        self._in_user = False

    def handle_starttag(self, tag, attrs):
        cls = _classes(attrs)
        a = dict(attrs)
        if self._row is None:
            if tag == "li" and "row" in cls:
                kind = ("announce" if cls & {"announce", "global-announce"}
                        else "sticky" if "sticky" in cls else "normal")
                self._row = {"kind": kind, "title": [], "href": "",
                             "author": None, "time": None, "text": [],
                             "in_dt": True}
                self._row_depth = 1
            return

        if tag == "li":
            self._row_depth += 1
        if tag == "dd":
            self._row["in_dt"] = False     # replies/views/last-post columns
        if self._ignore_depth:
            if tag == self._ignore_tag:
                self._ignore_depth += 1
            return
        if any(c in cls or any(x.startswith(c) for x in cls) for c in self._IGNORE):
            self._ignore_tag, self._ignore_depth = tag, 1
            return

        if tag == "a" and "topictitle" in cls and not self._row["href"]:
            self._row["href"] = a.get("href") or ""
            self._in_title = True
        elif (tag in ("a", "span") and self._row["href"]
              and self._row["author"] is None
              and any(c.startswith("username") for c in cls)):
            self._in_user = True
            self._row["author"] = ""
        elif tag == "time" and self._row["time"] is None and self._row["href"]:
            self._row["time"] = a.get("datetime") or ""

    def handle_data(self, data):
        if self._row is None or self._ignore_depth:
            return
        if self._in_title:
            self._row["title"].append(data)
        elif self._in_user:
            self._row["author"] += data
        elif self._row["href"] and self._row["in_dt"]:
            self._row["text"].append(data)

    def handle_endtag(self, tag):
        if self._row is None:
            return
        if self._ignore_depth and tag == self._ignore_tag:
            self._ignore_depth -= 1
        if tag in ("a", "span"):
            self._in_title = self._in_user = False
        if tag == "li":
            self._row_depth -= 1
            if self._row_depth == 0:
                self._finish_row()

    def _finish_row(self):
        r, self._row = self._row, None
        self._ignore_depth = 0
        tid = topic_id_from_href(r["href"], self.base_url)
        title = " ".join("".join(r["title"]).split())
        if not tid or not title or any(x.topic_id == tid for x in self.rows):
            return
        created = parse_forum_date(r["time"])
        if created is None:
            # "by X » Thu Sep 24, 2026 10:15 am" with no <time> element.
            text = " ".join("".join(r["text"]).split())
            m = re.search(r"[»›]\s*(.+?)\s*(?:$|[»›])", text)
            created = parse_forum_date(m.group(1)) if m else None
        author = " ".join((r["author"] or "").split()) or None
        self.rows.append(TopicRow(tid, title, author, created,
                                  topic_url(tid, BASE), r["kind"]))


def parse_forum_topics(html: str, base_url: str = BASE) -> list[TopicRow]:
    """Every topic row on a listing page, in page order."""
    p = _ForumListParser(base_url)
    p.feed(html or "")
    p.close()
    return p.rows


def newest_first(rows: list[TopicRow]) -> list[TopicRow]:
    """Newest *started* topic first. Pinned rows get no special treatment,
    and the last-post date is never consulted. A row whose start date could
    not be read sorts after dated ones, by topic id (phpBB allocates ids in
    creation order)."""
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(rows, key=lambda r: (r.created_at is not None,
                                       r.created_at or floor, r.topic_id),
                  reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Parsing: first post of a topic
# ──────────────────────────────────────────────────────────────────────────────

_BLOCK_TAGS = ("p", "div", "li", "ul", "ol", "blockquote", "pre", "tr",
               "h1", "h2", "h3", "h4", "h5", "h6")


class _FirstPostParser(HTMLParser):
    """The first ``div.post`` on a topic page: its author, date and body.

    Anchored on the post container (``id="p<N>"``), so nothing outside it --
    forum rules, notices, the replies after it -- can be mistaken for it."""

    #: Not the author's own words: quoted text, signatures, post buttons,
    #: scripts. OctoBot drops the same set.
    _DROP_TAGS = {"script", "style", "blockquote"}
    _DROP_CLASSES = {"quote", "signature", "post-buttons"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.author: str | None = None
        self.time: str | None = None
        self.parts: list[str] = []
        self.found = False
        self.post_id: int | None = None
        self.subject: str | None = None
        self._in_subject = False
        self._post_depth = 0       # div depth inside the first post
        self._done = False
        self._author_depth = 0     # inside p.author
        self._in_user = False
        self._content_depth = 0    # div depth inside div.content
        self._drop_tag = None      # inside something that is not the post's
        self._drop_depth = 0       # own words: script, quote, signature

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        cls = _classes(attrs)
        a = dict(attrs)
        if self._post_depth == 0:
            if (tag == "div" and "post" in cls
                    and re.fullmatch(r"p\d+", a.get("id") or "")):
                self._post_depth = 1
                self.found = True
                self.post_id = int(a["id"][1:])
            return
        if tag == "div":
            self._post_depth += 1
        if self._drop_depth:
            if tag == self._drop_tag:
                self._drop_depth += 1
            return
        if tag in self._DROP_TAGS or cls & self._DROP_CLASSES:
            self._drop_tag, self._drop_depth = tag, 1
            return

        if self._content_depth:
            if tag == "div":
                self._content_depth += 1
            if tag == "br":
                self.parts.append("\n")
            elif tag == "li":
                self.parts.append("\n• ")
            elif tag in _BLOCK_TAGS:
                self.parts.append("\n")
            elif tag == "img" and a.get("alt") and "smilies" not in (a.get("src") or ""):
                self.parts.append(a["alt"])
            return

        if tag == "h3" and self.subject is None:
            self._in_subject = True
            self.subject = ""
        elif tag == "p" and "author" in cls:
            self._author_depth = 1
        elif self._author_depth:
            if tag == "p":
                self._author_depth += 1
            if tag == "a" and self.author is None and any(
                    c.startswith("username") for c in cls):
                self._in_user = True
                self.author = ""
            if tag == "time" and self.time is None:
                self.time = a.get("datetime") or ""
        elif tag == "div" and "content" in cls:
            self._content_depth = 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "img"):
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self._done or self._drop_depth or not self._post_depth:
            return
        if self._content_depth:
            self.parts.append(data)
        elif self._in_subject:
            self.subject += data
        elif self._in_user:
            self.author += data

    def handle_endtag(self, tag):
        if self._done or not self._post_depth:
            return
        if self._drop_depth:
            if tag == "div":
                self._post_depth -= 1
            if tag == self._drop_tag:
                self._drop_depth -= 1
            return
        if self._content_depth:
            if tag in _BLOCK_TAGS:
                self.parts.append("\n")
            if tag == "div":
                self._content_depth -= 1
        if tag == "h3":
            self._in_subject = False
        if self._author_depth:
            if tag == "a":
                self._in_user = False
            if tag == "p":
                self._author_depth -= 1
        if tag == "div":
            self._post_depth -= 1
            if self._post_depth == 0:
                self._done = True

    def content(self) -> str:
        text = "".join(self.parts).replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" ?\n ?", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_first_post(html: str) -> tuple[str | None, datetime | None, str] | None:
    """(author, created, content) of the first post on a topic page, or None
    if the page has no post in it."""
    p = _FirstPostParser()
    p.feed(html or "")
    p.close()
    if not p.found:
        return None
    author = " ".join((p.author or "").split()) or None
    return author, parse_forum_date(p.time), p.content()


# ──────────────────────────────────────────────────────────────────────────────
#  Fetching
# ──────────────────────────────────────────────────────────────────────────────

def _get(url: str, stage: str, *, opener, user_agent: str, timeout: int,
         accept: str = _HTML_ACCEPT) -> str:
    """GET ``url`` as text. Raises ForumError naming ``stage`` on anything
    that is not the page asked for."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                               "Accept": accept})
    try:
        with opener(req, timeout=timeout) as resp:
            raw = resp.read()
            headers = resp.headers
            charset = "utf-8"
            try:
                charset = headers.get_content_charset() or charset
            except Exception:
                pass
    except Exception as exc:
        code = getattr(exc, "code", None)
        why = f"HTTP {code}" if code else f"{type(exc).__name__}: {exc}"
        raise ForumError(stage, url, why,
                         short=N_("octowow.st could not be reached")) from exc
    body = raw.decode(charset, errors="replace")
    if is_challenge_page(body, headers):
        raise ForumBlockedError(
            stage, url,
            "the site answered with its DDoS-protection check (BlazingFast "
            "'Just a moment please...') instead of the forum; it admits "
            "browsers only",
            short=N_("octowow.st is showing its DDoS-protection check to apps "
                  "right now"))
    return body


def fetch_forum_topics(forum_id: int, *, opener, user_agent: str,
                       timeout: int = 8, base: str = BASE) -> list[TopicRow]:
    """Every topic on the first page of a forum, newest-started first."""
    url = forum_url(forum_id, base)
    html = _get(url, f"forum {forum_id} listing", opener=opener,
                user_agent=user_agent, timeout=timeout)
    rows = parse_forum_topics(html, url)
    if not rows:
        raise ForumError(f"forum {forum_id} listing parse", url,
                         "no topic rows found; the page is not a phpBB "
                         "listing or its markup has changed",
                         short=N_("the forum page could not be read"))
    return newest_first(rows)


def fetch_first_post(topic: TopicRow, *, opener, user_agent: str,
                     timeout: int = 8, base: str = BASE) -> ForumPost:
    """The opening post of ``topic``: one request."""
    url = topic_url(topic.topic_id, base)
    html = _get(url, f"topic {topic.topic_id}", opener=opener,
                user_agent=user_agent, timeout=timeout)
    parsed = parse_first_post(html)
    if parsed is None:
        raise ForumError(f"topic {topic.topic_id} parse", url,
                         "no post found on the topic page",
                         short=N_("the forum topic could not be read"))
    author, created, content = parsed
    return ForumPost(topic.topic_id, topic.title, topic.author or author,
                     _iso(topic.created_at or created), topic.url, content)


def fetch_latest_post(forum_id: int, *, opener, user_agent: str,
                      timeout: int = 8) -> ForumPost:
    """The newest-started topic of a forum, with its opening post: the
    listing, then that one topic page. Two requests."""
    newest = fetch_forum_topics(forum_id, opener=opener,
                                user_agent=user_agent, timeout=timeout)[0]
    return fetch_first_post(newest, opener=opener, user_agent=user_agent,
                            timeout=timeout)


def fetch_topic_list(forum_id: int, limit: int, *, opener, user_agent: str,
                     timeout: int = 8) -> list[TopicRow]:
    """The ``limit`` newest-started topics of a forum. One request."""
    return fetch_forum_topics(forum_id, opener=opener, user_agent=user_agent,
                              timeout=timeout)[:max(1, int(limit))]


def fetch_newest_post_in_topic(topic_id: int, *, opener, user_agent: str,
                               timeout: int = 8, base: str = BASE) -> ForumPost:
    """The newest post of a topic -- an announcements thread -- with its
    own date, author and link (titled as in fetch_topic_posts). One request."""
    return fetch_topic_posts(topic_id, 1, opener=opener, user_agent=user_agent,
                             timeout=timeout, base=base)[0]


_POST_START = re.compile(r'<div\b[^>]*\bid="p\d+"[^>]*>')


def parse_topic_posts(html: str) -> list:
    """Every post on a topic page, in page order, as (post id, subject,
    author, created, content, is_reply). Each post is read by the same
    parser as a topic's opening post, from where it starts."""
    html = html or ""
    starts = [m.start() for m in _POST_START.finditer(html)]
    out = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html)
        p = _FirstPostParser()
        p.feed(html[start:end])
        p.close()
        if not p.found:
            continue
        raw = " ".join((p.subject or "").split())
        reply = bool(re.match(r"^Re:", raw, re.I))
        subject = re.sub(r"^Re:\s*", "", raw, flags=re.I)
        author = " ".join((p.author or "").split()) or None
        out.append((p.post_id, subject, author, parse_forum_date(p.time),
                    p.content(), reply))
    return out


def fetch_topic_posts(topic_id: int, limit: int, *, opener, user_agent: str,
                      timeout: int = 8, base: str = BASE) -> list[ForumPost]:
    """The ``limit`` newest posts of a topic -- a patch notes thread --
    newest first. One request. A reply's own subject is only "Re: <topic>",
    so it is titled by its first line instead, and the rest is its body."""
    url = newest_first_topic_url(topic_id, base)
    html = _get(url, f"topic {topic_id}", opener=opener,
                user_agent=user_agent, timeout=timeout)
    posts = parse_topic_posts(html)
    if not posts:
        raise ForumError(f"topic {topic_id} parse", url,
                         "no post found on the topic page",
                         short=N_("the forum topic could not be read"))
    out = []
    for post_id, subject, author, created, content, reply in posts[:max(1, int(limit))]:
        title, body = subject, content
        if reply and content:
            first, _, rest = content.partition("\n")
            title, body = first.strip()[:90] or subject, rest.strip()
        link = post_url(post_id, base) if post_id else topic_url(topic_id, base)
        out.append(ForumPost(topic_id, title, author, _iso(created), link, body))
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  news.json
# ──────────────────────────────────────────────────────────────────────────────

_REQUIRED = ("id", "title", "date", "body")


def _absolute_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlparse(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def parse_news_feed(text: str, url: str = NEWS_FEED_URL) -> list[dict]:
    """news.json's items as News items, in the feed's order (newest first).

    The contract is OctoLauncher's NewsFeedSchema: an object whose ``items``
    is a list; each item has string ``id``, ``title``, ``date`` and ``body``
    (plain text), ``author`` a string, null or absent, and ``url`` absent or
    an absolute http(s) URL. Anything else raises ForumError -- the whole
    feed, as the launcher rejects it -- so a bad feed never becomes content
    or replaces the last good one. Missing optional values stay missing."""
    stage = "news.json parse"
    short = N_("the news feed was malformed")

    def bad(why):
        return ForumError(stage, url, why, short=short)

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise bad(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise bad("expected an object with an 'items' list")
    out = []
    for n, item in enumerate(data["items"]):
        if not isinstance(item, dict):
            raise bad(f"item {n} is not an object")
        for key in _REQUIRED:
            if not isinstance(item.get(key), str):
                raise bad(f"item {n}: '{key}' missing or not a string")
        author = item.get("author")
        if author is not None and not isinstance(author, str):
            raise bad(f"item {n}: 'author' is not a string")
        link = item.get("url")
        if link is not None and not _absolute_url(link):
            raise bad(f"item {n}: 'url' is not an absolute http(s) URL")
        out.append({"id": item["id"], "title": item["title"],
                    "date": item["date"], "body": item["body"], "html": "",
                    "author": author, "url": link})
    return out


def fetch_news_feed(*, opener, user_agent: str, timeout: int = 8,
                    url: str = NEWS_FEED_URL) -> list[dict]:
    """GET news.json and validate it (parse_news_feed). One request; the
    DDoS-protection page is ForumBlockedError, as on the forum."""
    body = _get(url, "news.json", opener=opener, user_agent=user_agent,
                timeout=timeout, accept=_JSON_ACCEPT)
    return parse_news_feed(body, url)
