import unittest

from equpdater.news import (
    TopicLink,
    normalize_news_item,
    parse_first_post,
    parse_news_feed_json,
    parse_topic_links,
)


class NewsParserTests(unittest.TestCase):
    def test_topic_links_ignore_sticky_order_and_sort_by_topic_id(self):
        html = '''
        <a class="topictitle" href="./viewtopic.php?t=10">Pinned old post</a>
        <a href="./viewtopic.php?t=31" class="topictitle">Newest post</a>
        <a class="topictitle other" href="./viewtopic.php?t=22">Middle post</a>
        '''
        items = parse_topic_links(html, "https://octowow.st/forum/viewforum.php?f=2")
        self.assertEqual([x.id for x in items], [31, 22, 10])
        self.assertEqual(items[0].title, "Newest post")

    def test_topic_links_survive_missing_topictitle_class(self):
        html = '''
        <a href="./viewtopic.php?f=2&t=2595">DDoS Updates</a>
        <a href="./viewtopic.php?f=2&t=2594">Whitelist Updates</a>
        '''
        items = parse_topic_links(html, "https://octowow.st/forum/viewforum.php?f=2")
        self.assertEqual([x.id for x in items], [2595, 2594])
        self.assertEqual(items[0].title, "DDoS Updates")

    def test_first_post_extracts_body_author_and_date(self):
        topic = TopicLink(31, "Patch 31", "https://octowow.st/forum/viewtopic.php?t=31")
        html = '''
        <div class="post">
          <p class="author">by <a class="username-coloured">Kestrel</a>
            <time datetime="2026-09-24T05:00:00+00:00">24 Sep</time></p>
          <div class="content">First line<br>Second line<ul><li>Thing</li></ul></div>
        </div>
        '''
        item = parse_first_post(html, topic)
        self.assertEqual(item["author"], "Kestrel")
        self.assertEqual(item["date"], "2026-09-24T05:00:00+00:00")
        self.assertIn("First line", item["body"])
        self.assertIn("Second line", item["body"])
        self.assertIn("Thing", item["body"])

    def test_octonews_json_matches_launcher_schema(self):
        raw = '''{
          "items": [
            {
              "id": "2595",
              "title": "DDoS Updates",
              "date": "2026-09-24T07:06:00+00:00",
              "body": "Status update body",
              "url": "https://octowow.st/forum/viewtopic.php?t=2595",
              "author": "Kestrel"
            }
          ]
        }'''
        items = parse_news_feed_json(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "2595")
        self.assertEqual(items[0]["title"], "DDoS Updates")
        self.assertEqual(items[0]["body"], "Status update body")
        self.assertEqual(items[0]["author"], "Kestrel")

    def test_octonews_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):
            parse_news_feed_json('{"not_items": []}')

    def test_normalizer_accepts_nullable_author_and_relative_url(self):
        item = normalize_news_item({
            "id": "7", "title": "Patch 7", "date": "", "body": "Body",
            "url": "./viewtopic.php?t=7", "author": None,
        })
        self.assertIsNone(item["author"])
        self.assertEqual(item["url"], "https://octowow.st/forum/viewtopic.php?t=7")


if __name__ == "__main__":
    unittest.main()
