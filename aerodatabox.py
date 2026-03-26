"""
AeroDataBox batch fetcher (via RapidAPI).
Queries /flights/reg/{tail}/{fromDate}/{toDate} for each known tail number
and returns completed flight records to be merged into the database.
Drop-in replacement for flightaware.py — same run_batch() interface.
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta

from config import (
    AERODATABOX_API_KEY,
    AERODATABOX_LOOKBACK_DAYS,
)

SESSION = requests.Session()

# Map AeroDataBox model strings to ICAO type designators
MODEL_TO_ICAO = {
    "cessna 208 caravan":  "C208",
    "cessna 408 skycourier": "C408",
    "cessna 208b grand caravan": "C208",
    "cessna 208":          "C208",
}


def _api_key():
    key = os.environ.get("AERODATABOX_API_KEY") or AERODATABOX_API_KEY
    return key if key and key != "None" else None


def _headers():
    return {
        "x-rapidapi-host": "aerodatabox.p.rapidapi.com",
        "x-rapidapi-key": _api_key(),
    }


def _parse_airport(ap):
    if not ap or not ap.get("icao"):
        return None, None, None, None, None, None
    loc = ap.get("location") or {}
    return (
        ap.get("icao", ""),
        ap.get("name", ""),
        ap.get("municipalityName", ""),
        ap.get("countryCode", ""),
        loc.get("lat"),
        loc.get("lon"),
    )


def _parse_time(time_obj):
    """Return UTC ISO string from a time object, preferring runwayTime > revisedTime > predictedTime > scheduledTime."""
    for key in ("runwayTime", "revisedTime", "predictedTime", "scheduledTime"):
        val = (time_obj or {}).get(key, {}).get("utc")
        if val:
            # Normalise "2026-03-21 01:18Z" → "2026-03-21T01:18:00+00:00"
            return val.replace(" ", "T").rstrip("Z") + "+00:00"
    return None


def _model_to_icao(model_str):
    return MODEL_TO_ICAO.get((model_str or "").lower().strip(), model_str or "")


def fetch_flights_for_tail(tail):
    """
    Fetch completed flights for a tail number within the lookback window.
    Returns a list of flight dicts compatible with database.save_flight().
    """
    if not _api_key():
        raise RuntimeError("AERODATABOX_API_KEY is not set.")

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=AERODATABOX_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    url = f"https://aerodatabox.p.rapidapi.com/flights/reg/{tail}/{from_date}/{to_date}"
    params = {"dateLocalRole": "Both"}

    resp = SESSION.get(url, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    flights = []
    for f in data:
        # Skip flights still genuinely in progress
        if f.get("status") in ("EnRoute", "Unknown"):
            continue

        dep_time = _parse_time(f.get("departure"))
        arr_time = _parse_time(f.get("arrival"))
        # Require actual departure runway time + any arrival time
        dep_has_runway = bool((f.get("departure") or {}).get("runwayTime"))
        if not dep_time or not arr_time or not dep_has_runway:
            continue

        origin_icao, origin_name, origin_city, origin_country, origin_lat, origin_lon = \
            _parse_airport(f.get("departure", {}).get("airport"))
        dest_icao, dest_name, dest_city, dest_country, dest_lat, dest_lon = \
            _parse_airport(f.get("arrival", {}).get("airport"))

        if not origin_icao or not dest_icao:
            continue

        departure_dt = datetime.fromisoformat(dep_time)
        arrival_dt = datetime.fromisoformat(arr_time)
        duration_min = (arrival_dt - departure_dt).total_seconds() / 60

        aircraft = f.get("aircraft") or {}
        airline = f.get("airline") or {}
        callsign = (f.get("callSign") or "").strip()

        flights.append({
            "callsign": callsign,
            "tail": aircraft.get("reg") or tail,
            "aircraft_type": _model_to_icao(aircraft.get("model")),
            "airline_name": (airline.get("name") or "").strip() or None,
            "icao_hex": aircraft.get("modeS", ""),
            "origin_icao": origin_icao,
            "origin_name": origin_name,
            "origin_city": origin_city,
            "origin_region": "",
            "origin_country": origin_country,
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "dest_icao": dest_icao,
            "dest_name": dest_name,
            "dest_city": dest_city,
            "dest_region": "",
            "dest_country": dest_country,
            "dest_lat": dest_lat,
            "dest_lon": dest_lon,
            "departure_time": dep_time,
            "arrival_time": arr_time,
            "duration_min": round(duration_min, 1),
            "max_alt_ft": None,
            "flightaware_url": f"https://www.flightaware.com/live/flight/{callsign}" if callsign else None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source": "aerodatabox",
        })

    return flights


def run_batch():
    """
    Fetch flights for all tails due for a refresh (never fetched or > 7 days ago).
    Returns (saved, skipped) counts.
    """
    import database
    import tails as tails_store

    due = tails_store.get_tails_due_for_fetch()
    total_known = len(tails_store.get_tails())

    if not due:
        print(f"[AeroDataBox] All {total_known} tail(s) fetched within the last 7 days — skipping batch.")
        return 0, 0

    saved = 0
    skipped = 0
    total = len(due)
    print(f"[AeroDataBox] Starting batch for {total}/{total_known} tail(s) due for refresh...")

    for i, tail in enumerate(due, 1):
        try:
            flights = fetch_flights_for_tail(tail)
            tail_saved = 0
            tail_skipped = 0
            for flight in flights:
                if database.save_flight_if_new(flight):
                    tail_saved += 1
                    saved += 1
                    print(f"  [ADB] Saved: {flight['callsign'] or tail} "
                          f"{flight['origin_icao']}->{flight['dest_icao']} "
                          f"({flight['departure_time'][:10]})")
                else:
                    tail_skipped += 1
                    skipped += 1
            print(f"  [ADB] {tail} ({i}/{total}): {len(flights)} fetched, "
                  f"{tail_saved} saved, {tail_skipped} already known")
            tails_store.record_fa_fetch(tail)
        except ValueError as e:
            # Empty response body — AeroDataBox has no data for this tail, remove it
            print(f"  [ADB] No data for {tail} (removing from tails): {e}")
            tails_store.remove_tail(tail)
        except Exception as e:
            print(f"  [ADB] Error fetching {tail}: {e}")
        time.sleep(2)

    print(f"[AeroDataBox] Batch complete — {saved} saved, {skipped} duplicates skipped.")
    return saved, skipped
