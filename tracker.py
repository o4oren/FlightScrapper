"""
In-memory flight tracker. Detects takeoff and landing events, resolves
origin/destination airports, and emits complete flight records.
"""

import json
import os
from datetime import datetime, timezone

from airports import snap_to_airport
import tails as tails_store
from config import (
    BUFFER_PATH,
    LANDING_ALTITUDE_FT,
    LANDING_TIMEOUT_SECONDS,
    NEAR_AIRPORT_ALT_FT,
    TAKEOFF_ALTITUDE_FT,
)

# Active flights buffer: { hex: flight_state }
# flight_state keys:
#   callsign, first_seen, last_seen, last_lat, last_lon, last_alt,
#   airborne (bool), origin_icao, origin_name, origin_city, origin_region,
#   origin_country, origin_lat, origin_lon, departure_time
_active = {}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _now_ts():
    return datetime.now(timezone.utc).timestamp()


def load_buffer():
    if os.path.exists(BUFFER_PATH):
        with open(BUFFER_PATH) as f:
            data = json.load(f)
        # Backfill any fields that didn't exist when the buffer was saved
        for state in data.values():
            state.setdefault("tail", "")
            state.setdefault("aircraft_type", "")
            state.setdefault("max_alt", 0)
            state.setdefault("origin_name", None)
            state.setdefault("origin_city", None)
            state.setdefault("origin_region", None)
            state.setdefault("origin_country", None)
        _active.update(data)
        print(f"Resumed {len(_active)} in-flight aircraft from buffer.")


def save_buffer():
    with open(BUFFER_PATH, "w") as f:
        json.dump(_active, f)


def _altitude(ac):
    alt = ac.get("alt_baro")
    if alt == "ground" or alt is None:
        return 0
    return int(alt)


