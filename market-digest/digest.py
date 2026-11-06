"""Evidence-first market digest. No LLM, secrets in files, or unofficial feeds."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from sources import collect_feeds, import_x_posts
from activities import collect_activities

SOURCES = {'BTC': 'https://farside.co.uk/btc/', 'ETH': 'https://farside.co.uk/eth/'}
OFFICIAL_HOSTS = {'www.binance.com', 'www.okx.com', 'announcements.bybit.com'}
BJ = ZoneInfo('Asia/Shanghai')

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables = []; self.table = None; self.row = None; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.table = []
        elif tag == 'tr' and self.table is not None: self.row = []
        elif tag in ('td', 'th') and self.row is not None: self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row); self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table); self.table = None

def number(value):
    value = value.strip().replace(',', '').replace('−', '-')
    if value in ('', '-', '–', '—', 'N/A', 'n/a', 'NA'): return None
    if value.startswith('(') and value.endswith(')'): value = '-' + value[1:-1]
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except InvalidOperation: return None

def parse_date(value):
    for fmt in ('%d %b %Y', '%d %B %Y', '%Y-%m-%d', '%d/%m/%Y'):
        try: return datetime.strptime(value.strip(), fmt).date()
        except ValueError: pass
    return None

@dataclass(frozen=True)
class Flow:
    day: date
    total: Decimal | None
    complete: bool

def parse_farside(html):
    parser = TableParser(); parser.feed(html)
    results = {}
    for table in parser.tables:
        header = next((r for r in table if r and r[0].lower() in ('date', '') and any(c.lower() == 'total' for c in r)), None)
        if not header: continue
        total_idx = next(i for i,c in enumerate(header) if c.lower() == 'total')
        if total_idx < 2: continue
        for row in table:
            day = parse_date(row[0]) if row else None
            if day is None: continue
            vals = [number(v) for v in row[1:total_idx+1]]
            complete = len(row) == len(header) and len(vals) == total_idx and all(v is not None for v in vals)
            # Published totals are rounded, permit cumulative 0.1m rounding error.
            if complete and abs(sum(vals[:-1]) - vals[-1]) > Decimal('0.1') * len(vals): complete = False
            total = number(row[total_idx]) if len(row) > total_idx else None
            flow = Flow(day, total, complete)
            if day in results and results[day] != flow: raise ValueError('conflicting duplicate date')
            results[day] = flow
    if not results: raise ValueError('dated flow table not found; schema may have changed')
    return results

def closed_sessions(now):
    # Real exchange calendar handles US holidays and early closes. Fail closed if unavailable.
    import exchange_calendars as xcals
    cal = xcals.get_calendar('XNYS')
    start = (now - timedelta(days=90)).date().isoformat()
    end = now.date().isoformat()
    return [s.date() for s in cal.sessions_in_range(start, end)
            if cal.session_close(s).to_pydatetime() <= now]

def summarize(flows, sessions):
    if not sessions: raise ValueError('no closed exchange sessions')
    expected = sessions[-1]
    eligible = [d for d in sessions if d in flows and flows[d].complete]
    if not eligible:
        return {'expected_session': str(expected), 'status': 'unavailable', 'latest_complete': None, 'five_session_total_musd': None}
    latest = eligible[-1]
    idx = sessions.index(latest)
    window = sessions[max(0, idx-4):idx+1]
    valid = len(window) == 5 and all(d in flows and flows[d].complete for d in window)
    return {'expected_session': str(expected), 'status': 'current' if latest == expected else 'stale',
            'latest_complete': str(latest), 'latest_total_musd': str(flows[latest].total),
            'five_session_dates': [str(d) for d in window],
            'five_session_flows': [{'date': str(d), 'total_musd': str(flows[d].total) if d in flows and flows[d].complete else None} for d in window],
            'five_session_total_musd': str(sum(flows[d].total for d in window)) if valid else None,
            'missing_or_incomplete_sessions': [str(d) for d in sessions if d >= window[0] and (d not in flows or not flows[d].complete)]}

def fetch(url, allowed_hosts):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in allowed_hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('source URL is not allowlisted HTTPS')
    # Redirects are disabled: never follow official URLs to unverified destinations.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    request = Request(url, headers={'User-Agent': 'MarketDigest/0.1 (+public-source-verification)'})
    with build_opener(NoRedirect).open(request, timeout=25) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError('source exceeds size limit')
        return raw.decode('utf-8')

class EvidenceParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.title = []; self.in_title = False; self.description = ''
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title': self.in_title = True
        if tag == 'meta' and (attrs.get('name') == 'description' or attrs.get('property') == 'og:description'):
            self.description = attrs.get('content', '')
    def handle_data(self, text):
        if self.in_title: self.title.append(text)
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False

def collect_announcements(urls, fetcher=fetch):
    results = []
    for url in urls:
        try:
            parser = EvidenceParser(); parser.feed(fetcher(url, OFFICIAL_HOSTS))
            title = ' '.join(''.join(parser.title).split())
            if not title or not parser.description: raise ValueError('insufficient page evidence')
            results.append({'url': url, 'status': 'candidate_only', 'title_quote': title[:300],
                            'description_quote': parser.description[:600],
                            'eligibility_deadline_rewards': 'not_verified'})
        except Exception:
            results.append({'url': url, 'status': 'unavailable'})
    return results

def readable_time(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None: return '时间未核实'
        return dt.astimezone(BJ).strftime('%Y年%m月%d日 %H:%M')
    except (ValueError, TypeError, AttributeError): return '时间未核实'


def readable_flow(value):
    amount = number(str(value)) if value is not None else None
    if amount is None: return '数据不完整，暂不计算'
    if amount == 0: return '净流量为零'
    direction = '净流入' if amount > 0 else '净流出'
    # Avoid presenting a small non-zero flow as 0.00 billion yuan/dollars.
    magnitude = abs(amount) / Decimal('100')
    digits = max(2, -magnitude.adjusted() + 1)
    return f'{direction} {magnitude:.{digits}f} 亿美元'


def key_point(item):
    """Use only short Chinese source headlines; never invent a translation or interpretation.

    Retain qualifiers and numbers intact. Long/foreign text stays in evidence JSON,
    not the short digest. Descriptions and full social posts are never rendered.
    """
    text = ' '.join(item.get('title_quote', '').split())
    if not re.search(r'[\u4e00-\u9fff]', text) or len(text) > 120:
        return None
    return text


def select_key_news(items, categories, limit=2):
    # Transparent keyword relevance, not an assertion of market impact.
    priority = ('非农', '非農', '美联储', '美聯儲', '利率', '通胀', '通膨',
                '暂停', '暫停', '被盗', '被盜', '駭客', '黑客', '破产', '破產',
                'ETF', '比特币', '比特幣', '以太坊', '财报', '財報')
    eligible = [i for i in items if i.get('category') in categories and i.get('published_at') and key_point(i)]
    if categories <= {'crypto', 'etf'}:
        crypto_terms = ('币', '幣', '链', '鏈', 'ETF', 'Bitcoin', 'Ethereum', 'BTC', 'ETH', 'Solana', 'USDT', 'USDC', 'DeFi')
        eligible = [i for i in eligible if any(term.casefold() in i['title_quote'].casefold() for term in crypto_terms)]
    eligible.sort(key=lambda i: (any(word in i['title_quote'] for word in priority), i['published_at']), reverse=True)
    selected, seen = [], set()
    for item in eligible:
        text = key_point(item)
        if text in seen: continue
        seen.add(text); selected.append(item)
        if len(selected) == limit: break
    return selected


def render(report):
    links = []
    def reference(url):
        if url not in links: links.append(url)
        return f"[{links.index(url) + 1}]"
    lines = [f"市场要点｜北京时间 {readable_time(report['generated_beijing'])}", '\nETF 资金流（美国交易日）']
    for asset, data in report['etf'].items():
        if data.get('latest_complete'):
            lines.append(f"• {asset} {data['latest_complete']}：{readable_flow(data.get('latest_total_musd'))}；截至该日近5交易日合计{readable_flow(data.get('five_session_total_musd'))}。{reference(SOURCES[asset])}")
        else:
            lines.append(f"• {asset}：数据暂缺，不按零计算。")
        if data['status'] == 'stale':
            lines.append(f"  更新滞后，应至 {data.get('expected_session', '未知')}；以上不是最新交易日数据。")
    news = report.get('news', {'sources': [], 'items': []})
    lines.append(f"\n市场重点（近{news.get('lookback_hours', 72)}小时）")
    shown = set()
    for label, categories in [('美股 / 宏观', {'us_stocks', 'macro'}), ('币圈', {'crypto', 'etf'})]:
        items = select_key_news(news['items'], categories)
        for item in items:
            if item['url'] in shown: continue
            shown.add(item['url'])
            lines.append(f"• {label}：{key_point(item)} {reference(item['url'])}")
        if not items: lines.append(f"• {label}：暂无可核实的简短中文要点。")
    lines.append('\n活动提醒')
    activities = report.get('activities', {'sources': [], 'items': []})
    by_exchange = {}
    for item in activities['items']:
        by_exchange.setdefault(item['exchange'], []).append(item)
    for exchange, items in by_exchange.items():
        label = '币安' if exchange == 'Binance' else exchange
        candidate = next((i for i in items if key_point(i)), None)
        if candidate:
            lines.append(f"• {label}：{key_point(candidate)} {reference(candidate['url'])}")
        else:
            # Do not reproduce untranslated originals or invent a summary of them.
            lines.append(f"• {label}：发现新活动线索，细则待核实。{reference(items[0]['url'])}")
    for item in report.get('announcements', [])[:2]:
        if item.get('status') == 'candidate_only' and key_point(item):
            lines.append(f"• {key_point(item)} {reference(item['url'])}")
    if not activities['items'] and not report.get('announcements'):
        lines.append('• 暂无可核实活动线索。')
    lines.append('活动仅查近7天列表：期限、地区、KYC、投入及奖励条件未核实，先核对再参与。')
    social = report.get('x_posts', {'status': 'not_configured', 'items': []})
    # Unverified exports are not promoted into factual key points or reposted.
    if social['items']:
        lines.append('\n马斯克 / X：导出内容尚未核验，暂不生成观点要点。')
    else:
        lines.append('\n马斯克 / X：自动监测未接通，不代表马斯克没有发帖。')
    gaps = []
    if any(s['status'] != 'ok' for s in news['sources']): gaps.append('部分新闻源未取得')
    for source in activities['sources']:
        if source['status'] != 'ok': gaps.append(('币安' if source['source'] == 'Binance' else source['source']) + '活动未接通或未取得')
    if gaps: lines.append('覆盖缺口：' + '；'.join(gaps) + '。')
    if links:
        lines.append('\n来源')
        lines.extend(f"[{index}] {url}" for index, url in enumerate(links, 1))
    lines.append('\n消息尚未逐项交叉核实；非投资建议。')
    return '\n'.join(lines)

def send_feishu(text):
    webhook = os.environ.get('FEISHU_WEBHOOK_URL', '')
    p = urlparse(webhook)
    if p.scheme != 'https' or p.hostname != 'open.feishu.cn' or p.username or p.password or p.port not in (None, 443) or not p.path.startswith('/open-apis/bot/v2/hook/'):
        raise ValueError('FEISHU_WEBHOOK_URL is missing or invalid')
    if len(text.encode('utf-8')) > 18000:
        raise ValueError('Report exceeds safe Feishu payload size; reduce feed limits before sending')
    payload = json.dumps({'msg_type':'text','content':{'text':text}}, ensure_ascii=False).encode()
    # Never log webhook, raw exceptions or response bodies. No retry: uncertain sends may duplicate.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    try:
        with build_opener(NoRedirect).open(Request(webhook, data=payload, headers={'Content-Type':'application/json'}), timeout=25) as response:
            result = json.loads(response.read(65536))
        code = result.get('code', result.get('StatusCode'))
        if type(code) is not int or code != 0: raise RuntimeError()
    except Exception:
        raise RuntimeError('Feishu send failed or uncertain; inspect delivery before retrying') from None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--send', action='store_true')
    ap.add_argument('--output', default='out')
    ap.add_argument('--sources', default=str(Path(__file__).with_name('sources.json')))
    ap.add_argument('--announcements', default=str(Path(__file__).with_name('announcements.json')))
    ap.add_argument('--x-posts', type=Path, help='Explicitly supplied authorized JSON export; never fetched from X')
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    report = {'generated_beijing': now.astimezone(BJ).isoformat(), 'etf': {}, 'announcements': []}
    try: sessions = closed_sessions(now)
    except Exception: sessions = []
    for asset, url in SOURCES.items():
        try:
            report['etf'][asset] = summarize(parse_farside(fetch(url, {'farside.co.uk'})), sessions)
        except Exception:
            report['etf'][asset] = {'status':'unavailable', 'reason':'source fetch, schema or calendar verification failed'}
    config = json.loads(Path(args.sources).read_text(encoding='utf-8'))
    report['news'] = collect_feeds(config, now, fetch)
    try:
        report['x_posts'] = import_x_posts(args.x_posts, now)
    except Exception:
        report['x_posts'] = {'status': 'unavailable', 'items': [], 'reason': 'invalid or unreadable supplied export'}
    urls = json.loads(Path(args.announcements).read_text(encoding='utf-8'))
    if not isinstance(urls, list) or len(urls) > 100 or not all(isinstance(u, str) for u in urls):
        raise ValueError('announcements must be a JSON array of at most 100 URLs')
    report['announcements'] = collect_announcements(urls)
    report['activities'] = collect_activities(now, fetch)
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    content = render(report); (output/'report.txt').write_text(content, encoding='utf-8')
    print(content)
    if args.send: send_feishu(content)

if __name__ == '__main__': main()

