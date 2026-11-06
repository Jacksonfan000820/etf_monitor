"""Bounded public RSS/Atom collection and explicitly supplied X post import.

No social scraping, model-generated opinions, or assumed quote/price coverage.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
import json
import re
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

ALLOWED_FEED_HOSTS = {'www.federalreserve.gov', 'www.sec.gov', 'www.coindesk.com'}
CATEGORIES = {'crypto', 'us_stocks', 'macro', 'etf'}


def clean(text, limit=1000):
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', text or '')).split())[:limit]


def public_url(value, hosts=None):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('invalid HTTPS source URL')
    if hosts is not None and p.hostname not in hosts:
        raise ValueError('source host not allowed')
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))


def timestamp(value):
    if not value: return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try: dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError): return None
    if dt.tzinfo is None: return None
    return dt.astimezone(timezone.utc)


def freshness(dt, now, lookback_hours):
    if dt is None: return 'undated'
    if dt > now + timedelta(minutes=5): return 'future_timestamp'
    return 'current' if now - dt <= timedelta(hours=lookback_hours) else 'stale'


def local_name(tag):
    return tag.rsplit('}', 1)[-1]


def child_text(node, names):
    for child in node:
        if local_name(child.tag) in names:
            return ''.join(child.itertext())
    return ''


def parse_feed(xml, source, now, limit=15, lookback_hours=72):
    # ElementTree has no external entity fetcher; reject entity/DTD definitions too.
    if len(xml.encode('utf-8')) > 2_000_000 or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise ValueError('feed size or DTD policy violation')
    root = ET.fromstring(xml)
    if local_name(root.tag) not in {'rss', 'feed', 'RDF'}:
        raise ValueError('unsupported feed schema')
    entries = [e for e in root.iter() if local_name(e.tag) in {'item', 'entry'}]
    records, seen = [], set()
    for node in entries:
        title = clean(child_text(node, {'title'}), 300)
        url = child_text(node, {'link'}).strip()
        if not url:
            for child in node:
                if local_name(child.tag) == 'link' and child.get('rel', 'alternate') == 'alternate':
                    url = child.get('href', ''); break
        try: url = public_url(url)
        except ValueError: continue
        if not title or url in seen: continue
        seen.add(url)
        dt = timestamp(child_text(node, {'pubDate', 'published', 'updated', 'date'}))
        status = freshness(dt, now, lookback_hours)
        if status in {'stale', 'future_timestamp'}: continue
        records.append({'id': sha256(url.encode()).hexdigest()[:20], 'source': source['name'],
                        'category': source['category'], 'url': url, 'title_quote': title,
                        'description_quote': clean(child_text(node, {'description', 'summary'}), 600),
                        'published_at': dt.isoformat() if dt else None,
                        'fetched_at': now.isoformat(), 'freshness': status,
                        'evidence_type': 'publisher_feed_excerpt'})
    records.sort(key=lambda r: r['published_at'] or '', reverse=True)
    return records[:limit]


def collect_feeds(config, now, fetcher):
    if not isinstance(config, dict):
        raise ValueError('feed configuration must be an object')
    feeds = config.get('feeds', [])
    limit = int(config.get('max_items_per_source', 10))
    lookback = int(config.get('lookback_hours', 72))
    if not isinstance(feeds, list) or len(feeds) > 30 or not 1 <= limit <= 50 or not 1 <= lookback <= 168:
        raise ValueError('feed configuration exceeds supported bounds')
    reports, items, seen = [], [], set()
    for source in feeds:
        name = 'unnamed'
        try:
            if not isinstance(source, dict): raise ValueError('source must be an object')
            if not source.get('enabled', True): continue
            name = clean(source.get('name', 'unnamed'), 100)
            if source.get('category') not in CATEGORIES: raise ValueError('invalid category')
            url = public_url(source['url'], ALLOWED_FEED_HOSTS)
            records = parse_feed(fetcher(url, ALLOWED_FEED_HOSTS), source, now,
                                 limit=limit, lookback_hours=lookback)
            reports.append({'source': name, 'status': 'ok', 'item_count': len(records), 'url': url})
            for item in records:
                if item['id'] not in seen: items.append(item); seen.add(item['id'])
        except Exception:
            reports.append({'source': name, 'status': 'unavailable',
                            'reason': 'fetch, allowlist or feed schema validation failed'})
    return {'sources': reports, 'items': items}


def import_x_posts(path, now, lookback_hours=72):
    """Read user-supplied exports only. Source authenticity is NOT independently verified."""
    if path is None: return {'status': 'not_configured', 'items': []}
    with path.open('rb') as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000: raise ValueError('X export too large')
    records = json.loads(raw)
    if not isinstance(records, list) or len(records) > 1000: raise ValueError('invalid X export')
    items, seen, rejected = [], set(), 0
    for r in records:
        try:
            url = public_url(r['url'], {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'})
            match = re.fullmatch(r'/([A-Za-z0-9_]{1,15})/status/([0-9]+)', urlsplit(url).path)
            if not match or r['author'].lstrip('@').lower() != match[1].lower(): raise ValueError('author mismatch')
            dt = timestamp(r['published_at'])
            if dt is None or freshness(dt, now, lookback_hours) != 'current': raise ValueError('old or invalid timestamp')
            quote = clean(r['text'], 2000)
            if not quote: raise ValueError('empty post')
            post_id = match[2]
            if post_id in seen: continue
            seen.add(post_id)
            items.append({'id': post_id, 'author': '@' + match[1], 'url': url,
                          'published_at': dt.isoformat(), 'text_quote': quote,
                          'evidence_type': 'user_supplied_export', 'authenticity': 'not_independently_verified'})
        except (KeyError, TypeError, ValueError, AttributeError): rejected += 1
    return {'status': 'imported', 'items': items, 'rejected_records': rejected}
