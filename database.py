import sqlite3
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    callsign        TEXT NOT NULL,
    aircraft_type   TEXT NOT NULL,
    icao_hex        TEXT NOT NULL,
    origin_icao     TEXT NOT NULL,
    dest_icao       TEXT NOT NULL,
    origin_lat      REAL NOT NULL,
    origin_lon      REAL NOT NULL,
    dest_lat        REAL NOT NULL,
    dest_lon        REAL NOT NULL,
    departure_time  TEXT NOT NULL,
    arrival_time    TEXT NOT NULL,
    duration_min    REAL NOT NULL,
    recorded_at     TEXT NOT NULL
);
"""


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)


def save_flight(flight):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO flights
               (callsign, aircraft_type, icao_hex, origin_icao, dest_icao,
                origin_lat, origin_lon, dest_lat, dest_lon,
                departure_time, arrival_time, duration_min, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                flight["callsign"],
                flight["aircraft_type"],
                flight["icao_hex"],
                flight["origin_icao"],
                flight["dest_icao"],
                flight["origin_lat"],
                flight["origin_lon"],
                flight["dest_lat"],
                flight["dest_lon"],
                flight["departure_time"],
                flight["arrival_time"],
                flight["duration_min"],
                flight["recorded_at"],
            ),
        )
        conn.commit()
