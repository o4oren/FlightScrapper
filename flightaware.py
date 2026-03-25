"""
FlightAware AeroAPI batch fetcher.
Queries /flights/{tail} for each known tail number and returns
completed flight records to be merged into the database.
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta

from config import (
    FLIGHTAWARE_API_KEY,
    FLIGHTAWARE_API_URL,
    FLIGHTAWARE_LOOKBACK_DAYS,
    AIRCRAFT_TYPE,
)

SESSION = requests.Session()


def _api_key():
    return os.environ.get("FLIGHTAWARE_API_KEY") or FLIGHTAWARE_API_KEY


def _headers():
    return {"x-apikey": _api_key()}


def _parse_airport(ap):
    if not ap:
        return None, None, None, None, None, None, None
    return (
        ap.get("code") or ap.get("icao") or "",
        ap.get("name", ""),
        ap.get("city", ""),
        "",   # region not returned by AeroAPI directly
        ap.get("country_code", ""),
        ap.get("latitude"),
        ap.get("longitude"),
    )


def fetch_flights_for_tail(tail):
    """
    Fetch up to FLIGHTAWARE_LOOKBACK_DAYS of completed flights for a tail number.
    Returns a list of flight dicts compatible with database.save_flight().
    """
    if not _api_key():
        raise RuntimeError("FLIGHTAWARE_API_KEY is not set.")

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=FLIGHTAWARE_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{FLIGHTAWARE_API_URL}/flights/{tail}"
    params = {"start": start, "end": end, "max_pages": 1}

    resp = SESSION.get(url, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    flights = []
    for f in data.get("flights", []):
        # Only process completed flights (actual_off and actual_on both present)
        actual_off = f.get("actual_off")
        actual_on = f.get("actual_on")
        if not actual_off or not actual_on:
            continue

        origin_icao, origin_name, origin_city, origin_region, origin_country, origin_lat, origin_lon = \
            _parse_airport(f.get("origin"))
        dest_icao, dest_name, dest_city, dest_region, dest_country, dest_lat, dest_lon = \
            _parse_airport(f.get("destination"))

        if not origin_icao or not dest_icao:
            continue

        departure_dt = datetime.fromisoformat(actual_off.replace("Z", "+00:00"))
        arrival_dt = datetime.fromisoformat(actual_on.replace("Z", "+00:00"))
        duration_min = (arrival_dt - departure_dt).total_seconds() / 60

        flights.append({
            "callsign": (f.get("ident") or "").strip(),
            "tail": tail,
            "aircraft_type": f.get("aircraft_type") or AIRCRAFT_TYPE,
            "icao_hex": "",
            "origin_icao": origin_icao,
            "origin_name": origin_name,
            "origin_city": origin_city,
            "origin_region": origin_region,
            "origin_country": origin_country,
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "dest_icao": dest_icao,
            "dest_name": dest_name,
            "dest_city": dest_city,
            "dest_region": dest_region,
            "dest_country": dest_country,
            "dest_lat": dest_lat,
            "dest_lon": dest_lon,
            "departure_time": actual_off,
            "arrival_time": actual_on,
            "duration_min": round(duration_min, 1),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source": "flightaware",
        })

    return flights


def run_batch(tails):
    """
    Fetch flights for all known tails. Returns (saved, skipped) counts.
    Respects a short delay between calls to stay within rate limits.
    """
    import database

    saved = 0
    skipped = 0
    total = len(tails)

    print(f"[FlightAware] Starting batch for {total} tail(s)...")
    for i, tail in enumerate(sorted(tails), 1):
        try:
            flights = fetch_flights_for_tail(tail)
            tail_saved = 0
            tail_skipped = 0
            for flight in flights:
                if database.save_flight_if_new(flight):
                    tail_saved += 1
                    saved += 1
                    print(f"  [FA] Saved: {flight['callsign'] or tail} "
                          f"{flight['origin_icao']}->{flight['dest_icao']} "
                          f"({flight['departure_time'][:10]})")
                else:
                    tail_skipped += 1
                    skipped += 1
            print(f"  [FA] {tail} ({i}/{total}): {len(flights)} fetched, "
                  f"{tail_saved} saved, {tail_skipped} already known")
        except Exception as e:
            print(f"  [FA] Error fetching {tail}: {e}")
        time.sleep(0.5)  # be polite to the API

    print(f"[FlightAware] Batch complete — {saved} saved, {skipped} duplicates skipped.")
    return saved, skipped
