#!/usr/bin/env python3
"""
BTC/ETH ETF 资金流向监控 + SQLite 数据库
每次运行：抓取最新 → 存入数据库 → 生成含全量历史趋势的报告
"""
import sqlite3, re, json, time, os
from datetime import datetime, timezone
from html import escape
from flow_quality import BEIJING, parse_table, completed_sessions, summary
from curl_cffi import requests

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_flows.db')
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
})

# ============================================================
# 数据库
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS btc_flows (
        date TEXT PRIMARY KEY,
        IBIT REAL, FBTC REAL, GBTC REAL, ARKB REAL, BITB REAL,
        HODL REAL, BRRR REAL, BTCW REAL, EZBC REAL, BTCO REAL,
        BTC REAL, DEFI REAL, total REAL,
        fetched_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS eth_flows (
        date TEXT PRIMARY KEY,
        ETHA REAL, ETHB REAL, FETH REAL, ETHW REAL,
        TETH REAL, ETHV REAL, QETH REAL, EZET REAL,
        ETHE REAL, ETH REAL,
        total REAL, fetched_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS prices (
        date TEXT PRIMARY KEY,
        btc_price REAL, eth_price REAL, fear_greed INTEGER,
        fetched_at TEXT
    )''')
    # Additive migration only; preserve old databases and all existing rows.
    for table, columns in [('btc_flows', BTC_COLS), ('eth_flows', ETH_COLS)]:
        existing = {row[1] for row in c.execute(f'PRAGMA table_info({table})')}
        for column in columns:
            if column not in existing:
                c.execute(f'ALTER TABLE {table} ADD COLUMN {column} REAL')
    conn.commit()
    conn.close()

def upsert_btc(date_str, flows, total):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cols = ['date','IBIT','FBTC','GBTC','ARKB','BITB','HODL','BRRR','BTCW','EZBC','BTCO','BTC','DEFI','MSBT','total','fetched_at']
    vals = [date_str]
    for col in cols[1:-1]:  # 跳过 date 和 fetched_at
        vals.append(flows.get(col))
    # total 已经在 cols[1:-1] 中了，用 flows 里的值覆盖
    vals[-1] = total
    vals.append(now)
    placeholders = ','.join(['?']*len(cols))
    c.execute(f'INSERT OR REPLACE INTO btc_flows ({",".join(cols)}) VALUES ({placeholders})', vals)
    conn.commit()
    conn.close()

def upsert_eth(date_str, flows, total):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cols = ['date','ETHA','ETHB','FETH','ETHW','TETH','ETHV','QETH','EZET','ETHE','ETH','MSSE','total','fetched_at']
    vals = [date_str]
    for col in cols[1:-1]:
        vals.append(flows.get(col))
    vals[-1] = total
    vals.append(now)
    placeholders = ','.join(['?']*len(cols))
    c.execute(f'INSERT OR REPLACE INTO eth_flows ({",".join(cols)}) VALUES ({placeholders})', vals)
    conn.commit()
    conn.close()

def upsert_price(date_str, btc, eth, fg):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO prices (date,btc_price,eth_price,fear_greed,fetched_at) VALUES (?,?,?,?,?)',
              (date_str, btc, eth, fg, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def get_all_btc():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(f'SELECT date,{chr(44).join(BTC_COLS)},total,fetched_at FROM btc_flows ORDER BY date').fetchall()
    conn.close()
    return rows

def get_all_eth():
    conn = sqlite3.connect(DB_PATH)
    # Use explicit column order matching new ETH_COLS
    rows = conn.execute(f'SELECT date,{chr(44).join(ETH_COLS)},total,fetched_at FROM eth_flows ORDER BY date').fetchall()
    conn.close()
    return rows

def get_all_prices():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT * FROM prices ORDER BY date').fetchall()
    conn.close()
    return rows

def get_db_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM btc_flows')
    btc = c.fetchone()
    c.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM eth_flows')
    eth = c.fetchone()
    c.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM prices')
    prices = c.fetchone()
    conn.close()
    return {'btc_days': btc, 'eth_days': eth, 'price_days': prices}

# ============================================================
# Farside 抓取
# ============================================================

BTC_COLS = ['IBIT','FBTC','GBTC','ARKB','BITB','HODL','BRRR','BTCW','EZBC','BTCO','BTC','DEFI','MSBT']
ETH_COLS = ['ETHA','ETHB','FETH','ETHW','TETH','ETHV','QETH','EZET','ETHE','ETH','MSSE']

def parse_farside(symbol, columns):
    url = f'https://farside.co.uk/{symbol}/'
    resp = session.get(url, impersonate='chrome131', timeout=30)
    resp.raise_for_status()
    days = parse_table(resp.text, columns, optional_columns={'DEFI'})
    today = datetime.now(BEIJING).date().isoformat()
    if any(d['date'] > today for d in days):
        raise ValueError('Future source date')
    return days

# ============================================================
# 价格 & 恐慌指数
# ============================================================

def get_price_data():
    """获取价格和恐慌指数，带重试"""
    btc, eth, fg = None, None, None
    for _ in range(3):
        try:
            r = session.get(
                'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true&include_last_updated_at=true',
                impersonate='chrome131', timeout=15)
            r.raise_for_status()
            d = r.json()
            stamp = time.time()
            if any(not 0 <= stamp - d[c]['last_updated_at'] <= 3600 for c in ('bitcoin','ethereum')):
                raise ValueError('Stale or future price timestamp')
            if any(not isinstance(d[c]['usd'], (int, float)) or not 0 < d[c]['usd'] < 1e12 for c in ('bitcoin','ethereum')):
                raise ValueError('Invalid price')
            btc = d['bitcoin']['usd']
            eth = d['ethereum']['usd']
            break
        except Exception: time.sleep(2)
    for _ in range(3):
        try:
            r = session.get('https://api.alternative.me/fng/?limit=1', impersonate='chrome131', timeout=15)
            r.raise_for_status()
            entry = r.json()['data'][0]
            candidate = int(entry['value'])
            if not 0 <= candidate <= 100 or not 0 <= time.time() - int(entry['timestamp']) <= 172800:
                raise ValueError('Stale or invalid fear/greed index')
            fg = candidate
            break
        except Exception: time.sleep(2)
    return btc, eth, fg

# ============================================================
# SVG 图表
# ============================================================

def svg_sparkline(values, width=380, height=45, up='#22c55e', down='#ef4444'):
    if not values or len(values) < 2: return ''
    clean = [v for v in values if v is not None]
    if len(clean) < 2: return ''
    mn, mx = min(clean), max(clean)
    rng = mx - mn or 1
    pad = 4
    w, h = width - pad*2, height - pad*2
    points = []
    for i, v in enumerate(values):
        if v is None: continue
        x = pad + (i/(len(values)-1))*w
        y = pad + h - ((v-mn)/rng)*h
        points.append(f'{x:.1f},{y:.1f}')
    path = 'M'+' L'.join(points)
    color = up if clean[-1] >= clean[0] else down
    fill_path = path + f' L{pad+w:.1f},{pad+h:.1f} L{pad:.1f},{pad+h:.1f} Z'
    return f'''<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="{color}" stop-opacity="0.3"/>
<stop offset="100%" stop-color="{color}" stop-opacity="0.02"/></linearGradient></defs>
<path d="{fill_path}" fill="url(#g)"/>
<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/></svg>'''

def svg_bar_chart(values, labels, width=380, height=55, up='#22c55e', down='#ef4444'):
    if not values: return ''
    mx = max(abs(max(values)), abs(min(values)), 1)
    bar_w = max(2, (width - 20) / len(values) - 1)
    bars = ''
    for i, v in enumerate(values):
        x = 8 + i * (width - 16) / len(values)
        h = abs(v) / mx * (height - 12) / 2
        y = height / 2 - h if v >= 0 else height / 2
        color = up if v >= 0 else down
        bars += f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h,0.5):.1f}" fill="{color}" rx="1" opacity="0.8"/>'
    bars += f'<line x1="8" y1="{height/2}" x2="{width-8}" y2="{height/2}" stroke="#cbd5e0" stroke-width="0.5"/>'
    return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">{bars}</svg>'

# ============================================================
# HTML 报告
# ============================================================

def flow_fmt(m):
    if m is None: return '待更新'
    if abs(m) >= 1000: return f'${m/1000:.1f}B'
    return f'${m:.1f}M'

def generate_html(btc_rows, eth_rows, price_rows, latest_btc, latest_eth, btc_price, eth_price, fg, new_dates, now):
    """基于数据库生成完整历史报告"""
    # 解析 DB 行
    btc_dates, btc_totals = [], []
    for r in btc_rows:
        if r[0] and r[len(BTC_COLS)+1] is not None:  # published total
            btc_dates.append(r[0][-5:])  # MM-DD
            btc_totals.append(float(r[len(BTC_COLS)+1]))  # explicit select order

    eth_dates, eth_totals = [], []
    for r in eth_rows:
        if r[0] and r[len(ETH_COLS)+1] is not None:
            eth_dates.append(r[0][-5:])
            eth_totals.append(float(r[len(ETH_COLS)+1]))  # explicit select order

    # 累计流
    btc_cum, cum = [], 0
    for v in btc_totals: cum += v; btc_cum.append(cum)
    eth_cum, cum = [], 0
    for v in eth_totals: cum += v; eth_cum.append(cum)

    sessions = completed_sessions(now)
    btc_summary = summary(btc_rows, len(BTC_COLS)+1, sessions)
    eth_summary = summary(eth_rows, len(ETH_COLS)+1, sessions)
    btc_30d_net = btc_summary['net']
    eth_30d_net = eth_summary['net']
    source_status = {}
    for symbol, days in [('BTC', latest_btc), ('ETH', latest_eth)]:
        latest = max((d['date'] for d in days), default=None)
        source_status[symbol] = {'source_trade_date': latest,
            'source_stale_or_pending': latest is None or not sessions or latest < sessions[-1]}
    quality = escape(json.dumps({'BTC': btc_summary, 'ETH': eth_summary,
                                'this_fetch': source_status}, ensure_ascii=False))

    in_days = sum(1 for v in btc_totals if v > 0)
    out_days = sum(1 for v in btc_totals if v < 0)

    # 图表
    show_n = min(40, len(btc_totals))
    btc_bar = svg_bar_chart(btc_totals[-show_n:], btc_dates[-show_n:], 380, 50)
    btc_line = svg_sparkline(btc_cum[-show_n:], 380, 40)
    eth_bar = svg_bar_chart(eth_totals[-show_n:], eth_dates[-show_n:], 380, 50)

    # 各 ETF 累计
    btc_etf_cum = {}
    for r in btc_rows:
        cols = ['IBIT','FBTC','GBTC','ARKB','BITB','HODL','BRRR','BTCW','EZBC','BTCO','BTC','DEFI','MSBT']
        for i, col in enumerate(cols):
            if r[i+1] is not None:
                btc_etf_cum[col] = btc_etf_cum.get(col, 0) + float(r[i+1])

    eth_etf_cum = {}
    for r in eth_rows:
        cols = ['ETHA','ETHB','FETH','ETHW','TETH','ETHV','QETH','EZET','ETHE','ETH','MSSE']
        for i, col in enumerate(cols):
            if r[i+1] is not None:
                eth_etf_cum[col] = eth_etf_cum.get(col, 0) + float(r[i+1])

    def etf_rows(cum_dict):
        rows = ''
        for t, tot in sorted(cum_dict.items(), key=lambda x: abs(x[1]), reverse=True):
            c = '#22c55e' if tot > 0 else '#ef4444'
            s = '+' if tot > 0 else ''
            rows += f'<tr><td><strong>{t}</strong></td><td style="text-align:right;color:{c};font-weight:600">{s}{flow_fmt(tot)}</td></tr>'
        return rows

    # 最近7个已存储交易日明细
    def recent_table(rows, cols, num=7):
        h = '<th>日期</th>' + ''.join(f'<th style="text-align:right">{c}</th>' for c in cols) + '<th style="text-align:right">合计</th>'
        r = ''
        for row in rows[-num:]:
            date = row[0][-5:] if row[0] else '?'
            cells = f'<td>{date}</td>'
            total = row[len(cols)+1]
            for i, col in enumerate(cols):
                v = row[i+1]
                if v is None:
                    cells += '<td style="text-align:right">待更新/不适用</td>'
                    continue
                color = '#22c55e' if v > 0 else ('#ef4444' if v < 0 else '#9ca3af')
                sign = '+' if v > 0 else ''
                cells += f'<td style="text-align:right;color:{color}">{sign}{flow_fmt(v) if v != 0 else "0"}</td>'
            tc = '#22c55e' if (total or 0) > 0 else ('#ef4444' if (total or 0) < 0 else '#9ca3af')
            ts = '+' if (total or 0) > 0 else ''
            cells += f'<td style="text-align:right;color:{tc};font-weight:600">{ts}{flow_fmt(total) if total != 0 else "0"}</td>'
            r += f'<tr>{cells}</tr>'
        return h, r

    btc_h, btc_rr = recent_table(btc_rows, ['IBIT','FBTC','GBTC','ARKB','BITB','HODL','BRRR','BTCW','EZBC','BTCO','BTC','DEFI','MSBT'])
    eth_h, eth_rr = recent_table(eth_rows, ['ETHA','ETHB','FETH','ETHW','TETH','ETHV','QETH','EZET','ETHE','ETH','MSSE'])

    # 新增提示
    new_badge = ''
    if new_dates:
        new_badge = f'<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:6px;font-size:11px;margin-left:8px">🆕 +{len(new_dates)}天新数据</span>'

    fg_color = '#22c55e' if (fg if fg is not None else 50) > 55 else ('#ef4444' if (fg if fg is not None else 50) < 45 else '#f59e0b')
    db = get_db_stats()

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=500,initial-scale=1">
<title>ETF 资金流向</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f0f4f8;padding:10px;max-width:500px;margin:0 auto;font-size:13px}}
.card{{background:#fff;border-radius:10px;padding:13px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.card-title{{font-size:14px;font-weight:700;color:#1e293b;margin-bottom:6px}}
.db-info{{font-size:10px;color:#94a3b8;margin-bottom:6px}}
.metrics{{display:flex;gap:5px;flex-wrap:wrap;margin:6px 0}}
.metric{{flex:1;min-width:70px;text-align:center;padding:7px 5px;background:#f8fafc;border-radius:8px}}
.metric-v{{font-size:15px;font-weight:700}}
.metric-l{{font-size:10px;color:#64748b;margin-top:1px}}
table{{width:100%;border-collapse:collapse;font-size:11px}}
th{{text-align:left;padding:4px 3px;color:#94a3b8;font-weight:500;font-size:10px;border-bottom:1px solid #e2e8f0}}
td{{padding:5px 3px;border-bottom:1px solid #f1f5f9}}
.chart{{margin:4px 0;text-align:center;overflow-x:auto}}
.chart svg{{max-width:100%;height:auto}}
.pos{{color:#22c55e}}.neg{{color:#ef4444}}.muted{{color:#94a3b8}}
.section{{font-size:12px;font-weight:700;color:#334155;margin:8px 0 4px;padding-left:4px;border-left:3px solid #3b82f6}}
.footer{{text-align:center;font-size:10px;color:#94a3b8;margin-top:6px;padding-bottom:10px}}
</style>
</head>
<body>
<div class="card">查询时间（北京时间）：{now.astimezone(BEIJING).isoformat(timespec='seconds')}<br>
资金流日期为美国交易日。最近五个已收盘交易日如有缺报，净额保持待更新。<br>
<small>{quality}</small><br>累计及图表仅统计已知值，不代表完整历史。旧版历史零值及错列无法自动追溯，建议核对源数据后重抓。</div>

<div class="card">
    <div class="card-title">📊 BTC/ETH ETF 资金流向{new_badge}</div>
    <div class="db-info">数据库: {db['btc_days'][0]}天 BTC | {db['eth_days'][0]}天 ETH | {db['btc_days'][1]} ~ {db['btc_days'][2]}</div>

    <div class="metrics">
        <div class="metric">
            <div class="metric-v">{f'${btc_price:,.0f}' if btc_price is not None else '待更新'}</div><div class="metric-l">BTC</div>
        </div>
        <div class="metric">
            <div class="metric-v">{f'${eth_price:,.0f}' if eth_price is not None else '待更新'}</div><div class="metric-l">ETH</div>
        </div>
        <div class="metric">
            <div class="metric-v" style="color:{fg_color}">{fg if fg is not None else '待更新'}</div><div class="metric-l">恐慌贪婪</div>
        </div>
        <div class="metric">
            <div class="metric-v {'pos' if (btc_30d_net or 0)>0 else 'neg'}">{flow_fmt(btc_30d_net)}</div><div class="metric-l">BTC 5交易日净流</div>
        </div>
        <div class="metric">
            <div class="metric-v {'pos' if (eth_30d_net or 0)>0 else 'neg'}">{flow_fmt(eth_30d_net)}</div><div class="metric-l">ETH 5交易日净流</div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-title">₿ BTC ETF 每日净流</div>
    <div class="chart">{btc_bar}</div>
    <div style="font-size:9px;color:#94a3b8;text-align:center">🟢流入 🔴流出 | 单位: 百万美元</div>
</div>

<div class="card">
    <div class="card-title">₿ BTC ETF 已知数据累计资金流</div>
    <div class="chart">{btc_line}</div>
    <div class="metrics">
        <div class="metric"><div class="metric-v">{in_days}</div><div class="metric-l pos">流入日</div></div>
        <div class="metric"><div class="metric-v">{out_days}</div><div class="metric-l neg">流出日</div></div>
        <div class="metric"><div class="metric-v {'pos' if (btc_30d_net or 0)>0 else 'neg'}">{flow_fmt(btc_30d_net)}</div><div class="metric-l">5交易日净流</div></div>
    </div>
</div>

<div class="section">BTC ETF 各ETF已知数据累计</div>
<table><tr><th>ETF</th><th style="text-align:right">累计</th></tr>{etf_rows(btc_etf_cum)}</table>

<div class="section">BTC ETF 最近7个已存储交易日</div>
<table><tr>{btc_h}</tr>{btc_rr}</table>

<div class="card">
    <div class="card-title">Ξ ETH ETF 每日净流</div>
    <div class="chart">{eth_bar}</div>
</div>

<div class="section">ETH ETF 各ETF已知数据累计</div>
<table><tr><th>ETF</th><th style="text-align:right">累计</th></tr>{etf_rows(eth_etf_cum)}</table>

<div class="section">ETH ETF 最近7个已存储交易日</div>
<table><tr>{eth_h}</tr>{eth_rr}</table>

<div class="footer">Farside Investors · CoinGecko · Alternative.me | {now.strftime('%Y-%m-%d %H:%M')} | 数据库: {db['btc_days'][0]}天</div>
</body></html>'''

# ============================================================
# 主流程
# ============================================================

def main():
    now = datetime.now(BEIJING)
    init_db()

    print(f"[{now.strftime('%H:%M:%S')}] 抓取 + 存入数据库...")

    existing_dates = {r[0] for r in get_all_btc()}

    # 抓取失败时中止，不能把旧缓存称为本次更新。
    btc_days = parse_farside('btc', BTC_COLS)
    eth_days = parse_farside('eth', ETH_COLS)

    # 存入数据库 + 统计新增
    new_btc = 0
    for d in btc_days:
        try:
            dt = datetime.strptime(d['date'], '%d %b %Y')
            date_str = dt.strftime('%Y-%m-%d')
        except:
            date_str = d['date']
        upsert_btc(date_str, d['flows'], d['total'])
        new_btc += 1

    new_eth = 0
    for d in eth_days:
        try:
            dt = datetime.strptime(d['date'], '%d %b %Y')
            date_str = dt.strftime('%Y-%m-%d')
        except:
            date_str = d['date']
        upsert_eth(date_str, d['flows'], d['total'])
        new_eth += 1

    # 价格
    btc_p, eth_p, fg = get_price_data()
    if btc_p:
        today = now.strftime('%Y-%m-%d')
        upsert_price(today, btc_p, eth_p, fg)

    print(f"  BTC: {new_btc}条 | ETH: {new_eth}条")

    # 从数据库读取全量历史
    btc_rows = get_all_btc()
    eth_rows = get_all_eth()
    price_rows = get_all_prices()

    # 生成报告
    html = generate_html(btc_rows, eth_rows, price_rows,
                        btc_days, eth_days,
                        btc_p, eth_p, fg,
                        [d['date'] for d in btc_days if d['date'] not in existing_dates], now)

    html_path = f'/tmp/etf_db_{now.strftime("%Y%m%d_%H%M")}.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    # 截图
    png_path = html_path.replace('.html', '.png')
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 500, 'height': 900})
            page.goto(f'file://{html_path}', timeout=15000)
            page.wait_for_timeout(1500)
            h = page.evaluate('() => Math.max(document.body.scrollHeight, 1200)')
            page.set_viewport_size({'width': 500, 'height': h + 20})
            page.screenshot(path=png_path, full_page=True)
            browser.close()
        print(f"  📸 {png_path}")
    except Exception as e:
        print(f"  ⚠ 截图: {e}")
        png_path = None

    print(json.dumps({
        'btc_latest': btc_days[-1]['total'] if btc_days else None,
        'eth_latest': eth_days[-1]['total'] if eth_days else None,
        'query_time_beijing': now.isoformat(),
        'btc_five_sessions': summary(btc_rows, len(BTC_COLS)+1, completed_sessions(now)),
        'eth_five_sessions': summary(eth_rows, len(ETH_COLS)+1, completed_sessions(now)),
        'btc_price': btc_p, 'eth_price': eth_p, 'fg': fg,
        'db_total_days': len(btc_rows),
        'png': png_path,
    }, indent=2, ensure_ascii=False))

    return png_path

if __name__ == '__main__':
    main()

