import json
import random
import time
import requests
from config import ADSB_API_URL, AIRCRAFT_TYPES, CALLSIGN_PREFIXES

CALLSIGN_API_URL = "https://api.adsb.lol/v2/callsign/{callsign}"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FlightScrapper/1.0 (personal research)"})


def fetch_aircraft():
    seen_hexes = set()
    all_aircraft = []

    if AIRCRAFT_TYPES:
        for aircraft_type in AIRCRAFT_TYPES:
            url = ADSB_API_URL.format(aircraft_type=aircraft_type)
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            for ac in resp.json().get("ac", []):
                hex_id = ac.get("hex", "").lower()
                if hex_id and hex_id not in seen_hexes:
                    seen_hexes.add(hex_id)
                    all_aircraft.append(ac)
        if not CALLSIGN_PREFIXES:
            return all_aircraft
        return [
            ac for ac in all_aircraft
            if any((ac.get("flight") or "").strip().startswith(p) for p in CALLSIGN_PREFIXES)
        ]
    elif CALLSIGN_PREFIXES:
        for prefix in CALLSIGN_PREFIXES:
            url = CALLSIGN_API_URL.format(callsign=prefix)
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            for ac in resp.json().get("ac", []):
                hex_id = ac.get("hex", "").lower()
                if hex_id and hex_id not in seen_hexes:
                    seen_hexes.add(hex_id)
                    all_aircraft.append(ac)
        return all_aircraft
    return []


def jittered_sleep(base_seconds, jitter_seconds):
    sleep_time = base_seconds + random.uniform(-jitter_seconds, jitter_seconds)
    time.sleep(max(1, sleep_time))
