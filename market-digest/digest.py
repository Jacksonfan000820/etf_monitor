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

def render(report):
    lines = [f"市场数据日报 | 北京时间 {report['generated_beijing']}", 'ETF 净流量单位：百万美元；交易日期为美国交易日。']
    for asset, data in report['etf'].items():
        lines.append(f"{asset}: 状态 {data['status']}；最近完整日 {data.get('latest_complete') or '缺失'}；当日 {data.get('latest_total_musd', '缺失')}；5交易日合计 {data.get('five_session_total_musd') if data.get('five_session_total_musd') is not None else '缺失，不计算'}。")
        lines.append(f"预期最近已收盘日 {data.get('expected_session', '无法核实')}；来源 {SOURCES[asset]}")
    lines.append('交易所活动：仅收录配置的官方公告原文证据；不推断有效期、资格或收益。')
    if not report['announcements']: lines.append('币安 / Bitget / OKX：尚未接入自动活动发现，今天无已核实活动可列出；不代表这些平台没有活动。')
    for a in report['announcements']:
        lines.append(f"{a['status']} | {a.get('title_quote', '无法获取')} | {a['url']}")
        if a.get('description_quote'): lines.append('官方页面摘录：' + a['description_quote'])
    news = report.get('news', {'sources': [], 'items': []})
    lines.append('币圈 / 美股金融新闻：RSS 原文摘录，不是事实背书、实时行情或智能观点。')
    for source in news['sources']:
        lines.append(f"数据源 {source['source']}：{source['status']}，条目 {source.get('item_count', '未知')}")
    for item in news['items']:
        lines.append(f"[{item['category']}] {item['title_quote']} | 发布时间 {item['published_at'] or '未知'} | {item['url']}")
        if item['description_quote']: lines.append('来源摘录：' + item['description_quote'][:220])
    social = report.get('x_posts', {'status': 'not_configured', 'items': []})
    lines.append(f"马斯克 / X/KOL：{social['status']}；仅支持授权导出导入，未实现自动抓取或智能观点，导入真实性未独立验证。")
    for item in social['items']:
        lines.append(f"{item['author']} | {item['published_at']} | {item['text_quote']} | {item['url']}")
    lines.append('数据缺失不代表资金流为零；非投资建议。')
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
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    content = render(report); (output/'report.txt').write_text(content, encoding='utf-8')
    print(content)
    if args.send: send_feishu(content)

if __name__ == '__main__': main()

