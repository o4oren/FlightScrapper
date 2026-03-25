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
    recorded_at     TEXT NOT NULL
);
"""


MIGRATIONS = [
    "ALTER TABLE flights ADD COLUMN tail TEXT",
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


def save_flight(flight):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO flights
               (callsign, tail, aircraft_type, icao_hex,
                origin_icao, origin_name, origin_city, origin_region, origin_country,
                origin_lat, origin_lon,
                dest_icao, dest_name, dest_city, dest_region, dest_country,
                dest_lat, dest_lon,
                departure_time, arrival_time, duration_min, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                flight["callsign"],
                flight["tail"],
                flight["aircraft_type"],
                flight["icao_hex"],
                flight["origin_icao"],
                flight["origin_name"],
                flight["origin_city"],
                flight["origin_region"],
                flight["origin_country"],
                flight["origin_lat"],
                flight["origin_lon"],
                flight["dest_icao"],
                flight["dest_name"],
                flight["dest_city"],
                flight["dest_region"],
                flight["dest_country"],
                flight["dest_lat"],
                flight["dest_lon"],
                flight["departure_time"],
                flight["arrival_time"],
                flight["duration_min"],
                flight["recorded_at"],
            ),
        )
        conn.commit()
