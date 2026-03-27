import os

# Filter configuration — edit these to track different aircraft/airlines
# Fedex feeder operatiors: "BVN", "CPT", "IRO", "CFS", "MTN", "PCM", "WIG", "MAL", "AIG"
# DHL feeder operatiors: "DHK", "DHX", "VEC", "TJN", "BOX", "JOS", "SNC", "BEZ", "SET"
AIRCRAFT_TYPES = ["C208", "C408"]  # List of ICAO type designators to track
CALLSIGN_PREFIXES = ["BVN", "CPT", "IRO", "CFS", "MTN", "PCM", "WIG", "MAL", "AIG", "DHK", "DHX", "VEC", "TJN", "BOX", "JOS", "SNC", "BEZ", "SET"]  # Empty list = accept all callsigns

# Polling
POLL_INTERVAL_SECONDS = 60
POLL_JITTER_SECONDS = 10

# Flight detection thresholds
TAKEOFF_ALTITUDE_FT = 500        # Aircraft crosses this going up = takeoff
LANDING_ALTITUDE_FT = 3000       # Aircraft below this when it disappears = landed
LANDING_TIMEOUT_SECONDS = 300    # Seconds unseen before declaring landed
NEAR_AIRPORT_ALT_FT = 2000       # First observation below this + snaps to airport = accept as fresh takeoff

# Airport snap
SNAP_RADIUS_KM_PRIMARY = 3.0
SNAP_RADIUS_KM_FALLBACK = 10.0

# Data source
ADSB_API_URL = "https://api.adsb.lol/v2/type/{aircraft_type}"

# Historical enrichment provider — choose one: "flightaware" or "aerodatabox"
HISTORY_PROVIDER = "flightaware"

# FlightAware AeroAPI — set env var FLIGHTAWARE_API_KEY or fill in below
# Sign up: https://www.flightaware.com/aeroapi/portal
# Free personal tier: $5/month credit (~1,000 calls). Cost: $0.005 per result set (15 records).
# Coverage: global including Hawaii and Caribbean.
FLIGHTAWARE_API_KEY = f"{os.environ.get('FLIGHTAWARE_API_KEY', '')}"
FLIGHTAWARE_API_URL = "https://aeroapi.flightaware.com/aeroapi"
FLIGHTAWARE_LOOKBACK_DAYS = 10       # Personal tier supports up to 10 days of history
FLIGHTAWARE_BATCH_INTERVAL_HOURS = 24

# AeroDataBox API (via RapidAPI) — set env var AERODATABOX_API_KEY or fill in below
# Sign up: https://rapidapi.com/aedbx-aedbx/api/aerodatabox
# Free tier: 600 units/month. Basic plan: $5/month (6,000 units, ~1,000 calls).
# Coverage: good for US/Europe, limited in Hawaii and Caribbean.
AERODATABOX_API_KEY = f"{os.environ.get('AERODATABOX_API_KEY', '')}"
AERODATABOX_LOOKBACK_DAYS = 7        # Basic tier supports 7-day history per request
AERODATABOX_BATCH_INTERVAL_HOURS = 24

# Known tail numbers — seed list, runtime additions saved to tails.json
# adsb.lol will add new tails automatically as they are observed
KNOWN_TAILS = ["N962HL", "N960HL", "N961HL", "N963HL"]

# Paths
AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS_CSV_PATH = "data/airports.csv"
BUFFER_PATH = "buffer.json"
TAILS_PATH = "data/tails.json"
DB_PATH = "flights.db"
