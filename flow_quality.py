"""Strict Farside parsing and US exchange-session summaries."""
import math
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo('Asia/Shanghai')

class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None
    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.table = []
        elif tag == 'tr' and self.table is not None: self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            if any(k in ('colspan', 'rowspan') and v != '1' for k,v in attrs):
                self.cell = ['__SPAN__']
            else: self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip()); self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row); self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table); self.table = None

def number(text):
    text = text.strip().replace(',', '').replace('$', '').replace('−', '-')
    if text.lower() in ('', '-', '–', '—', 'n/a', 'na', 'pending'): return None
    if text.startswith('(') and text.endswith(')'): text = '-' + text[1:-1]
    value = float(text)
    if not math.isfinite(value): raise ValueError('Non-finite flow')
    return value

def source_date(text):
    match = re.fullmatch(r'(\d{1,2})\s*([A-Za-z]{3})\s*(\d{4})', text.strip())
    if not match: return None
    months = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.lower().split()
    return datetime(int(match[3]), months.index(match[2].lower()) + 1, int(match[1])).date().isoformat()

def parse_table(html, columns, optional_columns=()):
    parser = Tables(); parser.feed(html)
    days = {}
    for table in parser.tables:
        header = None
        previous = None
        for row in table:
            normalized = [re.sub(r'[\s*†‡]+', '', c).upper() for c in row]
            # Farside uses an empty date cell and Total on the preceding row.
            if (previous and len(previous) == len(normalized) and normalized[0] == ''
                    and normalized[-1] == '' and previous[-1] == 'TOTAL'
                    and any(c in normalized for c in columns)):
                normalized[0], normalized[-1] = 'DATE', 'TOTAL'
            previous = normalized
            if 'TOTAL' in normalized and 'DATE' in normalized and any(c in normalized for c in columns):
                if len(set(normalized)) != len(normalized): raise ValueError('Duplicate headers')
                unknown = set(normalized) - set(columns) - {'DATE','TOTAL'}
                if unknown: raise ValueError('Unknown ETF columns: ' + ', '.join(sorted(unknown)))
                missing = set(columns) - set(optional_columns) - set(normalized)
                if missing: raise ValueError('Missing required ETF headers: ' + ', '.join(sorted(missing)))
                header = normalized; continue
            if header is None or not row: continue
            date_index = header.index('DATE')
            date = source_date(row[date_index]) if len(row) > date_index else None
            if date is None: continue
            if len(row) != len(header): raise ValueError('Malformed dated row: ' + date)
            values = dict(zip(header, row))
            flows = {c: number(values[c]) if c in values else None for c in columns}
            total = number(values['TOTAL'])
            present = [flows[c] for c in columns if c in values]
            complete = all(v is not None for v in present)
            if complete and total is not None and abs(sum(present) - total) > 0.1 * (len(present) + 1):
                raise ValueError('Total does not match ETF flows: ' + date)
            # A published total can still be preliminary while funds are missing.
            day = {'date': date, 'flows': flows, 'total': total if complete else None}
            if date in days and days[date] != day: raise ValueError('Conflicting duplicate date: ' + date)
            days[date] = day
    if not days: raise ValueError('No recognizable dated ETF table; refusing to write data')
    return [days[d] for d in sorted(days)]

def completed_sessions(now, count=30):
    import pandas_market_calendars as mcal
    if now.tzinfo is None: raise ValueError('Query time must be timezone-aware')
    schedule = mcal.get_calendar('NYSE').schedule(start_date=(now - timedelta(days=100)).date(), end_date=now.date())
    closed = schedule[schedule['market_close'] <= now.astimezone(timezone.utc)]
    return [d.date().isoformat() for d in closed.index][-count:]

def summary(rows, total_index, sessions):
    by_date = {r[0]: r[total_index] for r in rows}
    window = sessions[-5:]
    values = [by_date.get(d) for d in window]
    complete = len(window) == 5 and all(v is not None for v in values)
    return {'dates': window, 'net': sum(values) if complete else None,
            'inflow_days': sum(v > 0 for v in values) if complete else None,
            'outflow_days': sum(v < 0 for v in values) if complete else None,
            'missing_dates': [d for d,v in zip(window, values) if v is None],
            'latest_source_date': max(by_date) if by_date else None,
            'expected_trade_date': sessions[-1] if sessions else None,
            'status': 'current' if complete else 'pending_or_stale'}
