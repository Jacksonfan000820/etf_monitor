import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import digest
import sources

class SafetyTests(unittest.TestCase):
    def test_nonstandard_fetch_port_rejected_before_network(self):
        with patch('urllib.request.build_opener') as opener:
            with self.assertRaises(ValueError):
                digest.fetch('https://farside.co.uk:8443/btc/', {'farside.co.uk'})
            opener.assert_not_called()

    def test_malformed_source_does_not_abort_other_sources(self):
        config = {'feeds': [None, {'name': 'Good', 'category': 'macro',
                  'url': 'https://www.federalreserve.gov/feed.xml'}]}
        result = sources.collect_feeds(config, datetime.now(timezone.utc),
                                       lambda *_: '<rss><channel/></rss>')
        self.assertEqual([s['status'] for s in result['sources']], ['unavailable', 'ok'])

    def test_invalid_source_name_is_isolated(self):
        result = sources.collect_feeds({'feeds': [{'name': 42}]},
                                       datetime.now(timezone.utc), lambda *_: '')
        self.assertEqual(result['sources'][0]['status'], 'unavailable')

    def test_nonobject_configuration_rejected(self):
        with self.assertRaises(ValueError):
            sources.collect_feeds([], datetime.now(timezone.utc), lambda *_: '')
