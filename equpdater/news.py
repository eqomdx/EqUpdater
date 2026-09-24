"""OctoWoW news feed reader used by EqUpdater's News tab.

OctoWoW's own launcher reads the public ``octonews.php`` JSON endpoint.  Use
that machine-readable feed first; it is substantially more reliable than
scraping phpBB markup and does not depend on theme class names.  Direct forum
HTML remains a fallback so News can survive a feed outage/schema change.

Forum 2 is Announcements and forum 4 is Patch Notes and Changelog.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlparse, parse_qs
import urllib.request

BASE = "https://octowow.st/forum/"
OCTONEWS_URL = urljoin(BASE, "octonews.php")
ANNOUNCEMENTS_FORUM_ID = 2
CHANGELOG_FORUM_ID = 4


@dataclass(frozen=True)
class TopicLink:
    id: int
    title: str
    url: str


class _TopicListParser(HTMLParser):
    """Very forgiving phpBB topic-link parser used only as a fallback."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.items: list[TopicLink] = []
        self._capture = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        a = dict(attrs)
        href = a.get("href") or ""
        classes = set((a.get("class") or "").split())
        # phpBB normally uses class=topictitle, but accept any viewtopic link
        # carrying a topic id as a fallback against theme/class changes.
        absolute = urljoin(self.base_url, href)
        q = parse_qs(urlparse(absolute).query)
        has_topic_id = bool((q.get("t") or [""])[0])
        if "topictitle" in classes or ("viewtopic.php" in href and has_topic_id):
            self._capture = True
            self._href = href
            self._text = []

    def handle_data(self, data):
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._capture:
            return
        self._capture = False
        url = urljoin(self.base_url, self._href)
        q = parse_qs(urlparse(url).query)
        try:
            topic_id = int((q.get("t") or ["0"])[0])
        except ValueError:
            topic_id = 0
        title = " ".join("".join(self._text).split())
        if topic_id and title and not any(it.id == topic_id for it in self.items):
            self.items.append(TopicLink(topic_id, title, url))


class _FirstPostParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body_parts: list[str] = []
        self.author = ""
        self.date = ""
        self._in_content = False
        self._content_depth = 0
        self._in_author = False
        self._author_depth = 0
        self._author_text: list[str] = []
        self._author_link = False
        self._author_link_text: list[str] = []
        self._done_content = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())

        if not self.date and tag.lower() == "time" and a.get("datetime"):
            self.date = a["datetime"]

        if not self.author and tag.lower() == "p" and "author" in classes:
            self._in_author = True
            self._author_depth = 1
            self._author_text = []
        elif self._in_author:
            if tag.lower() == "p":
                self._author_depth += 1
            if tag.lower() == "a" and any(c.startswith("username") for c in classes):
                self._author_link = True
                self._author_link_text = []

        if not self._done_content and tag.lower() == "div" and "content" in classes:
            self._in_content = True
            self._content_depth = 1
            return
        if self._in_content:
            if tag.lower() == "div":
                self._content_depth += 1
            elif tag.lower() in ("br", "p", "li", "blockquote"):
                self.body_parts.append("\n" if tag.lower() != "li" else "\n• ")

    def handle_data(self, data):
        if self._in_content:
            self.body_parts.append(data)
        if self._in_author:
            self._author_text.append(data)
        if self._author_link:
            self._author_link_text.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._author_link and tag == "a":
            candidate = " ".join("".join(self._author_link_text).split())
            if candidate:
                self.author = candidate
            self._author_link = False
        if self._in_author and tag == "p":
            self._author_depth -= 1
            if self._author_depth <= 0:
                if not self.author:
                    txt = " ".join("".join(self._author_text).split())
                    m = re.search(r"\bby\s+(.+?)(?:\s*[»|]|\s+on\s+)", txt, re.I)
                    if m:
                        self.author = m.group(1).strip()
                self._in_author = False
        if self._in_content and tag == "div":
            self._content_depth -= 1
            if self._content_depth <= 0:
                self._in_content = False
                self._done_content = True

    def body(self) -> str:
        text = unescape("".join(self.body_parts))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" ?\n ?", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_topic_links(html: str, base_url: str = BASE) -> list[TopicLink]:
    parser = _TopicListParser(base_url)
    parser.feed(html)
    # Topic ids are monotonically allocated by phpBB. Sorting by id prevents
    # an old sticky from being mistaken for the newest announcement.
    return sorted(parser.items, key=lambda item: item.id, reverse=True)


