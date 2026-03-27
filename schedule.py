"""
schedule.py — Generate weekly flight schedules from the flights DB.

Outputs (any combination via flags):
  --text    Pretty-print timetable to stdout  (default if no flags given)
  --html    Write schedule.html
  --csv     Write schedule.csv

Usage examples:
  python schedule.py                    # text to stdout
  python schedule.py --html --csv       # html + csv, no stdout
  python schedule.py --text --html --csv
"""

import argparse
import collections
import csv
import html as html_mod
import sqlite3
import sys
import datetime as _dt
from config import DB_PATH
import airlines as airlines_db

# ── Constants ────────────────────────────────────────────────────────────────

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DOW_MAP = {1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat', 0: 'Sun'}

# Colour palette for operator headers — cycles through for unknown operators
# Format: (bg, fg)
_PALETTE = [
    ('#2c3e50', '#fff'),
    ('#1a6b8a', '#fff'),
    ('#27ae60', '#fff'),
    ('#8e44ad', '#fff'),
    ('#c0392b', '#fff'),
    ('#d35400', '#fff'),
    ('#16a085', '#fff'),
    ('#2980b9', '#fff'),
]
_palette_index = {}  # { op: (bg, fg) }

def _palette_for(op):
    if op not in _palette_index:
        idx = len(_palette_index) % len(_PALETTE)
        _palette_index[op] = _PALETTE[idx]
    return _palette_index[op]

# Known operator metadata keyed by ICAO airline code.
# Any prefix found in the DB but absent here gets a sensible fallback in _operator_meta().
# Format: (full name, network role)  — colours assigned dynamically from palette
_KNOWN_OPERATORS = {
    # ── FedEx feeders ────────────────────────────────────────────────────────
    'BVN': ('Baron Aviation Services',   'FedEx feeder'),
    'CFS': ('Empire Airlines',           'FedEx feeder'),
    'CPT': ('Corporate Air',             'FedEx feeder'),
    'IRO': ('Iron Air (CSA Air Inc.)',   'FedEx feeder'),
    'MAL': ('Morningstar Air Express',   'FedEx feeder (CA)'),
    'MTN': ('Mountain Air Cargo',        'FedEx feeder'),
    'PCM': ('Westair Industries',        'FedEx feeder'),
    'SNC': ('Air Cargo Carriers',        'FedEx feeder'),
    'WIG': ('Wiggins Airways',           'FedEx feeder'),
    'AIG': ('Ameriflight',               'FedEx feeder'),
    # ── DHL feeders ──────────────────────────────────────────────────────────
    'BEZ': ('Kingfisher Air Services',   'DHL feeder'),
    'DHK': ('DHL Air (UK)',              'DHL feeder'),
    'DHX': ('DHL Air',                   'DHL feeder'),
    'VEC': ('Veca Airlines',             'DHL feeder'),
    'TJN': ('Trans-Jamaican Airlines',   'DHL feeder'),
    'BOX': ('Sky Lease Cargo',           'DHL feeder'),
    'JOS': ('Jota Aviation',             'DHL feeder'),
    'SET': ('Sierra Express',            'DHL feeder'),
}

AC_LABEL = {
    'C208': 'C208',
    'C408': 'C408',
    'ATR 42': 'ATR-42',
    'Cessna 750 Citation X': 'CIT-X',
}

AC_COLOR = {
    'C208': '#e8f4fd',
    'C408': '#d4edda',
    'ATR 42': '#fff3cd',
    'Cessna 750 Citation X': '#f8d7da',
}

HTML_OUT = 'schedule.html'
CSV_OUT  = 'schedule.csv'


# ── Helpers ───────────────────────────────────────────────────────────────────

def round5(hhmm: str) -> str:
    """Round an 'HH:MM' string to the nearest 5-minute increment."""
    if not hhmm or ':' not in hhmm:
        return hhmm
    h, m = map(int, hhmm.split(':'))
    total = h * 60 + m
    rounded = ((total + 2) // 5) * 5   # round half-up to nearest 5
    return f'{(rounded % 1440) // 60:02d}:{rounded % 60:02d}'


def _tail_network(tails):
    """Infer FedEx/DHL network role from tail number suffix conventions."""
    fedex = sum(1 for t in tails if t and (t.upper().endswith('FE') or t.upper().endswith('FX')))
    dhl   = sum(1 for t in tails if t and t.upper().endswith('HL'))
    if fedex > dhl and fedex > 0:
        return 'FedEx feeder'
    if dhl > fedex and dhl > 0:
        return 'DHL feeder'
    return ''


def _operator_meta(op, db_name=None, tails=None):
    """
    Return (name, network, bg_color, fg_color) for an operator prefix.
    Fallback chain:
    1. Hardcoded _KNOWN_OPERATORS table
    2. OpenFlights airlines.dat lookup by ICAO code
    3. Tail number suffix heuristic (FE/FX = FedEx, HL = DHL)
    4. airline_name stored in the flights DB
    5. Generic unknown label
    """
    bg, fg = _palette_for(op)

    if op in _KNOWN_OPERATORS:
        name, network = _KNOWN_OPERATORS[op]
        return (name, network, bg, fg)

    # OpenFlights lookup
    of_name, of_country = airlines_db.lookup(op)
    network = _tail_network(tails or [])
    if of_name:
        label = f"{of_name} ({of_country})" if of_country else of_name
        return (label, network, bg, fg)

    # Tail heuristic already computed above — use DB name if available
    if db_name:
        return (db_name, network, bg, fg)

    return (f'{op} (unknown)', network, bg, fg)


# ── Data loading ─────────────────────────────────────────────────────────────

def load_schedule():
    """
    Returns (sched, operators, generated_at, date_range) where:
      sched     = { op: { dow_int: [(dep, arr, dur, callsign, orig, from_city, dest, to_city, ac), ...] } }
      operators = { op: (name, network, bg, fg) }  — only operators actually in the DB
    """
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Load airlines reference data
    airlines_db.load_airlines()

    # Gather per-operator: most common airline_name and all tail numbers seen
    cur.execute("""
        SELECT substr(callsign, 1, 3) AS op, airline_name, tail
        FROM flights
        WHERE length(callsign) >= 4
          AND substr(callsign,1,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,2,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,3,1) BETWEEN 'A' AND 'Z'
    """)
    op_names = collections.defaultdict(collections.Counter)
    op_tails = collections.defaultdict(set)
    for op, name, tail in cur.fetchall():
        if name:
            op_names[op][name] += 1
        if tail:
            op_tails[op].add(tail)
    db_names = {op: counter.most_common(1)[0][0] for op, counter in op_names.items()}

    # Get distinct operator prefixes
    cur.execute("""
        SELECT DISTINCT substr(callsign, 1, 3) AS op
        FROM flights
        WHERE length(callsign) >= 4
          AND substr(callsign,1,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,2,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,3,1) BETWEEN 'A' AND 'Z'
        ORDER BY op
    """)
    operators = {
        row[0]: _operator_meta(row[0], db_names.get(row[0]), list(op_tails.get(row[0], [])))
        for row in cur.fetchall()
    }

    cur.execute("""
        SELECT
            substr(callsign, 1, 3)                          AS op,
            callsign,
            origin_icao,
            COALESCE(origin_city, origin_icao)              AS from_city,
            dest_icao,
            COALESCE(dest_city,  dest_icao)                 AS to_city,
            aircraft_type,
            CAST(strftime('%w', departure_time) AS INTEGER) AS dow,
            strftime('%H:%M', departure_time)               AS dep_utc,
            strftime('%H:%M', arrival_time)                 AS arr_utc,
            CAST(ROUND(duration_min) AS INTEGER)            AS dur_min
        FROM flights
        WHERE duration_min > 0
          AND length(callsign) >= 4
          AND substr(callsign,1,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,2,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,3,1) BETWEEN 'A' AND 'Z'
        ORDER BY op, dow, dep_utc
    """)
    rows = cur.fetchall()
    cur.execute("SELECT MIN(departure_time), MAX(departure_time) FROM flights")
    date_range = cur.fetchone()
    conn.close()

    sched = collections.defaultdict(lambda: collections.defaultdict(list))
    seen  = collections.defaultdict(lambda: collections.defaultdict(set))
    for op, cs, orig, fc, dest, tc, ac, dow, dep, arr, dur in rows:
        dep_r, arr_r = round5(dep), round5(arr)
        key = (cs, orig, dest, dep_r)
        if key not in seen[op][dow]:
            seen[op][dow].add(key)
            sched[op][dow].append((dep_r, arr_r, dur, cs, orig, fc, dest, tc, ac))

    generated_at = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return dict(sched), operators, generated_at, date_range


# ── Text output ───────────────────────────────────────────────────────────────

def print_schedule(sched, operators, generated_at, date_range):
    SEP  = '─' * 100
    SEP2 = '═' * 100
    dr_start = (date_range[0] or '')[:10]
    dr_end   = (date_range[1] or '')[:10]

    print(f'\n  WEEKLY FLIGHT SCHEDULE  —  All times UTC (rounded to nearest 5 min)')
    print(f'  Generated: {generated_at}   |   Data: {dr_start} → {dr_end}')

    for op in sorted(sched):
        name, network, _, _ = operators.get(op, (op, '?', '', ''))
        total = sum(len(v) for v in sched[op].values())
        days_active = len(sched[op])

        print(f'\n{SEP2}')
        print(f'  {op}  ·  {name}  ·  {network}  ·  {total} flights/week  ·  {days_active} operating days')
        print(SEP2)
        print(f'  {"FLIGHT":<11}  {"FROM":<28}  {"TO":<28}  {"DEP":>5}  {"ARR":>5}  {"DUR":>5}  {"A/C":<8}')
        print(f'  {"─"*11}  {"─"*28}  {"─"*28}  {"─"*5}  {"─"*5}  {"─"*5}  {"─"*8}')

        for day in DAYS:
            dow_num = next(k for k, v in DOW_MAP.items() if v == day)
            flights = sorted(sched[op].get(dow_num, []))
            if not flights:
                continue
            print(f'\n  ── {day} {"─"*90}')
            for dep, arr, dur, cs, orig, fc, dest, tc, ac in flights:
                ac_s   = AC_LABEL.get(ac, ac[:8])
                from_s = f'{orig} {fc}'[:28]
                to_s   = f'{dest} {tc}'[:28]
                print(f'  {cs:<11}  {from_s:<28}  {to_s:<28}  {dep:>5}  {arr:>5}  {dur:>4}m  {ac_s:<8}')

    print(f'\n{SEP}\n  {len(sched)} airlines  |  '
          f'{sum(sum(len(v) for v in d.values()) for d in sched.values())} total flights\n{SEP}\n')


# ── CSV output ────────────────────────────────────────────────────────────────

def write_csv(sched, operators, path=CSV_OUT):
    fields = ['operator', 'operator_name', 'network', 'day',
              'flight', 'origin_icao', 'origin_city',
              'dest_icao', 'dest_city',
              'dep_utc', 'arr_utc', 'duration_min', 'aircraft']
    rows = []
    for op in sorted(sched):
        name, network, _, _ = operators.get(op, (op, '?', '', ''))
        for day in DAYS:
            dow_num = next(k for k, v in DOW_MAP.items() if v == day)
            for dep, arr, dur, cs, orig, fc, dest, tc, ac in sorted(sched[op].get(dow_num, [])):
                rows.append({
                    'operator':      op,
                    'operator_name': name,
                    'network':       network,
                    'day':           day,
                    'flight':        cs,
                    'origin_icao':   orig,
                    'origin_city':   fc,
                    'dest_icao':     dest,
                    'dest_city':     tc,
                    'dep_utc':       dep,
                    'arr_utc':       arr,
                    'duration_min':  dur,
                    'aircraft':      AC_LABEL.get(ac, ac),
                })
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f'[schedule] CSV  → {path}  ({len(rows)} rows)', file=sys.stderr)


# ── HTML output ───────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; padding: 24px; color: #1a1a2e; }
h1 { font-size: 20px; margin-bottom: 4px; }
.meta { font-size: 12px; color: #888; margin-bottom: 28px; }
.airline-block { margin-bottom: 36px; border-radius: 10px; overflow: hidden;
                 box-shadow: 0 2px 12px rgba(0,0,0,.13); background: #fff; }
.airline-header { padding: 14px 20px; display: flex; align-items: center; gap: 16px; }
.airline-code { font-size: 28px; font-weight: 900; letter-spacing: 3px; }
.airline-name { font-size: 15px; font-weight: 700; }
.airline-network { font-size: 12px; opacity: .8; margin-top: 3px; }
.airline-stats { margin-left: auto; font-size: 12px; opacity: .8; text-align: right; line-height: 1.6; }
.day-section { border-top: 1px solid #eee; }
.day-label { background: #f7f8fa; padding: 7px 20px; font-size: 11px; font-weight: 700;
             color: #666; letter-spacing: 1.5px; text-transform: uppercase;
             border-bottom: 1px solid #eee; }
table { width: 100%; border-collapse: collapse; font-size: 13px;
        table-layout: fixed; }
col.c-flt  { width: 120px; }
col.c-from { width: 26%; }
col.c-to   { width: 26%; }
col.c-dep  { width: 90px; }
col.c-arr  { width: 90px; }
col.c-dur  { width: 60px; }
col.c-ac   { width: 72px; }
thead th { background: #fafafa; padding: 7px 12px; text-align: left; font-size: 11px;
           color: #999; font-weight: 700; letter-spacing: .5px; border-bottom: 2px solid #eee;
           overflow: hidden; white-space: nowrap; }
tbody tr { border-bottom: 1px solid #f2f2f2; transition: background .1s; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: #f5f8ff; }
td { padding: 6px 12px; vertical-align: middle;
     overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.flt  { font-family: 'Courier New', monospace; font-weight: 700; font-size: 13px; }
.icao { font-family: 'Courier New', monospace; font-size: 11px; color: #999;
        margin-right: 5px; }
.city { font-size: 13px; }
.time { font-family: 'Courier New', monospace; font-size: 13px; font-weight: 600; }
.dur  { font-size: 12px; color: #999; }
.ac   { display: inline-block; padding: 2px 7px; border-radius: 10px;
        font-size: 11px; font-weight: 700; font-family: monospace; }
"""

def _ac_badge(ac):
    bg = AC_COLOR.get(ac, '#eee')
    label = AC_LABEL.get(ac, ac[:8])
    return f'<span class="ac" style="background:{html_mod.escape(bg)}">{html_mod.escape(label)}</span>'

def write_html(sched, operators, generated_at, date_range, path=HTML_OUT):
    dr_start = (date_range[0] or '')[:10]
    dr_end   = (date_range[1] or '')[:10]
    total_flights = sum(sum(len(v) for v in d.values()) for d in sched.values())

    parts = [
        '<!DOCTYPE html><html lang="en"><head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Weekly Flight Schedule</title>',
        f'<style>{_CSS}</style>',
        '</head><body>',
        '<h1>&#9992;&nbsp; Weekly Flight Schedule</h1>',
        f'<p class="meta">All times UTC (rounded to nearest 5 min) &nbsp;·&nbsp; '
        f'Generated: {html_mod.escape(generated_at)}'
        f' &nbsp;·&nbsp; Data range: {html_mod.escape(dr_start)} → {html_mod.escape(dr_end)}'
        f' &nbsp;·&nbsp; {len(sched)} airlines &nbsp;·&nbsp; {total_flights} flights</p>',
    ]

    for op in sorted(sched):
        name, network, bg, fg = operators.get(op, (op, '?', '#666', '#fff'))
        total = sum(len(v) for v in sched[op].values())
        days_active = len(sched[op])

        parts += [
            '<div class="airline-block">',
            f'<div class="airline-header" style="background:{bg};color:{fg}">',
            f'<div class="airline-code">{html_mod.escape(op)}</div>',
            f'<div><div class="airline-name">{html_mod.escape(name)}</div>'
            f'<div class="airline-network">{html_mod.escape(network)}</div></div>',
            f'<div class="airline-stats">'
            f'{total} flights/week<br>{days_active} operating days</div>',
            '</div>',
        ]

        for day in DAYS:
            dow_num = next(k for k, v in DOW_MAP.items() if v == day)
            flights = sorted(sched[op].get(dow_num, []))
            if not flights:
                continue
            parts += [
                '<div class="day-section">',
                f'<div class="day-label">&#9992; {html_mod.escape(day)}</div>',
                '<table>',
                '<colgroup>'
                '<col class="c-flt"><col class="c-from"><col class="c-to">'
                '<col class="c-dep"><col class="c-arr"><col class="c-dur"><col class="c-ac">'
                '</colgroup>',
                '<thead><tr>',
                '<th>Flight</th><th>From</th><th>To</th>',
                '<th>Dep (UTC)</th><th>Arr (UTC)</th><th>Dur</th><th>A/C</th>',
                '</tr></thead><tbody>',
            ]
            for dep, arr, dur, cs, orig, fc, dest, tc, ac in flights:
                parts.append(
                    f'<tr>'
                    f'<td class="flt">{html_mod.escape(cs)}</td>'
                    f'<td><span class="icao">{html_mod.escape(orig)}</span>'
                    f'<span class="city">{html_mod.escape(fc[:24])}</span></td>'
                    f'<td><span class="icao">{html_mod.escape(dest)}</span>'
                    f'<span class="city">{html_mod.escape(tc[:24])}</span></td>'
                    f'<td class="time">{html_mod.escape(dep)}</td>'
                    f'<td class="time">{html_mod.escape(arr)}</td>'
                    f'<td class="dur">{dur}m</td>'
                    f'<td>{_ac_badge(ac)}</td>'
                    f'</tr>'
                )
            parts += ['</tbody></table></div>']

        parts.append('</div>')

    parts.append('</body></html>')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    print(f'[schedule] HTML → {path}', file=sys.stderr)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate weekly flight schedule from flights DB.'
    )
    parser.add_argument('--text', action='store_true', help='Print schedule to stdout')
    parser.add_argument('--html', action='store_true', help=f'Write {HTML_OUT}')
    parser.add_argument('--csv',  action='store_true', help=f'Write {CSV_OUT}')
    parser.add_argument('--html-out', default=HTML_OUT, metavar='PATH',
                        help=f'HTML output path (default: {HTML_OUT})')
    parser.add_argument('--csv-out',  default=CSV_OUT,  metavar='PATH',
                        help=f'CSV output path (default: {CSV_OUT})')
    args = parser.parse_args()

    # Default to --text if nothing specified
    if not any([args.text, args.html, args.csv]):
        args.text = True

    sched, operators, generated_at, date_range = load_schedule()

    if not sched:
        print('No flight data found in the database.', file=sys.stderr)
        sys.exit(1)

    if args.text:
        print_schedule(sched, operators, generated_at, date_range)
    if args.html:
        write_html(sched, operators, generated_at, date_range, path=args.html_out)
    if args.csv:
        write_csv(sched, operators, path=args.csv_out)


if __name__ == '__main__':
    main()