def process_poll(aircraft_list):
    """
    Process one poll result. Returns a list of completed flight dicts
    (ready to be saved to the database).
    """
    now_ts = _now_ts()
    seen_hexes = set()
    completed_flights = []

    for ac in aircraft_list:
        hex_id = ac.get("hex", "").lower()
        if not hex_id:
            continue

        callsign = (ac.get("flight") or "").strip()
        tail = (ac.get("r") or "").strip()
        aircraft_type = (ac.get("t") or "").strip()
        lat = ac.get("lat")
        lon = ac.get("lon")
        alt = _altitude(ac)

        if lat is None or lon is None:
            continue

        seen_hexes.add(hex_id)

        # Register new tail numbers as they are observed and fetch history immediately
        if tail and tails_store.add_tail(tail):
            print(f"  New tail discovered: {tail} — fetching history...")
            tails_store.save_tails()
            try:
                import aerodatabox
                import database
                import time
                flights = aerodatabox.fetch_flights_for_tail(tail)
                time.sleep(2)
                new_count = sum(1 for f in flights if database.save_flight_if_new(f))
                print(f"  History for {tail}: {len(flights)} fetched, {new_count} saved")
                tails_store.record_fa_fetch(tail)
            except ValueError:
                # Empty response — AeroDataBox has no data for this tail
                # Keep for live adsb.lol tracking, suppress for 7 days
                print(f"  No AeroDataBox coverage for {tail} — suppressing for 7 days")
                tails_store.record_fa_fetch(tail)
            except Exception as e:
                print(f"  History fetch failed for {tail}: {e}")

        if hex_id not in _active:
            # New aircraft — discard if clearly mid-flight
            if alt > NEAR_AIRPORT_ALT_FT:
                continue  # mid-join: too high to recover origin
            # If below NEAR_AIRPORT_ALT_FT and snaps to an airport, treat as fresh takeoff
            if alt > TAKEOFF_ALTITUDE_FT:
                origin_ap, _ = snap_to_airport(lat, lon)
                if not origin_ap:
                    continue  # airborne but not near any airport — discard
                # Accept as a near-takeoff join: start already airborne with origin resolved
                _active[hex_id] = {
                    "callsign": callsign,
                    "tail": tail,
                    "aircraft_type": aircraft_type,
                    "first_seen": now_ts,
                    "last_seen": now_ts,
                    "last_lat": lat,
                    "last_lon": lon,
                    "last_alt": alt,
                    "max_alt": alt,
                    "airborne": True,
                    "origin_icao": origin_ap["icao"],
                    "origin_name": origin_ap["name"],
                    "origin_city": origin_ap["city"],
                    "origin_region": origin_ap["region"],
                    "origin_country": origin_ap["country"],
                    "origin_lat": lat,
                    "origin_lon": lon,
                    "departure_time": _now_iso(),
                }
                print(f"  Near-takeoff join: {callsign or hex_id} from {origin_ap['icao']} ({origin_ap['city']}) at {alt}ft")
                continue
            # On the ground or below takeoff threshold — track normally
            _active[hex_id] = {
                "callsign": callsign,
                "tail": tail,
                "aircraft_type": aircraft_type,
                "first_seen": now_ts,
                "last_seen": now_ts,
                "last_lat": lat,
                "last_lon": lon,
                "last_alt": alt,
                "max_alt": alt,
                "airborne": False,
                "origin_icao": None,
                "origin_name": None,
                "origin_city": None,
                "origin_region": None,
                "origin_country": None,
                "origin_lat": None,
                "origin_lon": None,
                "departure_time": None,
            }
            continue

        state = _active[hex_id]
        prev_alt = state["last_alt"]

        # Detect takeoff
        if not state["airborne"] and prev_alt <= TAKEOFF_ALTITUDE_FT and alt > TAKEOFF_ALTITUDE_FT:
            origin_ap, _ = snap_to_airport(state["last_lat"], state["last_lon"])
            if origin_ap:
                state["airborne"] = True
                state["origin_icao"] = origin_ap["icao"]
                state["origin_name"] = origin_ap["name"]
                state["origin_city"] = origin_ap["city"]
                state["origin_region"] = origin_ap["region"]
                state["origin_country"] = origin_ap["country"]
                state["origin_lat"] = state["last_lat"]
                state["origin_lon"] = state["last_lon"]
                state["departure_time"] = _now_iso()
                print(f"  Takeoff: {callsign or hex_id} from {origin_ap['icao']} ({origin_ap['city']})")
            else:
                # Can't snap origin — discard by removing
                del _active[hex_id]
                seen_hexes.discard(hex_id)
                continue

        # Update state
        state["callsign"] = callsign or state["callsign"]
        state["tail"] = tail or state.get("tail", "")
        state["aircraft_type"] = aircraft_type or state.get("aircraft_type", "")
        state["last_seen"] = now_ts
        state["last_lat"] = lat
        state["last_lon"] = lon
        state["last_alt"] = alt
        state["max_alt"] = max(state.get("max_alt", 0), alt)

    # Check for aircraft that have disappeared
    vanished = [h for h in list(_active) if h not in seen_hexes]
    for hex_id in vanished:
        state = _active[hex_id]
        time_since_seen = now_ts - state["last_seen"]

        if time_since_seen < LANDING_TIMEOUT_SECONDS:
            continue  # Too soon — might be a radar gap

        # Timed out — attempt to close the flight
        if state["airborne"] and state["last_alt"] <= LANDING_ALTITUDE_FT:
            dest_ap, _ = snap_to_airport(state["last_lat"], state["last_lon"])
            if dest_ap and state["origin_icao"] and dest_ap["icao"] != state["origin_icao"]:
                arrival_time = _now_iso()
                departure_dt = datetime.fromisoformat(state["departure_time"])
                arrival_dt = datetime.fromisoformat(arrival_time)
                duration_min = (arrival_dt - departure_dt).total_seconds() / 60

                flight = {
                    "callsign": state["callsign"],
                    "tail": state.get("tail", ""),
                    "aircraft_type": state.get("aircraft_type", ""),
                    "icao_hex": hex_id,
                    "origin_icao": state["origin_icao"],
                    "origin_name": state["origin_name"],
                    "origin_city": state["origin_city"],
                    "origin_region": state["origin_region"],
                    "origin_country": state["origin_country"],
                    "origin_lat": state["origin_lat"],
                    "origin_lon": state["origin_lon"],
                    "dest_icao": dest_ap["icao"],
                    "dest_name": dest_ap["name"],
                    "dest_city": dest_ap["city"],
                    "dest_region": dest_ap["region"],
                    "dest_country": dest_ap["country"],
                    "dest_lat": state["last_lat"],
                    "dest_lon": state["last_lon"],
                    "departure_time": state["departure_time"],
                    "arrival_time": arrival_time,
                    "duration_min": round(duration_min, 1),
                    "max_alt_ft": round(state.get("max_alt", 0), -3),
                    "flightaware_url": f"https://www.flightaware.com/live/flight/{state['callsign']}" if state["callsign"] else None,
                    "recorded_at": _now_iso(),
                    "source": "adsb",
                }
                completed_flights.append(flight)
                print(
                    f"  Landed:  {state['callsign'] or hex_id} "
                    f"{state['origin_icao']} ({state['origin_city']}) -> "
                    f"{dest_ap['icao']} ({dest_ap['city']}) "
                    f"({round(duration_min)}min)"
                )

        del _active[hex_id]

    return completed_flights
