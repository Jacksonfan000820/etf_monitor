import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from sources import collect_feeds, import_x_posts, parse_feed, public_url, timestamp

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
SOURCE = {'name': 'Fed', 'category': 'macro', 'url': 'https://www.federalreserve.gov/feeds/press_all.xml'}
RSS = '''<rss><channel><item><title>Policy &amp; markets</title><link>https://www.federalreserve.gov/newsevents/a.htm</link><pubDate>Fri, 06 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Exact excerpt&lt;/p&gt;</description></item></channel></rss>'''

class SourceTests(unittest.TestCase):
    def test_rss(self):
        r = parse_feed(RSS, SOURCE, NOW)[0]
        self.assertEqual(r['title_quote'], 'Policy & markets')
        self.assertEqual(r['description_quote'], 'Exact excerpt')
        self.assertEqual(r['freshness'], 'current')
    def test_atom(self):
        xml = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Release</title><link href="https://example.com/a"/><updated>2026-11-06T10:00:00Z</updated></entry></feed>'
        self.assertEqual(len(parse_feed(xml, SOURCE, NOW)), 1)
    def test_old_and_future_excluded(self):
        for dt in ['Fri, 01 Nov 2024 10:00:00 GMT', 'Fri, 06 Nov 2026 13:00:00 GMT']:
            self.assertEqual(parse_feed(RSS.replace('Fri, 06 Nov 2026 10:00:00 GMT', dt), SOURCE, NOW), [])
    def test_undated_explicit(self):
        r = parse_feed(RSS.replace('Fri, 06 Nov 2026 10:00:00 GMT', ''), SOURCE, NOW)[0]
        self.assertEqual(r['freshness'], 'undated'); self.assertIsNone(r['published_at'])
    def test_no_dtd(self):
        with self.assertRaises(ValueError): parse_feed('<!DOCTYPE rss><rss/>', SOURCE, NOW)
    def test_bad_schema(self):
        with self.assertRaises(ValueError): parse_feed('<html>blocked</html>', SOURCE, NOW)
    def test_source_failure_isolated(self):
        config = {'feeds': [SOURCE, {**SOURCE, 'name': 'bad', 'url': 'https://evil.example/rss'}]}
        r = collect_feeds(config, NOW, lambda *_: RSS)
        self.assertEqual([s['status'] for s in r['sources']], ['ok', 'unavailable'])
        self.assertEqual(len(r['items']), 1)
    def test_deduplicate(self):
        r = collect_feeds({'feeds': [SOURCE, SOURCE]}, NOW, lambda *_: RSS)
        self.assertEqual(len(r['items']), 1)
    def test_url_validation(self):
        for url in ['http://x.com/a', 'https://user:pw@x.com/a', 'https://x.com:444/a']:
            with self.assertRaises(ValueError): public_url(url)
    def test_naive_timestamp(self): self.assertIsNone(timestamp('2026-11-06T10:00:00'))
    def test_x_not_configured(self): self.assertEqual(import_x_posts(None, NOW)['status'], 'not_configured')
    def test_x_import_reject_mismatch_and_dedup(self):
        post = {'author': '@example', 'url': 'https://x.com/example/status/123', 'published_at': '2026-11-06T10:00:00Z', 'text': 'Source quote'}
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/'posts.json'; p.write_text(json.dumps([post, post, {**post, 'author': 'someone'}]))
            r = import_x_posts(p, NOW)
        self.assertEqual(len(r['items']), 1); self.assertEqual(r['rejected_records'], 1)
        self.assertEqual(r['items'][0]['authenticity'], 'not_independently_verified')

if __name__ == '__main__': unittest.main()
