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

# AeroDataBox API (via RapidAPI) — set env var AERODATABOX_API_KEY or fill in below
AERODATABOX_API_KEY = f"{os.environ.get('AERODATABOX_API_KEY', '')}"
AERODATABOX_LOOKBACK_DAYS = 7        # Free tier supports 7-day history per request
AERODATABOX_BATCH_INTERVAL_HOURS = 24  # How often to check for tails due for a refresh

# Known tail numbers — seed list, runtime additions saved to tails.json
# adsb.lol will add new tails automatically as they are observed
KNOWN_TAILS = ["N962HL", "N960HL", "N961HL", "N963HL", "N965HL", "N920HL", "N910HL", "N763FE", "N765FE", "N851FE", "N934FE", "N907FX"]

# Paths
AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS_CSV_PATH = "data/airports.csv"
BUFFER_PATH = "buffer.json"
TAILS_PATH = "data/tails.json"
DB_PATH = "flights.db"
