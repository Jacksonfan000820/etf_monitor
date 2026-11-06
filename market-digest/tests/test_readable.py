import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from digest import readable_flow, readable_time, render, summarize, Flow
from sources import collect_feeds

class ReadableTests(unittest.TestCase):
    def test_flow_units_and_direction(self):
        self.assertEqual(readable_flow('240'), '净流入 2.40 亿美元')
        self.assertEqual(readable_flow('-240'), '净流出 2.40 亿美元')
        self.assertEqual(readable_flow('0'), '净流量为零')
        self.assertIn('暂不计算', readable_flow(None))
        self.assertEqual(readable_flow('0.1'), '净流入 0.0010 亿美元')
    def test_beijing_time_is_readable(self):
        self.assertEqual(readable_time('2026-11-06T17:00:00+00:00'), '2026年11月07日 01:00')
        self.assertEqual(readable_time('2026-11-06T17:00:00'), '时间未核实')
    def test_five_day_rows_preserve_gap(self):
        dates = [date(2026,11,d) for d in range(2,7)]
        data = summarize({d: Flow(d,Decimal('1'),True) for d in dates if d.day != 3}, dates)
        self.assertEqual(len(data['five_session_flows']),5)
        self.assertIsNone(data['five_session_flows'][1]['total_musd'])
        self.assertIsNone(data['five_session_total_musd'])
    def test_missing_and_stale_are_explicit(self):
        report = {'generated_beijing':'2026-11-07T01:00:00+08:00', 'etf':{'BTC':{'status':'stale','latest_complete':'2026-11-05','latest_total_musd':'-100','expected_session':'2026-11-06'}}, 'announcements':[]}
        text = render(report)
        self.assertIn('净流出 1.00 亿美元',text)
        self.assertIn('不是最新交易日数据',text)
        self.assertIn('不代表马斯克没有发帖',text)
        self.assertNotIn('stale',text)
    def test_chinese_feed_allowlist_and_topic_filter(self):
        xml = '<rss><channel><item><title>美国非农公布</title><link>https://wallstreetcn.com/articles/1</link><pubDate>Fri, 06 Nov 2026 13:00:00 GMT</pubDate></item><item><title>无关新闻</title><link>https://wallstreetcn.com/articles/2</link></item></channel></rss>'
        config = {'feeds':[{'name':'中文','category':'us_stocks','url':'https://feed.wallstreetcn.com/wallstreetcn/news/global','title_keywords':['美国']}]}
        result=collect_feeds(config,datetime(2026,11,6,14,tzinfo=timezone.utc),lambda *_:xml)
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['sources'][0]['status'],'ok')
    def test_undated_news_not_presented_as_recent(self):
        report={'generated_beijing':'2026-11-07T01:00:00+08:00','etf':{},'announcements':[], 'news':{'sources':[], 'items':[{'category':'crypto','published_at':None,'title_quote':'未知日期标题'}]}}
        text=render(report)
        self.assertNotIn('未知日期标题',text)
        self.assertIn('1 条来源记录没有',text)

    def test_chinese_headlines_do_not_get_english_filler(self):
        news = [{'category':'us_stocks','published_at':'2026-11-06T12:00:00+00:00', 'title_quote':title, 'source':'fixture', 'url':'https://example.com'} for title in ['美国就业新闻', 'English regulatory boilerplate']]
        text = render({'generated_beijing':'2026-11-07T01:00:00+08:00','etf':{},'announcements':[], 'news':{'sources':[],'items':news}})
        self.assertIn('美国就业新闻',text)
        self.assertNotIn('English regulatory boilerplate',text)