def parse_first_post(html: str, topic: TopicLink) -> dict:
    parser = _FirstPostParser()
    parser.feed(html)
    body = parser.body()
    return {
        "id": str(topic.id),
        "title": topic.title,
        "author": parser.author or None,
        "date": parser.date,
        "body": body,
        "html": body,  # compatibility with the inherited renderer
        "url": topic.url,
    }


def normalize_news_item(raw: dict, base_url: str = BASE) -> dict | None:
    """Validate/normalise one object from OctoWoW's public NewsFeed schema."""
    if not isinstance(raw, dict):
        return None
    item_id = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    date = str(raw.get("date") or "").strip()
    body = str(raw.get("body") or raw.get("html") or "").strip()
    if not item_id or not title:
        return None
    url = raw.get("url")
    if url:
        url = urljoin(base_url, str(url))
    author = raw.get("author")
    if author is not None:
        author = str(author).strip() or None
    return {
        "id": item_id,
        "title": title,
        "author": author,
        "date": date,
        "body": body,
        "html": str(raw.get("html") or body),
        "url": url or "",
    }


def parse_news_feed_json(text: str, base_url: str = BASE) -> list[dict]:
    """Parse ``octonews.php?mode=list``. Accept only the documented shape."""
    payload = json.loads(text)
    if isinstance(payload, dict):
        rows = payload.get("items")
    else:
        rows = None
    if not isinstance(rows, list):
        raise ValueError("malformed OctoWoW news feed")
    out = []
    for row in rows:
        item = normalize_news_item(row, base_url)
        if item is not None:
            out.append(item)
    return out


def _read_text(opener, request, timeout: int) -> str:
    with opener(request, timeout=timeout) as response:
        raw = response.read()
        charset = "utf-8"
        try:
            charset = response.headers.get_content_charset() or charset
        except Exception:
            pass
        return raw.decode(charset, errors="replace")


def fetch_octonews(forum_id: int, *, opener, user_agent: str,
                   timeout: int = 8, limit: int = 8) -> list[dict]:
    """Read the same machine-readable feed used by OctoWoW's own launcher."""
    url = (f"{OCTONEWS_URL}?mode=list&forum={int(forum_id)}"
           f"&limit={max(1, int(limit))}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
        },
    )
    return parse_news_feed_json(_read_text(opener, req, timeout), url)


def _fetch_html_topics(forum_id: int, *, opener, user_agent: str,
                       timeout: int = 8, limit: int = 8) -> list[dict]:
    """Fallback direct phpBB scrape if the public JSON endpoint is unavailable."""
    url = f"{BASE}viewforum.php?f={int(forum_id)}&sk=t&sd=d"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    listing = _read_text(opener, req, timeout)
    topics = parse_topic_links(listing, url)[:max(1, int(limit))]
    if not topics:
        return []

    def fetch(topic: TopicLink):
        req2 = urllib.request.Request(
            topic.url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        html = _read_text(opener, req2, timeout)
        return parse_first_post(html, topic)

    with ThreadPoolExecutor(max_workers=min(4, len(topics))) as pool:
        return list(pool.map(fetch, topics))


def fetch_forum_topics(forum_id: int, *, opener, user_agent: str,
                       timeout: int = 8, limit: int = 8) -> list[dict]:
    """Fetch a forum feed, preferring OctoWoW's launcher-facing JSON API."""
    json_error = None
    try:
        items = fetch_octonews(
            forum_id, opener=opener, user_agent=user_agent,
            timeout=timeout, limit=limit)
        if items:
            return items
    except Exception as exc:
        json_error = exc

    try:
        items = _fetch_html_topics(
            forum_id, opener=opener, user_agent=user_agent,
            timeout=timeout, limit=limit)
        if items:
            return items
    except Exception as html_error:
        if json_error is not None:
            raise RuntimeError(
                f"JSON feed failed: {json_error}; forum fallback failed: {html_error}") from html_error
        raise

    if json_error is not None:
        raise RuntimeError(f"JSON feed failed: {json_error}; forum returned no topics")
    return []
