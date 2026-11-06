#!/usr/bin/env python3
"""Print a historical fixture preview, without HTTP, DB writes, or messaging."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flow_quality import parse_table

# Match the captured headers; legacy DEFI is optional and not in this fixture.
COLUMNS = {
    'btc': ['IBIT', 'FBTC', 'GBTC', 'ARKB', 'BITB', 'HODL', 'BRRR', 'BTCW', 'EZBC', 'BTCO', 'BTC', 'MSBT'],
    'eth': ['ETHA', 'ETHB', 'FETH', 'ETHW', 'TETH', 'ETHV', 'QETH', 'EZET', 'ETHE', 'ETH', 'MSSE'],
}


def build_preview():
    report = {'mode': 'historical_fixture_only', 'live_data': False,
              'notice': 'Historical parser demonstration. Not current market data or investment advice.',
              'unit': 'USD million', 'assets': {}}
    for asset, columns in COLUMNS.items():
        fixture = ROOT / 'fixtures' / f'farside_{asset}_2026-11-06.html'
        rows = parse_table(fixture.read_text(encoding='utf-8'), columns)
        report['assets'][asset.upper()] = {
            'fixture': fixture.name, 'row_count': len(rows), 'latest_fixture_row': rows[-1],
        }
    return report


def main():
    print(json.dumps(build_preview(), indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
