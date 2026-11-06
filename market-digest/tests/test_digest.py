import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from digest import Flow, number, parse_farside, summarize, collect_announcements, fetch, render, BJ, send_feishu

DAYS = [date(2026,11,d) for d in (2,3,4,5,6)]
class DigestTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        for s in ('', '-', '–', '—', 'N/A', 'NaN', 'Infinity'): self.assertIsNone(number(s))
        self.assertEqual(number('0.0'), Decimal('0'))
        self.assertEqual(number('(1,200.1)'), Decimal('-1200.1'))
    def test_complete_table(self):
        rows = parse_farside('<table><tr><th>Date</th><th>A</th><th>B</th><th>Total</th></tr><tr><td>06 Nov 2026</td><td>0</td><td>(2.1)</td><td>-2.1</td></tr></table>')
        self.assertTrue(rows[DAYS[-1]].complete)
    def test_live_style_two_row_header(self):
        rows = parse_farside('<table><tr><th></th><th></th><th></th><th>Total</th></tr><tr><th></th><th>IBIT</th><th>FBTC</th><th></th></tr><tr><td>06 Nov 2026</td><td>0.0</td><td>3.0</td><td>3.0</td></tr></table>')
        self.assertTrue(rows[DAYS[-1]].complete)
    def test_total_does_not_prove_completeness(self):
        rows = parse_farside('<table><tr><td>Date</td><td>A</td><td>B</td><td>Total</td></tr><tr><td>06 Nov 2026</td><td>-</td><td>3</td><td>3</td></tr></table>')
        self.assertFalse(rows[DAYS[-1]].complete)
    def test_current_five_sessions(self):
        rows = {d:Flow(d,Decimal('0'),True) for d in DAYS}
        s = summarize(rows,DAYS)
        self.assertEqual(s['five_session_total_musd'],'0'); self.assertEqual(s['status'],'current')
    def test_gap_not_silently_skipped(self):
        rows = {d:Flow(d,Decimal('1'),True) for d in DAYS}; del rows[DAYS[1]]
        self.assertIsNone(summarize(rows,DAYS)['five_session_total_musd'])
    def test_latest_partial_is_stale(self):
        rows = {d:Flow(d,Decimal('1'),True) for d in DAYS}; rows[DAYS[-1]]=Flow(DAYS[-1],None,False)
        s = summarize(rows,DAYS)
        self.assertEqual(s['status'],'stale'); self.assertEqual(s['latest_complete'],'2026-11-05')
    def test_weekend_uses_last_session(self):
        rows={DAYS[-1]:Flow(DAYS[-1],Decimal('2'),True)}
        self.assertEqual(summarize(rows,DAYS)['status'],'current')
    def test_future_row_excluded(self):
        rows={date(2030,1,1):Flow(date(2030,1,1),Decimal('2'),True)}
        self.assertEqual(summarize(rows,DAYS)['status'],'unavailable')
    def test_schema_fail_closed(self):
        with self.assertRaises(ValueError): parse_farside('<html>Access denied</html>')
    def test_beijing_timezone(self):
        self.assertEqual(datetime(2026,11,6,17,tzinfo=timezone.utc).astimezone(BJ).isoformat(),'2026-11-07T01:00:00+08:00')
    def test_official_source_allowlist(self):
        for url in ('http://www.okx.com/a','https://www.okx.com.evil.com/a','https://user@www.okx.com/a'):
            with self.assertRaises(ValueError): fetch(url,{'www.okx.com'})
    def test_announcement_evidence_only(self):
        result=collect_announcements(['https://www.okx.com/a'],lambda *_:'<title>Campaign</title><meta name="description" content="Official quote">')[0]
        self.assertEqual(result['status'],'candidate_only'); self.assertEqual(result['eligibility_deadline_rewards'],'not_verified')
    def test_missing_evidence_unavailable(self):
        result=collect_announcements(['https://www.okx.com/a'],lambda *_:'<title>Campaign</title>')[0]
        self.assertEqual(result['status'],'unavailable')
    def test_no_secret_default(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError): send_feishu('test')

if __name__ == '__main__': unittest.main()
