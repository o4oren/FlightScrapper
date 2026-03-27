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
import airports as airports_db

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
VCI_OUT  = 'schedule_vci.csv'


def _known_icao(icao):
    """Return True if the ICAO code resolves to a known airport in OurAirports."""
    return airports_db.lookup_by_icao(icao) is not None


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

    # Load reference data
    airlines_db.load_airlines()
    if not airports_db._airports:
        airports_db.load_airports()

    # Gather per-operator: most common airline_name and all tail numbers seen
    cur.execute("""
        SELECT substr(callsign, 1, 3) AS op, airline_name, tail
        FROM flights
        WHERE length(callsign) >= 4
          AND origin_icao IS NOT NULL AND origin_icao != ''
          AND dest_icao IS NOT NULL AND dest_icao != ''
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
            origin_icao                                     AS from_city,
            dest_icao,
            dest_icao                                       AS to_city,
            aircraft_type,
            CAST(strftime('%w', departure_time) AS INTEGER) AS dow,
            strftime('%H:%M', departure_time)               AS dep_utc,
            strftime('%H:%M', arrival_time)                 AS arr_utc,
            CAST(ROUND(duration_min) AS INTEGER)            AS dur_min
        FROM flights
        WHERE duration_min > 0
          AND origin_icao IS NOT NULL AND origin_icao != ''
          AND dest_icao IS NOT NULL AND dest_icao != ''
          AND origin_icao != dest_icao
          AND length(callsign) >= 4
          AND substr(callsign,1,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,2,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,3,1) BETWEEN 'A' AND 'Z'
        ORDER BY op, dow, dep_utc
    """)
    rows = [r for r in cur.fetchall() if _known_icao(r[2]) and _known_icao(r[4])]
    cur.execute("SELECT MIN(departure_time), MAX(departure_time) FROM flights")
    date_range = cur.fetchone()
    conn.close()

    sched = collections.defaultdict(lambda: collections.defaultdict(list))
    seen  = collections.defaultdict(lambda: collections.defaultdict(set))
    for op, cs, orig, _, dest, _, ac, dow, dep, arr, dur in rows:
        if orig == dest:
            continue  # skip same-airport records
        ap_orig = airports_db.lookup_by_icao(orig)
        ap_dest = airports_db.lookup_by_icao(dest)
        fc = ap_orig["city"] if ap_orig and ap_orig.get("city") else orig
        tc = ap_dest["city"] if ap_dest and ap_dest.get("city") else dest
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


def load_map_routes():
    """
    Return deduplicated routes per operator with coordinates for the map.
    Each route: (op, callsign, origin_icao, dest_icao, orig_lat, orig_lon, dest_lat, dest_lon,
                 origin_city, dest_city)
    Only includes routes where all four coordinates are present.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            substr(callsign, 1, 3) AS op,
            callsign,
            origin_icao, dest_icao,
            origin_lat, origin_lon,
            dest_lat, dest_lon,
            origin_icao AS origin_city,
            dest_icao   AS dest_city
        FROM flights
        WHERE origin_lat IS NOT NULL AND origin_lon IS NOT NULL
          AND dest_lat IS NOT NULL AND dest_lon IS NOT NULL
          AND origin_icao IS NOT NULL AND origin_icao != ''
          AND dest_icao IS NOT NULL AND dest_icao != ''
          AND origin_icao != dest_icao
          AND duration_min > 0
          AND length(callsign) >= 4
          AND substr(callsign,1,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,2,1) BETWEEN 'A' AND 'Z'
          AND substr(callsign,3,1) BETWEEN 'A' AND 'Z'
        GROUP BY substr(callsign,1,3), origin_icao, dest_icao
        ORDER BY op, origin_icao, dest_icao
    """)
    rows = cur.fetchall()
    conn.close()
    def _city(icao):
        ap = airports_db.lookup_by_icao(icao)
        return ap["city"] if ap and ap.get("city") else icao

    return [
        (op, cs, orig, dest, olat, olon, dlat, dlon, _city(orig), _city(dest))
        for op, cs, orig, dest, olat, olon, dlat, dlon, _, _2
        in rows
        if _known_icao(orig) and _known_icao(dest)
    ]


