# FlightScrapper

Polls [adsb.lol](https://adsb.lol) for live ADS-B data and builds a local SQLite database of completed flights for a specific aircraft type and/or airline callsign prefix.

Designed to run continuously on a free-tier cloud VM (Fly.io, Oracle Cloud, etc.) at zero ongoing cost.

## What it does

Every 60 seconds, FlightScrapper fetches all airborne aircraft of a configured type (default: Cessna 208 Caravan, `C208`) from the adsb.lol public API. It tracks each aircraft in memory, detects takeoff and landing events from altitude changes, and resolves the origin and destination airports by snapping the aircraft's position at those events to the nearest airport from the [OurAirports](https://ourairports.com/data/) database.

A flight record is written to the database **only** when both origin and destination airports are successfully identified. Partial flights, mid-flight detections, and unresolvable positions are silently discarded.

### Tracked fields per flight

| Field | Description |
|---|---|
| `callsign` | Flight callsign (e.g. `FDX1234`) |
| `aircraft_type` | ICAO type designator (e.g. `C208`) |
| `icao_hex` | Aircraft Mode-S transponder hex code |
| `origin_icao` | Departure airport ICAO code |
| `dest_icao` | Arrival airport ICAO code |
| `origin_lat` / `origin_lon` | Departure position coordinates |
| `dest_lat` / `dest_lon` | Arrival position coordinates |
| `departure_time` | Takeoff timestamp (UTC ISO 8601) |
| `arrival_time` | Landing timestamp (UTC ISO 8601) |
| `duration_min` | Flight duration in minutes |
| `recorded_at` | When the record was written |

## Requirements

- Python 3.9+
- Internet access (adsb.lol API + OurAirports CSV on first run)

## Installation

```bash
git clone <repo-url>
cd FlightScrapper

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Running

```bash
python main.py
```

On first run, the OurAirports airport database (~8MB CSV) is downloaded to `data/airports.csv`. This only happens once.

The poller then starts. Output looks like:

```
FlightScrapper starting.
  Aircraft type : C208
  Callsign filter: ['FDX', 'DHL']
  Poll interval : 60s ± 10s
Loaded 25431 airports.
Resumed 0 in-flight aircraft from buffer.
[poll #1] 3 aircraft matching filters
[poll #2] 3 aircraft matching filters
  Takeoff: FDX1234 from KMEM
[poll #47] 4 aircraft matching filters
  Landed:  FDX1234 KMEM->KBNA (42min)
  Saved: FDX1234 KMEM->KBNA
```

Stop with `Ctrl+C` — active flights are saved to `buffer.json` and resumed on next start.

## Configuration

All settings are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `AIRCRAFT_TYPE` | `"C208"` | ICAO aircraft type designator to track |
| `CALLSIGN_PREFIXES` | `["FDX", "DHL"]` | Only track callsigns starting with these. Empty list = all callsigns |
| `POLL_INTERVAL_SECONDS` | `60` | How often to poll adsb.lol |
| `POLL_JITTER_SECONDS` | `10` | Random ± jitter added to each poll interval |
| `TAKEOFF_ALTITUDE_FT` | `500` | Altitude threshold for takeoff detection |
| `LANDING_ALTITUDE_FT` | `3000` | Maximum altitude when disappearing to count as landing |
| `LANDING_TIMEOUT_SECONDS` | `300` | Seconds unseen before declaring an aircraft landed |
| `SNAP_RADIUS_KM_PRIMARY` | `3.0` | Primary airport snap radius in km |
| `SNAP_RADIUS_KM_FALLBACK` | `10.0` | Fallback snap radius if nothing found within primary |

## Data files

| File | Description |
|---|---|
| `flights.db` | SQLite database of completed flights |
| `buffer.json` | In-memory tracker state, persisted for crash resilience |
| `data/airports.csv` | OurAirports database, downloaded on first run |

Neither `flights.db` nor `buffer.json` are committed to git.

## Querying the data

The database is a standard SQLite file. Query it with any SQLite client, or use [Datasette](https://datasette.io/) for a browser-based interface with built-in CSV export:

```bash
pip install datasette
datasette flights.db
```

Then open `http://localhost:8001` in your browser.

Example SQL queries:

```sql
-- All flights, newest first
SELECT * FROM flights ORDER BY departure_time DESC;

-- Flights between two airports
SELECT * FROM flights WHERE origin_icao = 'KMEM' AND dest_icao = 'KBNA';

-- Most common routes
SELECT origin_icao, dest_icao, COUNT(*) as count
FROM flights
GROUP BY origin_icao, dest_icao
ORDER BY count DESC;

-- Average flight duration per route
SELECT origin_icao, dest_icao, ROUND(AVG(duration_min)) as avg_min
FROM flights
GROUP BY origin_icao, dest_icao
ORDER BY avg_min DESC;
```

## Data sources

- **Live ADS-B data:** [adsb.lol](https://adsb.lol) — free, no API key required, personal/non-commercial use
- **Airport database:** [OurAirports](https://ourairports.com/data/) — CC0 public domain

## Limitations

- Flights already in progress when the poller starts are discarded (no mid-join recovery)
- ADS-B coverage is incomplete at low altitudes in rural areas — short flights may be missed
- Origin/destination is inferred from position data, not from filed flight plans
- adsb.lol may require an API key in future (see their documentation)

## Deployment

To run on a free-tier cloud VM (Fly.io example):

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly launch
fly volumes create flightscrapper_data --size 1
fly deploy
```

Ensure the volume is mounted at `/data` and update `DB_PATH`, `BUFFER_PATH`, and `AIRPORTS_CSV_PATH` in `config.py` to use `/data/` as the base directory when deploying.
