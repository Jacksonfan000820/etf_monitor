"""Bounded read-only discovery. Listing candidates are not eligibility checks.

Public website schemas are not stable APIs. Never infer that a listed campaign
is still open, risk-free, available in the user's region, or worth joining.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
from sources import clean, freshness

HOSTS = {'www.binance.com', 'www.okx.com'}
BINANCE = 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=10&catalogId=93'
OKX = 'https://www.okx.com/zh-hans/help/section/latest-events'
BITGET = 'https://www.bitget.com/zh-CN/support/sections/4413154768537'


class _AppState(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = dict(attrs).get('id') == 'appState'
    def handle_endtag(self, tag):
        if tag == 'script': self.active = False
    def handle_data(self, data):
        if self.active: self.parts.append(data)


def _payload(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 2_000_000:
        raise ValueError('activity response size or type invalid')
    return raw


def _record(exchange, key, title, millis, now, lookback_hours):
    if isinstance(millis, bool) or not isinstance(millis, (int, float)):
        raise ValueError('missing epoch milliseconds')
    dt = datetime.fromtimestamp(millis / 1000, timezone.utc)
    if freshness(dt, now, lookback_hours) != 'current': return None
    title = clean(title, 300)
    if not title: raise ValueError('empty activity title')
    if exchange == 'Binance':
        if not re.fullmatch(r'[a-f0-9]{32}', key): raise ValueError('invalid article code')
        url = 'https://www.binance.com/en/support/announcement/detail/' + key
    else:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,250}', key): raise ValueError('invalid slug')
        url = 'https://www.okx.com/zh-hans/help/' + key
    return {'id': exchange.lower() + ':' + key, 'exchange': exchange,
            'title_quote': title, 'url': url, 'published_at': dt.isoformat(),
            'fetched_at': now.isoformat(), 'freshness': 'current',
            'evidence_type': 'official_activity_listing',
            'language': 'en' if exchange == 'Binance' else 'zh-Hans',
            'eligibility': 'not_checked', 'activity_status': 'not_verified',
            'deadline': None, 'requirements': None, 'risk_review': 'not_performed'}


def parse_binance(raw, now, lookback_hours=168):
    data = json.loads(_payload(raw))
    if data.get('code') != '000000' or data.get('success') is not True:
        raise ValueError('Binance API did not report success')
    catalogs = data['data']['catalogs']
    catalog = next(c for c in catalogs if c.get('catalogId') == 93)
    return _records(catalog['articles'], 'Binance', 'code', 'releaseDate', now, lookback_hours)


def parse_okx(raw, now, lookback_hours=168):
    parser = _AppState(); parser.feed(_payload(raw))
    data = json.loads(''.join(parser.parts))
    rows = data['appContext']['initialProps']['sectionData']['articleList']['list']
    if not isinstance(rows, list): raise ValueError('invalid article list')
    rows = [r for r in rows if isinstance(r, dict) and r.get('sectionSlug') == 'latest-events']
    return _records(rows, 'OKX', 'slug', 'publishTime', now, lookback_hours)


def _records(rows, exchange, key_field, time_field, now, lookback_hours):
    if not isinstance(rows, list) or len(rows) > 100: raise ValueError('invalid article list')
    records = {}
    for row in rows:
        # Fail closed on malformed schema rather than silently reporting an empty list.
        r = _record(exchange, row[key_field], row['title'], row[time_field], now, lookback_hours)
        if r: records[r['id']] = r
    return sorted(records.values(), key=lambda r: r['published_at'], reverse=True)


def collect_activities(now, fetcher, limit=2, lookback_hours=168):
    """Fetcher must enforce HTTPS host/redirect allowlist and bounded response sizes."""
    if not isinstance(limit, int) or not 1 <= limit <= 2 or not 1 <= lookback_hours <= 168:
        raise ValueError('activity bounds exceeded')
    reports, items = [], []
    for exchange, url, parser in [('Binance', BINANCE, parse_binance), ('OKX', OKX, parse_okx)]:
        try:
            records = parser(fetcher(url, HOSTS), now, lookback_hours)[:limit]
            reports.append({'source': exchange, 'url': url, 'status': 'ok', 'item_count': len(records),
                            'fetched_at': now.isoformat(), 'coverage': 'bounded_first_page'})
            items.extend(records)
        except Exception:
            reports.append({'source': exchange, 'url': url, 'status': 'unavailable',
                            'fetched_at': now.isoformat(), 'reason': 'fetch or activity schema validation failed'})
    reports.append({'source': 'Bitget', 'url': BITGET, 'status': 'not_integrated',
                    'reason': 'official listing identified; automated parser not yet validated'})
    return {'sources': reports, 'items': items,
            'scope': '官方公告候选，不代表活动仍有效或用户符合资格；参与前核实地区、KYC、资金要求及风险。'}