def _build_map_html(routes, operators):
    """Build a Leaflet map with geodesic lines per airline, embedded as HTML."""
    import json as _json

    # Group routes by operator
    by_op = collections.defaultdict(list)
    for op, cs, orig, dest, olat, olon, dlat, dlon, ocity, dcity in routes:
        by_op[op].append({
            'callsign': cs, 'orig': orig, 'dest': dest,
            'olat': olat, 'olon': olon, 'dlat': dlat, 'dlon': dlon,
            'ocity': ocity, 'dcity': dcity,
        })

    # Build per-operator JS data
    op_data = []
    for op in sorted(by_op):
        _, _, bg, _ = operators.get(op, (op, '', '#888', '#fff'))
        op_data.append({'op': op, 'color': bg, 'routes': by_op[op]})

    data_json = _json.dumps(op_data)

    # Build legend HTML
    legend_items = ''.join(
        f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">'
        f'<span style="display:inline-block;width:24px;height:3px;background:{d["color"]};border-radius:2px"></span>'
        f'<span style="font-size:12px;color:#333">{html_mod.escape(d["op"])}</span>'
        f'</div>'
        for d in op_data
    )

    return f"""
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.geodesic@2.7.1/dist/leaflet.geodesic.umd.min.js"></script>
<div id="map-section" style="margin-bottom:28px">
  <div id="map-wrapper" style="position:relative;height:500px;min-height:200px;resize:vertical;overflow:hidden;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.13)">
    <div id="route-map" style="height:100%;width:100%"></div>
    <div id="map-legend" style="position:absolute;top:10px;right:10px;z-index:1000;background:rgba(255,255,255,0.92);border-radius:8px;padding:10px 12px;box-shadow:0 1px 6px rgba(0,0,0,.15);max-height:80%;overflow-y:auto">
      <div style="font-size:11px;font-weight:700;color:#666;letter-spacing:.5px;margin-bottom:6px;text-transform:uppercase">Airlines</div>
      {legend_items}
    </div>
    <div id="map-resize-hint" style="position:absolute;bottom:4px;left:50%;transform:translateX(-50%);font-size:10px;color:#999;pointer-events:none">⬍ drag to resize</div>
  </div>
</div>
<script>
(function(){{
  var map = L.map('route-map', {{zoomControl:true}}).setView([30, -40], 3);
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd', maxZoom: 19
  }}).addTo(map);

  // Invalidate map size when wrapper is resized
  var wrapper = document.getElementById('map-wrapper');
  var ro = new ResizeObserver(function() {{ map.invalidateSize(); }});
  ro.observe(wrapper);

  var data = {data_json};
  var airports = {{}};

  data.forEach(function(airline) {{
    var color = airline.color;
    airline.routes.forEach(function(r) {{
      var line = L.geodesic(
        [[r.olat, r.olon], [r.dlat, r.dlon]],
        {{weight: 1.5, color: color, opacity: 0.8}}
      ).addTo(map);
      line.bindPopup(
        '<b>' + r.callsign + '</b><br>' +
        r.orig + ' (' + r.ocity + ') &rarr; ' + r.dest + ' (' + r.dcity + ')'
      );

      [
        [r.olat, r.olon, r.orig, r.ocity],
        [r.dlat, r.dlon, r.dest, r.dcity]
      ].forEach(function(ap) {{
        var key = ap[2];
        if (!airports[key]) {{
          airports[key] = L.circleMarker([ap[0], ap[1]], {{
            radius: 4, color: '#fff', weight: 1.5,
            fillColor: '#333', fillOpacity: 0.9
          }}).addTo(map).bindPopup('<b>' + ap[2] + '</b><br>' + ap[3]);
        }}
      }});
    }});
  }});
}})();
</script>
"""


def write_html(sched, operators, generated_at, date_range, path=HTML_OUT):
    dr_start = (date_range[0] or '')[:10]
    dr_end   = (date_range[1] or '')[:10]
    total_flights = sum(sum(len(v) for v in d.values()) for d in sched.values())

    routes = load_map_routes()
    map_html = _build_map_html(routes, operators) if routes else ''

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
        map_html,
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


# ── VCI export ────────────────────────────────────────────────────────────────

import math

