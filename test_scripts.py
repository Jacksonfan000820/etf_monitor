import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from scripts import check, offline_demo


class ScriptTests(unittest.TestCase):
    def test_preview_is_historical_and_has_real_fixture_values(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            report = offline_demo.build_preview()
        self.assertFalse(report['live_data'])
        self.assertEqual(report['mode'], 'historical_fixture_only')
        self.assertEqual(report['assets']['BTC']['row_count'], 14)
        self.assertEqual(report['assets']['BTC']['latest_fixture_row']['date'], '2026-11-05')
        self.assertAlmostEqual(report['assets']['BTC']['latest_fixture_row']['total'], -430.2)
        self.assertAlmostEqual(report['assets']['ETH']['latest_fixture_row']['total'], -99.9)

    def test_demo_runs_from_another_directory_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, str(check.ROOT / 'scripts/offline_demo.py')], cwd=tmp, capture_output=True, text=True, check=True)
            self.assertFalse(json.loads(result.stdout)['live_data'])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_check_fails_clearly_for_missing_dependencies(self):
        with patch.object(check, 'missing_dependencies', return_value=['curl_cffi']), patch.object(check.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(check.main(), 2)
            self.assertIn('curl_cffi', error.getvalue())
            run.assert_not_called()

    def test_check_runs_all_stages_and_preserves_failure(self):
        with patch.object(check, 'missing_dependencies', return_value=[]), patch.object(check.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            run.side_effect = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0)]
            self.assertEqual(check.main(), 1)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(run.call_args_list[1].kwargs['cwd'], check.ROOT / 'market-digest')

    def test_check_success(self):
        with patch.object(check, 'missing_dependencies', return_value=[]), patch.object(check.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check.main(), 0)
