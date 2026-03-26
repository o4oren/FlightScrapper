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
    recorded_at     TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'adsb'
);
"""


MIGRATIONS = [
    "ALTER TABLE flights ADD COLUMN tail TEXT",
    "ALTER TABLE flights ADD COLUMN source TEXT NOT NULL DEFAULT 'adsb'",
    "ALTER TABLE flights ADD COLUMN max_alt_ft INTEGER",
    "ALTER TABLE flights ADD COLUMN flightaware_url TEXT",
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
    """Return the id of a matching flight record, or None."""
    callsign = flight.get("callsign", "")
    aircraft_type = flight.get("aircraft_type", "")
    origin = flight.get("origin_icao", "")
    dest = flight.get("dest_icao", "")
    date = _departure_date(flight)
    if not callsign or not origin or not dest or not date:
        return None
    row = conn.execute(
        """SELECT id FROM flights
           WHERE callsign = ? AND aircraft_type = ? AND origin_icao = ? AND dest_icao = ?
           AND departure_time LIKE ? LIMIT 1""",
        (callsign, aircraft_type, origin, dest, f"{date}%"),
    ).fetchone()
    return row[0] if row else None


def _merge_flight(conn, existing_id, flight):
    """Update NULL fields in an existing record with non-null values from the incoming flight."""
    # Fields that can be merged from either source
    mergeable = [
        ("tail", flight.get("tail") or None),
        ("icao_hex", flight.get("icao_hex") or None),
        ("max_alt_ft", flight.get("max_alt_ft")),
        ("flightaware_url", flight.get("flightaware_url") or None),
        ("origin_name", flight.get("origin_name") or None),
        ("origin_city", flight.get("origin_city") or None),
        ("origin_region", flight.get("origin_region") or None),
        ("origin_country", flight.get("origin_country") or None),
        ("dest_name", flight.get("dest_name") or None),
        ("dest_city", flight.get("dest_city") or None),
        ("dest_region", flight.get("dest_region") or None),
        ("dest_country", flight.get("dest_country") or None),
    ]
    updates = [(col, val) for col, val in mergeable if val is not None]
    if not updates:
        return
    set_clause = ", ".join(f"{col} = COALESCE({col}, ?)" for col, _ in updates)
    values = [val for _, val in updates]
    conn.execute(f"UPDATE flights SET {set_clause} WHERE id = ?", values + [existing_id])


def _insert_flight(conn, flight):
    conn.execute(
        """INSERT INTO flights
           (callsign, tail, aircraft_type, icao_hex,
            origin_icao, origin_name, origin_city, origin_region, origin_country,
            origin_lat, origin_lon,
            dest_icao, dest_name, dest_city, dest_region, dest_country,
            dest_lat, dest_lon,
            departure_time, arrival_time, duration_min, max_alt_ft, flightaware_url, recorded_at, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            flight["recorded_at"],
            flight.get("source", "adsb"),
        ),
    )


def save_flight(flight):
    """Insert flight, or merge into existing record if duplicate."""
    with sqlite3.connect(DB_PATH) as conn:
        existing_id = _find_existing(conn, flight)
        if existing_id:
            _merge_flight(conn, existing_id, flight)
        else:
            _insert_flight(conn, flight)
        conn.commit()


def save_flight_if_new(flight):
    """Insert flight if new, or merge into existing record. Returns True if inserted, False if merged."""
    with sqlite3.connect(DB_PATH) as conn:
        existing_id = _find_existing(conn, flight)
        if existing_id:
            _merge_flight(conn, existing_id, flight)
            conn.commit()
            return False
        _insert_flight(conn, flight)
        conn.commit()
    return True