def _haversine_nm(lat1, lon1, lat2, lon2):
    """Return great-circle distance in nautical miles."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R_nm = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return round(R_nm * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def load_vci_data():
    """
    Load one representative record per unique callsign + origin + dest combination.
    Prefers records with a route field set; falls back to most recent.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Use a subquery to rank: records with route first, then by most recent departure.
    # SQLite's GROUP BY picks the row that satisfies the aggregate — we use MIN on a
    # sort key that puts route-having rows first.
    cur.execute("""
        SELECT
            callsign,
            substr(callsign, 1, 3)                          AS op,
            substr(callsign, 4)                             AS flight_num,
            origin_icao, dest_icao,
            route,
            aircraft_type,
            max_alt_ft,
            origin_lat, origin_lon, dest_lat, dest_lon,
            strftime('%H:%M', departure_time)               AS dep_utc,
            strftime('%H:%M', arrival_time)                 AS arr_utc,
            CAST(ROUND(duration_min) AS INTEGER)            AS dur_min,
            flightaware_url,
            departure_time,
            airline_name
        FROM (
            SELECT *,
                   CASE WHEN route IS NOT NULL AND route != '' THEN 0 ELSE 1 END AS route_rank
            FROM flights
            WHERE duration_min > 0
              AND origin_icao IS NOT NULL AND origin_icao != ''
              AND dest_icao IS NOT NULL AND dest_icao != ''
              AND origin_icao != dest_icao
              AND length(callsign) >= 4
              AND substr(callsign,1,1) BETWEEN 'A' AND 'Z'
              AND substr(callsign,2,1) BETWEEN 'A' AND 'Z'
              AND substr(callsign,3,1) BETWEEN 'A' AND 'Z'
            ORDER BY callsign, origin_icao, dest_icao, route_rank ASC, departure_time DESC
        )
        GROUP BY callsign, origin_icao, dest_icao
        ORDER BY op, callsign, origin_icao, dest_icao
    """)
    # r[3]=origin_icao, r[4]=dest_icao
    rows = [r for r in cur.fetchall()
            if _known_icao(r[3]) and _known_icao(r[4]) and r[3] != r[4]]
    conn.close()
    return rows


def write_vci_csv(operators, path=VCI_OUT):
    rows = load_vci_data()
    fields = [
        'Airline Code', 'Flight number', 'ICAO-Departure', 'ICAO-Arrival',
        'Route (without SID/STAR)', 'Aircraft', 'Flightlevel (ft)',
        'Distance (nm)', 'Departure time (hh:mm)', 'Arrival time (hh:mm)',
        'Flight time (minutes)', 'Link to Approve (Flightaware)',
        'Operator', 'Company',
    ]
    out_rows = []
    for (callsign, op, flight_num, orig, dest, route, ac, max_alt,
         orig_lat, orig_lon, dest_lat, dest_lon,
         dep, arr, dur, fa_url, dep_time, airline_name) in rows:

        name, network, _, _ = operators.get(op, (airline_name or f'{op} (unknown)', '', '', ''))
        dep_r = round5(dep) if dep else ''
        arr_r = round5(arr) if arr else ''
        dist = _haversine_nm(orig_lat, orig_lon, dest_lat, dest_lon)

        out_rows.append({
            'Airline Code':                  op,
            'Flight number':                 flight_num,
            'ICAO-Departure':                orig,
            'ICAO-Arrival':                  dest,
            'Route (without SID/STAR)':      route or '',
            'Aircraft':                      AC_LABEL.get(ac, ac or ''),
            'Flightlevel (ft)':              max_alt or '',
            'Distance (nm)':                 dist or '',
            'Departure time (hh:mm)':        dep_r,
            'Arrival time (hh:mm)':          arr_r,
            'Flight time (minutes)':         dur or '',
            'Link to Approve (Flightaware)': fa_url or '',
            'Operator':                      network or '',
            'Company':                       name or '',
        })

    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f'[schedule] VCI → {path}  ({len(out_rows)} rows)', file=sys.stderr)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate weekly flight schedule from flights DB.'
    )
    parser.add_argument('--text', action='store_true', help='Print schedule to stdout')
    parser.add_argument('--html', action='store_true', help=f'Write {HTML_OUT}')
    parser.add_argument('--csv',  action='store_true', help=f'Write {CSV_OUT}')
    parser.add_argument('--vci',  action='store_true', help=f'Write {VCI_OUT} (VCI import format)')
    parser.add_argument('--html-out', default=HTML_OUT, metavar='PATH',
                        help=f'HTML output path (default: {HTML_OUT})')
    parser.add_argument('--csv-out',  default=CSV_OUT,  metavar='PATH',
                        help=f'CSV output path (default: {CSV_OUT})')
    parser.add_argument('--vci-out',  default=VCI_OUT,  metavar='PATH',
                        help=f'VCI CSV output path (default: {VCI_OUT})')
    args = parser.parse_args()

    # Default to --text if nothing specified
    if not any([args.text, args.html, args.csv, args.vci]):
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
    if args.vci:
        write_vci_csv(operators, path=args.vci_out)


if __name__ == '__main__':
    main()
