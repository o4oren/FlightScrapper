"""
Airline name lookup using OpenFlights airlines.dat (CC0/ODbL).
Downloaded once to data/airlines.dat and loaded into memory.

Fields: id, name, alias, iata, icao, callsign, country, active
"""

import csv
import os
import requests

AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
AIRLINES_PATH = "data/airlines.dat"

# { icao_code: (name, country) }
_airlines = {}


def _download():
    os.makedirs(os.path.dirname(AIRLINES_PATH), exist_ok=True)
    print(f"Downloading airlines database from {AIRLINES_URL} ...")
    r = requests.get(AIRLINES_URL, timeout=30)
    r.raise_for_status()
    with open(AIRLINES_PATH, "w", encoding="utf-8") as f:
        f.write(r.text)
    print("Airlines database downloaded.")


def load_airlines():
    if not os.path.exists(AIRLINES_PATH):
        _download()
    count = 0
    with open(AIRLINES_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 8:
                continue
            # Fields: id, name, alias, iata, icao, callsign, country, active
            icao = row[4].strip()
            name = row[1].strip()
            country = row[6].strip()
            if icao and icao != r'\N' and name and name != r'\N':
                _airlines[icao] = (name, country)
                count += 1
    print(f"Loaded {count} airlines.")


def lookup(icao_code):
    """Return (name, country) for an ICAO airline code, or (None, None) if not found."""
    return _airlines.get((icao_code or "").upper(), (None, None))
