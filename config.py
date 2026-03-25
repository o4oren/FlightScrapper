# Filter configuration — edit these to track different aircraft/airlines
# Fedex feeder operatiors: "BVN", "CPT", "IRO", "CFS", "MTN", "PCM", "WIG", "MAL", "AIG"
# DHL feeder operatiors: "DHK", "DHX", "VEC", "TJN", "BOX", "JOS", "SNC", "BEZ", "SET"
AIRCRAFT_TYPE = "C208"
CALLSIGN_PREFIXES = ["BVN", "CPT", "IRO", "CFS", "MTN", "PCM", "WIG", "MAL", "AIG", "DHK", "DHX", "VEC", "TJN", "BOX", "JOS", "SNC", "BEZ", "SET"]  # Empty list = accept all callsigns

# Polling
POLL_INTERVAL_SECONDS = 60
POLL_JITTER_SECONDS = 10

# Flight detection thresholds
TAKEOFF_ALTITUDE_FT = 500       # Aircraft crosses this going up = takeoff
LANDING_ALTITUDE_FT = 3000      # Aircraft below this when it disappears = landed
LANDING_TIMEOUT_SECONDS = 300   # Seconds unseen before declaring landed

# Airport snap
SNAP_RADIUS_KM_PRIMARY = 3.0
SNAP_RADIUS_KM_FALLBACK = 10.0

# Data source
ADSB_API_URL = "https://api.adsb.lol/v2/type/{aircraft_type}"

# FlightAware AeroAPI
FLIGHTAWARE_API_KEY = ""  # Set your AeroAPI key here or via env var FLIGHTAWARE_API_KEY
FLIGHTAWARE_API_URL = "https://aeroapi.flightaware.com/aeroapi"
FLIGHTAWARE_LOOKBACK_DAYS = 14       # How many days back to fetch on each batch run
FLIGHTAWARE_BATCH_INTERVAL_HOURS = 24  # How often to run the FlightAware batch

# Known tail numbers — seed list, runtime additions saved to tails.json
# adsb.lol will add new tails automatically as they are observed
KNOWN_TAILS = []

# Paths
AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS_CSV_PATH = "data/airports.csv"
BUFFER_PATH = "buffer.json"
TAILS_PATH = "data/tails.json"
DB_PATH = "flights.db"
