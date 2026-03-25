import json
import random
import time
import requests
from config import ADSB_API_URL, AIRCRAFT_TYPE, CALLSIGN_PREFIXES

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FlightScrapper/1.0 (personal research)"})


def fetch_aircraft():
    url = ADSB_API_URL.format(aircraft_type=AIRCRAFT_TYPE)
    resp = SESSION.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    aircraft = data.get("ac", [])
    if not CALLSIGN_PREFIXES:
        return aircraft
    return [
        ac for ac in aircraft
        if any((ac.get("flight") or "").strip().startswith(p) for p in CALLSIGN_PREFIXES)
    ]


def jittered_sleep(base_seconds, jitter_seconds):
    sleep_time = base_seconds + random.uniform(-jitter_seconds, jitter_seconds)
    time.sleep(max(1, sleep_time))
