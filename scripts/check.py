#!/usr/bin/env python3
"""Run both offline suites from any directory; never execute production CLIs."""
from pathlib import Path
import importlib.util
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('curl_cffi', 'pandas_market_calendars', 'exchange_calendars', 'pandas', 'tzdata')


def missing_dependencies():
    return [name for name in REQUIRED if importlib.util.find_spec(name) is None]


def checks():
    return [
        (ROOT, ['-m', 'unittest', 'discover', '-s', '.', '-p', 'test_*.py', '-v']),
        (ROOT / 'market-digest', ['-m', 'unittest', 'discover', '-s', 'tests', '-v']),
        (ROOT, ['-m', 'compileall', '-q', 'etf_db.py', 'flow_quality.py', 'scripts', 'market-digest']),
    ]


def main():
    missing = missing_dependencies()
    if missing:
        print('Missing test dependencies: ' + ', '.join(missing), file=sys.stderr)
        print('Install from repository root: python -m pip install -r requirements.txt -r market-digest/requirements.txt', file=sys.stderr)
        return 2
    failed = False
    for cwd, args in checks():
        print(f'Checking {cwd.name}: {" ".join(args)}', flush=True)
        failed = subprocess.run([sys.executable, *args], cwd=cwd, check=False).returncode != 0 or failed
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
