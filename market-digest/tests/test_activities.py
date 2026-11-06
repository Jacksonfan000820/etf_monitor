import json
import unittest
from datetime import datetime, timezone
from activities import collect_activities, parse_binance, parse_okx, BINANCE, OKX

NOW = datetime(2026, 11, 6, 14, tzinfo=timezone.utc)
MILLIS = int(NOW.timestamp() * 1000) - 3600000

def binance(rows=None):
    if rows is None: rows = [{'code': 'a'*32, 'title': 'Official campaign', 'releaseDate': MILLIS}]
    return json.dumps({'code':'000000','success':True,'data':{'catalogs':[{'catalogId':93,'articles':rows}]}})

def okx(rows=None):
    if rows is None: rows = [{'slug':'example-campaign','title':'官方活动','publishTime':MILLIS,'sectionSlug':'latest-events'}]
    return '<html><script type="application/json" id="appState">'+json.dumps({'appContext':{'initialProps':{'sectionData':{'articleList':{'list':rows}}}}})+'</script></html>'

class ActivitiesTests(unittest.TestCase):
    def test_binance_exact_link_time_and_unknowns(self):
        r = parse_binance(binance(), NOW)[0]
        self.assertEqual(r['url'], 'https://www.binance.com/en/support/announcement/detail/'+'a'*32)
        self.assertEqual(r['published_at'], '2026-11-06T13:00:00+00:00')
        self.assertEqual(r['eligibility'], 'not_checked')
        self.assertIsNone(r['deadline'])
    def test_okx_chinese_and_url(self):
        r = parse_okx(okx(), NOW)[0]
        self.assertEqual(r['title_quote'], '官方活动')
        self.assertEqual(r['url'], 'https://www.okx.com/zh-hans/help/example-campaign')
    def test_invalid_schema_fails(self):
        for raw in ['{}', '<html>Challenge</html>']:
            with self.assertRaises(Exception): parse_binance(raw, NOW)
            with self.assertRaises(Exception): parse_okx(raw, NOW)
    def test_injection_in_slug_rejected(self):
        with self.assertRaises(ValueError): parse_okx(okx([{'slug':'../evil','title':'x','publishTime':MILLIS,'sectionSlug':'latest-events'}]), NOW)
    def test_old_future_excluded(self):
        for dt in [MILLIS-8*86400000, MILLIS+7200000]:
            self.assertEqual(parse_binance(binance([{'code':'a'*32,'title':'x','releaseDate':dt}]),NOW), [])
    def test_limit_sort_dedup(self):
        rows=[{'code':c*32,'title':'x','releaseDate':MILLIS-i*1000} for i,c in enumerate('abc')]
        r=collect_activities(NOW,lambda u,h:binance(rows+rows) if u==BINANCE else okx())
        self.assertEqual(len(r['items']),3)
        self.assertEqual(r['sources'][0]['item_count'],2)
        self.assertEqual(r['sources'][2]['status'],'not_integrated')
    def test_failure_isolation(self):
        r=collect_activities(NOW,lambda u,h: '{}' if u==BINANCE else okx())
        self.assertEqual([x['status'] for x in r['sources']],['unavailable','ok','not_integrated'])
    def test_no_validity_claim(self):
        self.assertEqual(parse_okx(okx(),NOW)[0]['activity_status'],'not_verified')
    def test_bounds(self):
        with self.assertRaises(ValueError): collect_activities(NOW,lambda *_:'',limit=3)
        with self.assertRaises(ValueError): parse_okx('x'*2000001,NOW)

if __name__ == '__main__': unittest.main()
