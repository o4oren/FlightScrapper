import sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    callsign        TEXT NOT NULL,
    tail            TEXT,
    aircraft_type   TEXT NOT NULL,
    icao_hex        TEXT NOT NULL,
    origin_icao     TEXT NOT NULL,
    origin_name     TEXT,
    origin_city     TEXT,
    origin_region   TEXT,
    origin_country  TEXT,
    origin_lat      REAL NOT NULL,
    origin_lon      REAL NOT NULL,
    dest_icao       TEXT NOT NULL,
    dest_name       TEXT,
    dest_city       TEXT,
    dest_region     TEXT,
    dest_country    TEXT,
    dest_lat        REAL NOT NULL,
    dest_lon        REAL NOT NULL,
    departure_time  TEXT NOT NULL,
    arrival_time    TEXT NOT NULL,
    duration_min    REAL NOT NULL,
    max_alt_ft      INTEGER,
    flightaware_url TEXT,
    airline_name    TEXT,
    recorded_at     TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'adsb'
);
"""


MIGRATIONS = [
    "ALTER TABLE flights ADD COLUMN tail TEXT",
    "ALTER TABLE flights ADD COLUMN source TEXT NOT NULL DEFAULT 'adsb'",
    "ALTER TABLE flights ADD COLUMN max_alt_ft INTEGER",
    "ALTER TABLE flights ADD COLUMN flightaware_url TEXT",
    "ALTER TABLE flights ADD COLUMN airline_name TEXT",
    "ALTER TABLE flights ADD COLUMN origin_name TEXT",
    "ALTER TABLE flights ADD COLUMN origin_city TEXT",
    "ALTER TABLE flights ADD COLUMN origin_region TEXT",
    "ALTER TABLE flights ADD COLUMN origin_country TEXT",
    "ALTER TABLE flights ADD COLUMN dest_name TEXT",
    "ALTER TABLE flights ADD COLUMN dest_city TEXT",
    "ALTER TABLE flights ADD COLUMN dest_region TEXT",
    "ALTER TABLE flights ADD COLUMN dest_country TEXT",
]


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        # Apply migrations idempotently — SQLite raises on duplicate columns, so we ignore those errors
        for sql in MIGRATIONS:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()


def _departure_date(flight):
    """Extract YYYY-MM-DD from departure_time for dedup key."""
    return (flight.get("departure_time") or "")[:10]


def _find_existing(conn, flight):
    """
    Return (id, exact_match) for a matching flight record, or (None, False).
    Tries exact match first (callsign + aircraft_type + origin + dest + date),
    then falls back to loose match (callsign + aircraft_type + date) to catch
    records where O/D was inferred differently by ADS-B vs history source.
    """
    callsign = flight.get("callsign", "")
    aircraft_type = flight.get("aircraft_type", "")
    origin = flight.get("origin_icao", "")
    dest = flight.get("dest_icao", "")
    date = _departure_date(flight)
    if not callsign or not date:
        return None, False

    # Exact match
    if origin and dest:
        row = conn.execute(
            """SELECT id FROM flights
               WHERE callsign = ? AND aircraft_type = ? AND origin_icao = ? AND dest_icao = ?
               AND departure_time LIKE ? LIMIT 1""",
            (callsign, aircraft_type, origin, dest, f"{date}%"),
        ).fetchone()
        if row:
            return row[0], True

    # Loose match — same flight number and day, different O/D (ADS-B snap vs history)
    row = conn.execute(
        """SELECT id FROM flights
           WHERE callsign = ? AND aircraft_type = ? AND departure_time LIKE ? LIMIT 1""",
        (callsign, aircraft_type, f"{date}%"),
    ).fetchone()
    return (row[0], False) if row else (None, False)


def _merge_flight(conn, existing_id, flight, exact_match):
    """
    Merge incoming flight data into an existing record.
    - Always: fill NULL fields with non-null values from incoming flight
    - If not exact_match (O/D or times differ): overwrite O/D and times
      with values from history source (assumed more authoritative)
    """
    # Fields filled only if currently NULL
    fill_if_null = [
        ("tail", flight.get("tail") or None),
        ("icao_hex", flight.get("icao_hex") or None),
        ("max_alt_ft", flight.get("max_alt_ft")),
        ("flightaware_url", flight.get("flightaware_url") or None),
        ("airline_name", flight.get("airline_name") or None),
        ("origin_name", flight.get("origin_name") or None),
        ("origin_city", flight.get("origin_city") or None),
        ("origin_region", flight.get("origin_region") or None),
        ("origin_country", flight.get("origin_country") or None),
        ("dest_name", flight.get("dest_name") or None),
        ("dest_city", flight.get("dest_city") or None),
        ("dest_region", flight.get("dest_region") or None),
        ("dest_country", flight.get("dest_country") or None),
    ]
    null_updates = [(col, val) for col, val in fill_if_null if val is not None]
    if null_updates:
        set_clause = ", ".join(f"{col} = COALESCE({col}, ?)" for col, _ in null_updates)
        conn.execute(
            f"UPDATE flights SET {set_clause} WHERE id = ?",
            [val for _, val in null_updates] + [existing_id],
        )

    # If O/D or times differ, overwrite with history source values
    if not exact_match and flight.get("source") in ("aerodatabox", "flightaware"):
        overwrite = {}
        if flight.get("origin_icao"):
            overwrite["origin_icao"] = flight["origin_icao"]
            overwrite["origin_lat"] = flight.get("origin_lat")
            overwrite["origin_lon"] = flight.get("origin_lon")
        if flight.get("dest_icao"):
            overwrite["dest_icao"] = flight["dest_icao"]
            overwrite["dest_lat"] = flight.get("dest_lat")
            overwrite["dest_lon"] = flight.get("dest_lon")
        if flight.get("departure_time"):
            overwrite["departure_time"] = flight["departure_time"]
        if flight.get("arrival_time"):
            overwrite["arrival_time"] = flight["arrival_time"]
        if flight.get("duration_min"):
            overwrite["duration_min"] = flight["duration_min"]
        if overwrite:
            set_clause = ", ".join(f"{col} = ?" for col in overwrite)
            conn.execute(
                f"UPDATE flights SET {set_clause} WHERE id = ?",
                list(overwrite.values()) + [existing_id],
            )


def _insert_flight(conn, flight):
    conn.execute(
        """INSERT INTO flights
           (callsign, tail, aircraft_type, icao_hex,
            origin_icao, origin_name, origin_city, origin_region, origin_country,
            origin_lat, origin_lon,
            dest_icao, dest_name, dest_city, dest_region, dest_country,
            dest_lat, dest_lon,
            departure_time, arrival_time, duration_min, max_alt_ft, flightaware_url, airline_name, recorded_at, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            flight["callsign"],
            flight.get("tail", ""),
            flight["aircraft_type"],
            flight.get("icao_hex", ""),
            flight["origin_icao"],
            flight.get("origin_name"),
            flight.get("origin_city"),
            flight.get("origin_region"),
            flight.get("origin_country"),
            flight.get("origin_lat"),
            flight.get("origin_lon"),
            flight["dest_icao"],
            flight.get("dest_name"),
            flight.get("dest_city"),
            flight.get("dest_region"),
            flight.get("dest_country"),
            flight.get("dest_lat"),
            flight.get("dest_lon"),
            flight["departure_time"],
            flight["arrival_time"],
            flight["duration_min"],
            flight.get("max_alt_ft"),
            flight.get("flightaware_url"),
            flight.get("airline_name"),
            flight["recorded_at"],
            flight.get("source", "adsb"),
        ),
    )


