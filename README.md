# FlightScrapper

A generic flight tracking utility that builds a local SQLite database of completed flights, filtered by any combination of aircraft types and airline callsign prefixes. Works for any operator or aircraft type — configured out of the box for FedEx and DHL C208/C408 feeder operations as an example.

Uses four complementary data sources:
- **[adsb.lol](https://adsb.lol)** — free live ADS-B feed, polled every 60 seconds
- **[OurAirports](https://ourairports.com/data/)** — free CC0 airport database for origin/destination resolution
- **[OpenFlights](https://openflights.org/data.php)** — free airline name database for schedule display
- **[FlightAware AeroAPI](https://www.flightaware.com/commercial/aeroapi/)** or **[AeroDataBox](https://rapidapi.com/aedbx-aedbx/api/aerodatabox)** — optional historical enrichment (configurable, one key required)

Designed to run continuously on a free-tier cloud VM (Fly.io, Oracle Cloud, etc.) at near-zero cost.

---

## How it works

### Live ADS-B tracking (adsb.lol)

Every 60 seconds, FlightScrapper fetches all airborne aircraft matching the configured type(s) (e.g. `C208`, `C408`) from the adsb.lol API, then filters by callsign prefix (e.g. `BEZ`, `PCM`).

Each aircraft is tracked in memory. When an aircraft's altitude crosses 500ft upward, a takeoff is recorded and its position is snapped to the nearest airport in the OurAirports database. When the aircraft disappears from the feed below 3000ft for 5+ minutes, a landing is recorded and its last known position is snapped to the nearest airport.

If an aircraft is first seen already airborne but below 2000ft and its position snaps cleanly to a known airport, it is accepted as a near-takeoff join — handling cases where the poller first detects the aircraft just after liftoff (e.g. low-altitude ADS-B coverage areas like the Caribbean). Aircraft first seen above 2000ft are discarded as mid-flight joins.

A flight record is written to the database **only** when both origin and destination airports are successfully identified. Partial flights, unresolvable positions, and high-altitude mid-joins are silently discarded.

Any new tail number observed flying under a matching callsign prefix is added to `data/tails.json` and its history is fetched immediately from the configured enrichment provider.

### Historical enrichment (FlightAware or AeroDataBox)

Once every 24 hours, FlightScrapper runs a batch job against the configured history provider. For each known tail number not fetched in the last 7 days, it retrieves completed flight history and merges it into the database.

Duplicate detection uses callsign + aircraft type + origin + destination + departure date. When a duplicate is found, missing fields are filled in from the other source (e.g. airport names from history, max altitude from live tracking). If origin/destination differs between sources, the history source values are treated as authoritative.

Historical enrichment is **optional** — if no API key is configured the system runs on adsb.lol alone.

### Origin/destination resolution

Airport snapping uses the OurAirports CC0 dataset (~25,000 airports with ICAO codes). Priority rules:
1. A small airport within 500m always wins
2. Otherwise medium/large airports are preferred over small ones
3. Within the same tier, the closest wins
4. Fallback radius (3–10km) only considers medium/large airports

### Airline name resolution (schedule output)

Four-level fallback chain:
1. Hardcoded table of known operators (FedEx/DHL feeders)
2. OpenFlights airlines.dat lookup by ICAO prefix (~5,800 airlines)
3. Tail number suffix heuristic (FE/FX → FedEx feeder, HL → DHL feeder)
4. Airline name stored from history provider responses

---

## Tracked fields per flight

| Field | Description |
|---|---|
| `callsign` | Flight callsign (e.g. `BEZ321`) |
| `tail` | Aircraft registration / tail number (e.g. `N960HL`) |
| `aircraft_type` | ICAO type designator (e.g. `C208`) |
| `airline_name` | Airline name from history provider |
| `icao_hex` | Mode-S transponder hex code (adsb source only) |
| `origin_icao` | Departure airport ICAO code |
| `origin_name` / `origin_city` / `origin_region` / `origin_country` | Departure airport details |
| `origin_lat` / `origin_lon` | Departure position coordinates |
| `dest_icao` | Arrival airport ICAO code |
| `dest_name` / `dest_city` / `dest_region` / `dest_country` | Arrival airport details |
| `dest_lat` / `dest_lon` | Arrival position coordinates |
| `departure_time` | Takeoff timestamp (UTC ISO 8601) |
| `arrival_time` | Landing timestamp (UTC ISO 8601) |
| `duration_min` | Flight duration in minutes |
| `max_alt_ft` | Maximum observed altitude in feet, rounded to nearest 1,000 (live tracking only) |
| `flightaware_url` | Link to validate the flight on FlightAware |
| `source` | `adsb`, `flightaware`, or `aerodatabox` |
| `recorded_at` | When the record was written |

---

## Requirements

- Python 3.9+
- Internet access (adsb.lol + OurAirports CSV on first run)
- FlightAware or AeroDataBox API key (optional, for historical enrichment)

## Installation

```bash
git clone <repo-url>
cd FlightScrapper

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Configuration

All settings are in `config.py`:

### Filtering

| Setting | Description |
|---|---|
| `AIRCRAFT_TYPES` | List of ICAO type designators to track (e.g. `["C208", "C408"]`) |
| `CALLSIGN_PREFIXES` | Only track callsigns starting with these prefixes. Empty list = all callsigns |
| `KNOWN_TAILS` | Seed list of tail numbers to include in history batches from the start |

### Polling

| Setting | Default | Description |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `60` | How often to poll adsb.lol |
| `POLL_JITTER_SECONDS` | `10` | Random ± jitter added to each poll interval |

### Flight detection

| Setting | Default | Description |
|---|---|---|
| `TAKEOFF_ALTITUDE_FT` | `500` | Altitude threshold for normal takeoff detection |
| `NEAR_AIRPORT_ALT_FT` | `2000` | First observation below this + snaps to airport = accepted as near-takeoff join |
| `LANDING_ALTITUDE_FT` | `3000` | Maximum altitude when disappearing to count as a landing |
| `LANDING_TIMEOUT_SECONDS` | `300` | Seconds unseen before declaring an aircraft landed |
| `SNAP_RADIUS_KM_PRIMARY` | `3.0` | Primary airport snap radius in km |
| `SNAP_RADIUS_KM_FALLBACK` | `10.0` | Fallback snap radius if nothing found within primary |

### Historical enrichment provider

Set `HISTORY_PROVIDER` in `config.py` to choose your enrichment source:

```python
HISTORY_PROVIDER = "flightaware"   # or "aerodatabox"
```

History fetches are suppressed per tail for 7 days after a successful fetch (configurable via `FA_SUPPRESS_DAYS` in `tails.py`). When a new tail is discovered by the live poller, its history is fetched immediately.

---

#### FlightAware AeroAPI (recommended)

| Setting | Default | Description |
|---|---|---|
| `FLIGHTAWARE_API_KEY` | `""` | AeroAPI key — or set env var `FLIGHTAWARE_API_KEY` |
| `FLIGHTAWARE_LOOKBACK_DAYS` | `10` | Days of history to fetch per tail number (personal tier max) |
| `FLIGHTAWARE_BATCH_INTERVAL_HOURS` | `24` | How often to check for tails due for refresh |

**Coverage:** Global including Hawaii and Caribbean (own receiver network).
**Cost:** $5/month free credit (~1,000 calls at $0.005/result set). Pay-as-you-go above that, no minimum.

**Getting an API key:**
1. Sign up at [flightaware.com/aeroapi/portal](https://www.flightaware.com/aeroapi/portal)
2. The personal tier provides $5/month free credit with no subscription required

---

#### AeroDataBox (alternative)

| Setting | Default | Description |
|---|---|---|
| `AERODATABOX_API_KEY` | `""` | RapidAPI key — or set env var `AERODATABOX_API_KEY` |
| `AERODATABOX_LOOKBACK_DAYS` | `7` | Days of history to fetch per tail number |
| `AERODATABOX_BATCH_INTERVAL_HOURS` | `24` | How often to check for tails due for refresh |

**Coverage:** Good for US and Europe. Limited in Hawaii and Caribbean.
**Cost:** Free tier (600 units/month) or $5/month Basic plan (6,000 units, ~1,000 calls).

**Getting an API key:**
1. Sign up at [rapidapi.com](https://rapidapi.com/aedbx-aedbx/api/aerodatabox)
2. Subscribe to the AeroDataBox Basic plan

---

**Setting API keys** (never put them in `config.py` or commit to git):
```bash
# Add to ~/.zshrc or ~/.bashrc for persistence
export FLIGHTAWARE_API_KEY=your_key_here
# or
export AERODATABOX_API_KEY=your_key_here
source ~/.zshrc
```

**adsb.lol** requires no key — it is a free community ADS-B feed.

## Running

```bash
python main.py
```

On first run, the OurAirports airport database (~8MB CSV) is downloaded to `data/airports.csv`. This only happens once.

Example output:

```
FlightScrapper starting.
  Aircraft types : C208, C408
  Callsign filter: ['BEZ', 'PCM', ...]
  Poll interval  : 60s ± 10s
  History source : FlightAware — enabled (batch every 24h)
Loaded 32700 airports.
Loaded 12 known tail numbers.
Resumed 3 in-flight aircraft from buffer.
[2026-03-27 09:53:49 UTC] poll #1 — 7 aircraft matching filters
  Near-takeoff join: BEZ321 from TJSJ (San Juan) at 1200ft
  New tail discovered: N960HL — fetching history...
  History for N960HL: 7 fetched, 7 saved
[FlightAware] Starting batch for 8/12 tail(s) due for refresh...
  [FA] Saved: BEZ2321 TJSJ->TFFJ (2026-03-24)
  [FA] N960HL (1/8): 7 fetched, 7 saved, 0 already known
[FlightAware] Batch complete — 12 saved, 3 duplicates skipped.
```

Stop with `Ctrl+C` — active flights are saved to `buffer.json` and resumed on next start.

## Data files

| File | Description |
|---|---|
| `flights.db` | SQLite database of completed flights |
| `buffer.json` | In-flight tracker state, persisted for crash resilience |
| `data/airports.csv` | OurAirports database, downloaded on first run |
| `data/airlines.dat` | OpenFlights airline database, downloaded on first schedule run |
| `data/tails.json` | Known tail numbers with last history fetch timestamps |

None of these are committed to git.

## Generating schedules

`schedule.py` reads the flights database and produces a **weekly timetable** — grouped by airline, broken down by day — in three output formats.

### Usage

```bash
# Pretty-print to stdout (default if no flags given)
python3 schedule.py

# Write schedule.html (opens in any browser)
python3 schedule.py --html

# Write schedule.csv (import into Excel, Google Sheets, etc.)
python3 schedule.py --csv

# All three at once
python3 schedule.py --text --html --csv

# Custom output paths
python3 schedule.py --html --html-out reports/schedule.html \
                    --csv  --csv-out  reports/schedule.csv
```

### What it produces

Each output lists every **recorded flight per airline per day of the week**, sorted by departure time, with columns:

| Column | Description |
|---|---|
| Flight | Callsign (e.g. `BEZ321`) |
| From | Origin ICAO code + city |
| To | Destination ICAO code + city |
| Dep (UTC) | Departure time, rounded to nearest 5 min |
| Arr (UTC) | Arrival time, rounded to nearest 5 min |
| Dur | Flight duration in minutes |
| A/C | Aircraft type (`C208`, `C408`, …) |

Each airline gets a distinct colour from a rotating palette. Known operators have their network role displayed (e.g. FedEx feeder, DHL feeder). Unknown operators are resolved via OpenFlights or the airline name stored from the history provider.

### Output files

| File | Description |
|---|---|
| `schedule.html` | Styled browser timetable, one card per airline |
| `schedule.csv` | Flat file with one row per flight-day, suitable for spreadsheet analysis |

Neither file is committed to git — regenerate them any time from the live database.

---

## Querying the data

Use any SQLite client, or [Datasette](https://datasette.io/) for a browser UI with built-in CSV export:

```bash
pip install datasette
datasette flights.db
```

Then open `http://localhost:8001`.

Example queries:

```sql
-- All flights, newest first
SELECT callsign, tail, aircraft_type, origin_icao, origin_city, dest_icao, dest_city,
       departure_time, duration_min, source
FROM flights ORDER BY departure_time DESC;

-- Caribbean routes only
SELECT * FROM flights WHERE origin_country = 'PR' OR dest_country = 'PR'
ORDER BY departure_time DESC;

-- Most common routes
SELECT origin_icao, origin_city, dest_icao, dest_city, COUNT(*) as count
FROM flights
GROUP BY origin_icao, dest_icao
ORDER BY count DESC;

-- Flights by source
SELECT source, COUNT(*) as count FROM flights GROUP BY source;

-- Average duration per route
SELECT origin_icao, dest_icao, ROUND(AVG(duration_min)) as avg_min, COUNT(*) as flights
FROM flights
GROUP BY origin_icao, dest_icao
ORDER BY avg_min DESC;
```

## Data sources

| Source | Use | Cost | Key required |
|---|---|---|---|
| [adsb.lol](https://adsb.lol) | Live ADS-B polling | Free | No |
| [OurAirports](https://ourairports.com/data/) | Airport database for O/D resolution | Free (CC0) | No |
| [OpenFlights](https://openflights.org/data.php) | Airline name lookup for schedule display | Free (ODbL) | No |
| [FlightAware AeroAPI](https://www.flightaware.com/commercial/aeroapi/) | Historical enrichment (recommended) | $5/month free credit | Yes |
| [AeroDataBox via RapidAPI](https://rapidapi.com/aedbx-aedbx/api/aerodatabox) | Historical enrichment (alternative) | Free (600 units) or $5/month | Yes |

### Why these sources?

**adsb.lol for live polling:**
The key requirement was a native filter by ICAO aircraft type (e.g. `C208`) so we only receive relevant aircraft without downloading the entire global feed. adsb.lol is the only free community ADS-B source with a `/v2/type/{aircraft_type}` endpoint. Alternatives considered:

- **adsb.fi** — identical data quality and better-documented use policy, but no type filter endpoint; only supports lookup by hex, callsign, registration, or lat/lon radius
- **ADSBexchange** — no public API; would require scraping their web UI
- **airplanes.live** — no documented use policy for automated polling
- **OpenSky Network** — no native type filter; 400 API credits/day on free tier; historical data only via research account registration

**FlightAware AeroAPI for historical enrichment (recommended):**
Provides global coverage including Hawaii and Caribbean via their own receiver network. Personal tier gives $5/month free credit (~1,000 calls at $0.005/result set) with no subscription commitment. Supports 10-day lookback on the personal tier.

**AeroDataBox as alternative:**
Good US/Europe coverage at $5/month for 6,000 units (~1,000 calls). Limited in Hawaii and Caribbean. 7-day lookback on the basic tier.

**Alternatives not chosen:**
- **FlightRadar24 API** — no free tier; $9/month minimum
- **Aviationstack** — historical data requires paid plan starting at $49.99/month
- **OpenSky Network** — community feeders only; poor Hawaii/Caribbean coverage

## Limitations

- Flights first seen above 2000ft are discarded (no mid-flight join recovery)
- adsb.lol ADS-B coverage is sparse in Hawaii and some remote areas — history enrichment mitigates this
- adsb.lol may require an API key in future (see their documentation)
- FlightAware personal tier rate limit: 10 requests/minute

## Deployment

To run on a free-tier cloud VM (Fly.io example):

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly launch
fly volumes create flightscrapper_data --size 1
fly deploy
```

Ensure the persistent volume is mounted at `/data` and set `DB_PATH`, `BUFFER_PATH`, `AIRPORTS_CSV_PATH`, and `TAILS_PATH` in `config.py` to use `/data/` as the base directory.

Set the API key as a Fly.io secret:

```bash
fly secrets set FLIGHTAWARE_API_KEY=your_key_here
```
