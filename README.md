# FlightScrapper

Tracks cargo feeder flights by aircraft type and airline callsign, building a local SQLite database of completed flights with full origin/destination detail.

Uses two complementary data sources:
- **[adsb.lol](https://adsb.lol)** — free live ADS-B feed, polled every 60 seconds, good coverage of the continental US and most major regions
- **[FlightAware AeroAPI](https://www.flightaware.com/commercial/aeroapi/)** — optional enrichment, fetches 14 days of history per tail number weekly, fills gaps in ADS-B coverage (Caribbean, remote areas)

Designed to run continuously on a free-tier cloud VM (Fly.io, Oracle Cloud, etc.) at near-zero cost.

---

## How it works

### Live ADS-B tracking (adsb.lol)

Every 60 seconds, FlightScrapper fetches all airborne aircraft matching the configured type(s) (e.g. `C208`, `C408`) from the adsb.lol API, then filters by callsign prefix (e.g. `FDX`, `DHX`).

Each aircraft is tracked in memory. When an aircraft's altitude crosses 500ft upward, a takeoff is recorded and its position is snapped to the nearest airport in the [OurAirports](https://ourairports.com/data/) database. When the aircraft disappears from the feed below 3000ft for 5+ minutes, a landing is recorded and its last known position is snapped to the nearest airport.

If an aircraft is first seen already airborne but below 2000ft and its position snaps cleanly to a known airport, it is accepted as a near-takeoff join — handling cases where the poller first detects the aircraft just after liftoff (e.g. low-altitude ADS-B coverage areas like the Caribbean). Aircraft first seen above 2000ft are discarded as mid-flight joins.

A flight record is written to the database **only** when both origin and destination airports are successfully identified. Partial flights, unresolvable positions, and high-altitude mid-joins are silently discarded.

Any new tail number observed flying under a matching callsign prefix is added to `data/tails.json` for FlightAware enrichment.

### FlightAware batch enrichment

Once every 24 hours, FlightScrapper runs a batch job against the FlightAware AeroAPI. For each known tail number that has not been successfully fetched in the last **7 days**, it calls `GET /flights/{tail}` to retrieve up to 14 days of completed flight history with authoritative origin, destination, and times.

Each returned flight is inserted into the database only if no record with the same callsign, aircraft type, origin, destination, and departure date already exists (deduplication). On success, the tail's last-fetch timestamp is updated — suppressing it from the next 7 days of batches.

This makes FlightAware coverage additive: it fills in flights that ADS-B missed (Caribbean routes, coverage gaps) without duplicating what adsb.lol already captured.

FlightAware enrichment is **optional** — if no API key is configured the system runs on adsb.lol alone.

### Origin/destination resolution

Airport snapping uses the OurAirports CC0 dataset (~25,000 airports with ICAO codes). At takeoff/landing, the aircraft's position is matched to the nearest airport within 3km (expanding to 10km if nothing is found). If no airport is found within 10km, the flight is discarded.

For scheduled cargo feeder operations this is reliable — these aircraft always depart from and arrive at real airports.

---

## Tracked fields per flight

| Field | Description |
|---|---|
| `callsign` | Flight callsign (e.g. `FDX1234`) |
| `tail` | Aircraft registration / tail number (e.g. `N208FE`) |
| `aircraft_type` | ICAO type designator (e.g. `C208`) |
| `icao_hex` | Mode-S transponder hex code (adsb source only) |
| `origin_icao` | Departure airport ICAO code |
| `origin_name` | Departure airport name |
| `origin_city` | Departure city |
| `origin_region` | Departure state/province |
| `origin_country` | Departure country code |
| `origin_lat` / `origin_lon` | Departure position coordinates |
| `dest_icao` | Arrival airport ICAO code |
| `dest_name` | Arrival airport name |
| `dest_city` | Arrival city |
| `dest_region` | Arrival state/province |
| `dest_country` | Arrival country code |
| `dest_lat` / `dest_lon` | Arrival position coordinates |
| `departure_time` | Takeoff timestamp (UTC ISO 8601) |
| `arrival_time` | Landing timestamp (UTC ISO 8601) |
| `duration_min` | Flight duration in minutes |
| `recorded_at` | When the record was written |
| `source` | `adsb` or `flightaware` |

---

## Requirements

- Python 3.9+
- Internet access (adsb.lol + OurAirports CSV on first run)
- FlightAware AeroAPI key (optional, for Caribbean/gap coverage)

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
| `KNOWN_TAILS` | Seed list of tail numbers to include in FlightAware batches from the start |

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

### AeroDataBox

| Setting | Default | Description |
|---|---|---|
| `AERODATABOX_API_KEY` | `""` | RapidAPI key — or set env var `AERODATABOX_API_KEY` |
| `AERODATABOX_LOOKBACK_DAYS` | `7` | Days of history to fetch per tail number |
| `AERODATABOX_BATCH_INTERVAL_HOURS` | `24` | How often to check for tails due for a refresh |

AeroDataBox fetches are suppressed per tail for 7 days after a successful fetch. The suppression window is set by `FA_SUPPRESS_DAYS` in `tails.py`.

**Getting an API key:**
1. Sign up at [rapidapi.com](https://rapidapi.com/aedbx-aedbx/api/aerodatabox)
2. Subscribe to the AeroDataBox Basic plan ($5/month, 3,000 calls)
3. Copy your RapidAPI key from the dashboard

**Setting the key** (never put it in `config.py` or commit it to git):
```bash
# Add to ~/.zshrc or ~/.bashrc for persistence
export AERODATABOX_API_KEY=your_rapidapi_key_here
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
  Aircraft types: C208, C408
  Callsign filter: ['BEZ', 'PCM', ...]
  Poll interval : 60s ± 10s
  AeroDataBox  : enabled (batch every 24h)
Loaded 32700 airports.
Loaded 45 known tail numbers.
Resumed 3 in-flight aircraft from buffer.
[2026-03-26 09:53:49 UTC] poll #1 — 7 aircraft matching filters
  Near-takeoff join: BEZ321 from TJSJ (San Juan) at 1200ft
  New tail discovered: N960HL — fetching history...
  History for N960HL: 7 fetched, 7 saved
[AeroDataBox] Starting batch for 8/45 tail(s) due for refresh...
  [ADB] Saved: BEZ2321 TJSJ->TFFJ (2026-03-24)
  [ADB] N960HL (1/8): 7 fetched, 7 saved, 0 already known
[AeroDataBox] Batch complete — 12 saved, 3 duplicates skipped.
```

Stop with `Ctrl+C` — active flights are saved to `buffer.json` and resumed on next start.

## Data files

| File | Description |
|---|---|
| `flights.db` | SQLite database of completed flights |
| `buffer.json` | In-flight tracker state, persisted for crash resilience |
| `data/airports.csv` | OurAirports database, downloaded on first run |
| `data/tails.json` | Known tail numbers with last AeroDataBox fetch timestamps |

None of these are committed to git.

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
| [adsb.lol](https://adsb.lol) | Live polling | Free | No |
| [OurAirports](https://ourairports.com/data/) | Airport database | Free (CC0) | No |
| [AeroDataBox via RapidAPI](https://rapidapi.com/aedbx-aedbx/api/aerodatabox) | Historical enrichment | $5/month (3,000 calls) | Yes (RapidAPI key) |

## Limitations

- Flights already airborne when the poller starts are discarded (no mid-join recovery)
- ADS-B coverage is incomplete at low altitudes in rural areas and the Caribbean — FlightAware enrichment mitigates this
- adsb.lol may require an API key in future (see their documentation)
- FlightAware free tier provides ~$5/month credit; at ~$0.002/call this covers roughly 2,500 tail lookups/month

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
