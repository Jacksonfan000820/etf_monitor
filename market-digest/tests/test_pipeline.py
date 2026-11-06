import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import digest

HTML = '<table><tr><th>Date</th><th>A</th><th>Total</th></tr><tr><td>06 Nov 2026</td><td>2</td><td>2</td></tr></table>'
class PipelineTests(unittest.TestCase):
    def test_end_to_end_dry_run(self):
        def fixture_fetch(url, hosts):
            if 'farside.co.uk' in url: return HTML
            return '<rss><channel><item><title>Fixture only</title><link>https://example.com/fixture</link></item></channel></rss>'
        with TemporaryDirectory() as tmp, patch('sys.argv', ['digest.py', '--output', tmp]), patch('digest.closed_sessions', return_value=[date(2026,11,6)]), patch('digest.fetch', side_effect=fixture_fetch), patch('digest.send_feishu') as send, patch('builtins.print'):
            digest.main()
            report = json.loads((Path(tmp)/'report.json').read_text())
            self.assertEqual(report['etf']['BTC']['status'], 'current')
            self.assertEqual(report['news']['sources'][0]['status'], 'ok')
            self.assertEqual(report['x_posts']['status'], 'not_configured')
            self.assertTrue((Path(tmp)/'report.txt').exists())
            send.assert_not_called()
    def test_feishu_reject_credentials_in_url(self):
        with patch.dict('os.environ', {'FEISHU_WEBHOOK_URL':'https://user:password@open.feishu.cn/open-apis/bot/v2/hook/example'}):
            with self.assertRaises(ValueError): digest.send_feishu('test')
