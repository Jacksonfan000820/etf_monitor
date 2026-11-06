import unittest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, Mock
from flow_quality import number, parse_table, summary, completed_sessions
import etf_db

class QualityTests(unittest.TestCase):
    def table(self, header, rows):
        return '<table><tr>'+''.join('<th>'+x+'</th>' for x in header)+'</tr>'+''.join('<tr>'+''.join('<td>'+x+'</td>' for x in row)+'</tr>' for row in rows)+'</table>'
    def test_live_captured_tables(self):
        for symbol, columns, expected in [('btc',etf_db.BTC_COLS,-430.2),('eth',etf_db.ETH_COLS,-99.9)]:
            html=(Path(__file__).parent/'fixtures'/f'farside_{symbol}_2026-11-06.html').read_text()
            days=parse_table(html,columns,optional_columns={'DEFI'})
            self.assertEqual(len(days),14)
            self.assertEqual(days[-1]['date'],'2026-11-05')
            self.assertAlmostEqual(days[-1]['total'],expected)
    def test_missing_required_header(self):
        with self.assertRaises(ValueError):
            parse_table(self.table(['Date','IBIT','Total'],[['06 Nov 2026','1','1']]),['IBIT','FBTC'])
    def test_price_failures_are_missing(self):
        response=Mock(); response.raise_for_status.side_effect=RuntimeError('HTTP error')
        with patch.object(etf_db.session,'get',return_value=response), patch.object(etf_db.time,'sleep'):
            self.assertEqual(etf_db.get_price_data(), (None,None,None))
    def test_additive_legacy_migration(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory, patch.object(etf_db,'DB_PATH',os.path.join(directory,'old.db')):
            with sqlite3.connect(etf_db.DB_PATH) as conn:
                conn.execute('CREATE TABLE btc_flows (date TEXT PRIMARY KEY, total REAL, fetched_at TEXT)')
                conn.execute("INSERT INTO btc_flows VALUES ('2026-01-02', 12, 'old')")
            etf_db.init_db()
            rows=etf_db.get_all_btc()
            self.assertEqual(rows[0][len(etf_db.BTC_COLS)+1],12)
            self.assertIsNone(rows[0][-3])
    def test_missing_is_not_zero(self):
        for text in ['', '-', '—', 'N/A']: self.assertIsNone(number(text))
        self.assertEqual(number('0.0'), 0)
        self.assertEqual(number('(1,234.5)'), -1234.5)
        for text in ['oops', 'nan', 'inf']:
            with self.assertRaises(ValueError): number(text)
    def test_headers_and_sort(self):
        html=self.table(['Date','FBTC','IBIT','Total'],[['06 Nov 2026','2','1','3'],['05Nov2026','4','0','4']])
        days=parse_table(html,['IBIT','FBTC','BTC'],optional_columns={'BTC'})
        self.assertEqual(days[0]['date'],'2026-11-05')
        self.assertEqual(days[1]['flows'],{'IBIT':1,'FBTC':2,'BTC':None})
    def test_partial_total_not_final(self):
        day=parse_table(self.table(['Date','IBIT','Total'],[['06 Nov 2026','-','0']]),['IBIT'])[0]
        self.assertIsNone(day['total'])
    def test_fail_closed(self):
        for html in ['<html>challenge</html>',self.table(['Date','IBIT','NEW','Total'],[['06 Nov 2026','1','2','3']]),self.table(['Date','IBIT','Total'],[['06 Nov 2026','1']]),self.table(['Date','IBIT','Total'],[['06 Nov 2026','1','100']])]:
            with self.assertRaises(ValueError): parse_table(html,['IBIT'])
    def test_five_expected_not_five_available(self):
        sessions=['2026-11-02','2026-11-03','2026-11-04','2026-11-05','2026-11-06']
        rows=[(d,v) for d,v in zip(sessions,[1,0,-2,3,4])]
        self.assertEqual(summary(rows,1,sessions)['net'],6)
        self.assertEqual(summary(rows,1,sessions)['inflow_days'],3)
        self.assertIsNone(summary(rows[:-1],1,sessions)['net'])
    def test_holidays_early_close_dst(self):
        # July 3 is observed Independence Day in 2026.
        result=completed_sessions(datetime(2026,7,4,2,tzinfo=timezone.utc))
        self.assertEqual(result[-1],'2026-07-02')
        # Thanksgiving Friday closes at 13:00 ET = 18:00 UTC.
        self.assertEqual(completed_sessions(datetime(2026,11,27,17,59,tzinfo=timezone.utc))[-1],'2026-11-25')
        self.assertEqual(completed_sessions(datetime(2026,11,27,18,1,tzinfo=timezone.utc))[-1],'2026-11-27')
    def test_http_failure(self):
        response=Mock(); response.raise_for_status.side_effect=RuntimeError('503')
        with patch.object(etf_db.session,'get',return_value=response):
            with self.assertRaises(RuntimeError): etf_db.parse_farside('btc',etf_db.BTC_COLS)
    def test_database_and_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(etf_db,'DB_PATH',os.path.join(directory,'test.db')):
            etf_db.init_db();etf_db.upsert_btc('2026-11-05',{'IBIT':0},None)
            rows=etf_db.get_all_btc(); self.assertEqual(rows[0][1],0);self.assertIsNone(rows[0][2]);self.assertIsNone(rows[0][len(etf_db.BTC_COLS)+1])
            etf_db.upsert_btc('2026-11-05',{'IBIT':1},1)
            self.assertEqual(len(etf_db.get_all_btc()),1)
            html=etf_db.generate_html(rows,[],[],[],[],None,None,0,[],datetime(2026,11,6,tzinfo=timezone.utc))
            self.assertIn('待更新',html);self.assertIn('北京时间',html);self.assertIn('5交易日净流',html)
            self.assertNotIn('>${0',html)
    def test_duplicate_conflict(self):
        with self.assertRaises(ValueError):
            parse_table(self.table(['Date','IBIT','Total'],[['06 Nov 2026','1','1'],['06 Nov 2026','2','2']]),['IBIT'])

if __name__ == '__main__': unittest.main()
