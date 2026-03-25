# Filter configuration — edit these to track different aircraft/airlines
AIRCRAFT_TYPE = "C208"
CALLSIGN_PREFIXES = ["FDX", "DHL"]  # Empty list = accept all callsigns

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

# Paths
AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORTS_CSV_PATH = "data/airports.csv"
BUFFER_PATH = "buffer.json"
DB_PATH = "flights.db"