def _is_valid_icao(code):
    """Return True if code looks like a real ICAO airport code (4 letters, no digits in first 3 chars)."""
    if not code or len(code) < 3:
        return False
    return all(c.isalpha() for c in code[:3])


def save_flight(flight):
    """Insert flight, or merge into existing record if duplicate."""
    if not _is_valid_icao(flight.get("origin_icao", "")) or \
       not _is_valid_icao(flight.get("dest_icao", "")):
        return  # silently discard private/non-standard airport codes
    with sqlite3.connect(DB_PATH) as conn:
        existing_id, exact_match = _find_existing(conn, flight)
        if existing_id:
            _merge_flight(conn, existing_id, flight, exact_match)
        else:
            _insert_flight(conn, flight)
        conn.commit()


def save_flight_if_new(flight):
    """Insert flight if new, or merge into existing record. Returns True if inserted, False if merged/discarded."""
    if not _is_valid_icao(flight.get("origin_icao", "")) or \
       not _is_valid_icao(flight.get("dest_icao", "")):
        return False  # silently discard private/non-standard airport codes
    with sqlite3.connect(DB_PATH) as conn:
        existing_id, exact_match = _find_existing(conn, flight)
        if existing_id:
            _merge_flight(conn, existing_id, flight, exact_match)
            conn.commit()
            return False
        _insert_flight(conn, flight)
        conn.commit()
    return True
