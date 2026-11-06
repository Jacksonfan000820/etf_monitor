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


def render(report):
    lines = [f"市场日报｜北京时间 {readable_time(report['generated_beijing'])}",
             '一、比特币 / 以太坊现货 ETF', '金额为美元；下列日期均为美国交易日。']
    statuses = {'current': '已更新', 'stale': '更新滞后', 'unavailable': '暂未获取到可靠数据'}
    for asset, data in report['etf'].items():
        lines.append(f"\n{asset}｜{statuses.get(data['status'], '待核实')}")
        if data.get('latest_complete'):
            lines.append(f"{data['latest_complete']}：{readable_flow(data.get('latest_total_musd'))}")
            dates = data.get('five_session_dates', [])
            window = f"（{dates[0]} 至 {dates[-1]}）" if dates else ''
            lines.append(f"截至最近完整日的五交易日合计{window}：{readable_flow(data.get('five_session_total_musd'))}")
            for day in data.get('five_session_flows', []):
                lines.append(f"  {day['date']}：{readable_flow(day['total_musd'])}")
        else:
            lines.append('抓取、解析或交易日历校验未通过，本次不显示资金流数字。')
        if data['status'] == 'stale':
            lines.append(f"应更新至 {data.get('expected_session', '未知')}，最新完整数据尚未公布或未取得；以上不是最新交易日数据。")
        lines.append(f"来源：{SOURCES[asset]}")
    news = report.get('news', {'sources': [], 'items': []})
    lines.append('\n二、美股 / 美国金融与币圈要闻')
    lines.append(f"过去{news.get('lookback_hours', 72)}小时内来源标题摘录；中文来源优先，外文保留原文，不自动编译或推断。")
    groups = [('美股 / 美国金融', {'us_stocks', 'macro'}), ('币圈', {'crypto', 'etf'})]
    for label, categories in groups:
        lines.append(f"\n{label}")
        items = [item for item in news['items'] if item['category'] in categories and item.get('published_at')]
        # Prefer available Chinese headlines; do not fill a short digest with unrelated English boilerplate.
        chinese = [item for item in items if re.search(r'[\u4e00-\u9fff]', item['title_quote'])]
        if chinese: items = chinese
        # Bound the human digest, retaining all collected evidence in report.json.
        items.sort(key=lambda item: (bool(re.search(r'[\u4e00-\u9fff]', item['title_quote'])), item['published_at']), reverse=True)
        for item in items[:4]:
            lines.append(f"• {item['title_quote']}")
            lines.append(f"  {item['source']}｜北京时间 {readable_time(item['published_at'])}\n  {item['url']}")
        if not items: lines.append('本次未取得有明确发布时间的可用新闻。')
    failures = [s['source'] for s in news['sources'] if s['status'] != 'ok']
    if failures: lines.append('抓取未成功：' + '、'.join(failures) + '。不代表没有相关新闻。')
    undated = sum(not i.get('published_at') for i in news['items'])
    if undated: lines.append(f'{undated} 条来源记录没有可核实发布时间，未列入要闻。')
    lines.append('\n三、交易所活动')
    activities = report.get('activities', {'sources': [], 'items': []})
    lines.append('近七天官方列表线索，每所最多两条；不是可参加活动推荐。')
    for source in activities['sources']:
        label = {'Binance': '币安', 'OKX': 'OKX', 'Bitget': 'Bitget'}.get(source['source'], source['source'])
        if source['status'] == 'not_integrated': lines.append(f"{label}：自动发现尚未接通。官方活动入口：{source['url']}")
        elif source['status'] != 'ok': lines.append(f"{label}：本次官方活动列表抓取或解析失败。")
        elif not source.get('item_count'): lines.append(f"{label}：已读取的列表首页没有近七天候选，不代表平台没有其他活动。")
    for item in activities['items']:
        language = '（英文原文）' if item.get('language') == 'en' else ''
        lines.append(f"• {item['exchange']}{language}：{item['title_quote']}\n  公告发布：北京时间 {readable_time(item['published_at'])}\n  {item['url']}")
    if not activities['sources'] and not report['announcements']:
        lines.append('本次没有取得官方活动列表，不能据此判断平台是否有活动。')
    lines.append('所有候选的截止时间、地区、KYC、投入门槛及奖励条件均未核实；不要把公告发布时间当作活动截止时间。')
    for item in report['announcements']:
        lines.append(f"• {item.get('title_quote', '官方公告暂时无法读取')}\n  {item['url']}")
        if item.get('description_quote'): lines.append('  官方页面摘录：' + item['description_quote'][:300])
        lines.append('  仅为公告线索；截止时间、地区、KYC、投入门槛与奖励条件未核实，不能据此认定你有参与资格。')
    social = report.get('x_posts', {'status': 'not_configured', 'items': []})
    lines.append('\n四、马斯克 / X 动态')
    if not social['items']:
        lines.append('尚未接入可核验的 X 原帖自动监测，本次无可展示原帖；不代表马斯克没有发帖。')
    else:
        lines.append('以下来自授权导出，原文真实性尚未独立核实：')
        for item in social['items'][:3]:
            lines.append(f"{item['author']}｜北京时间 {readable_time(item['published_at'])}\n{item['text_quote'][:500]}\n{item['url']}")
    lines.append('\n数据缺失不等于资金流为零；新闻摘录不代表事实已交叉核实。非投资建议。')
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

