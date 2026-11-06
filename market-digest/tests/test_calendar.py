"""Real installed calendar regression; skipped only when dependency is absent."""
import importlib.util
import unittest
from datetime import datetime
from digest import closed_sessions

@unittest.skipUnless(importlib.util.find_spec('exchange_calendars'), 'calendar dependency not installed')
class CalendarTests(unittest.TestCase):
    def test_holiday_early_close_and_dst(self):
        cases = [
            ('2026-07-04T02:00:00+00:00', '2026-07-02'),
            ('2026-11-27T17:59:00+00:00', '2026-11-25'),
            ('2026-11-27T18:01:00+00:00', '2026-11-27'),
            ('2026-03-09T19:59:00+00:00', '2026-03-06'),
            ('2026-03-09T20:01:00+00:00', '2026-03-09'),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(str(closed_sessions(datetime.fromisoformat(now))[-1]), expected)
