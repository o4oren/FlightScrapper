"""
In-memory flight tracker. Detects takeoff and landing events, resolves
origin/destination airports, and emits complete flight records.
"""

import json
import os
from datetime import datetime, timezone

from airports import snap_to_airport
from config import (
    AIRCRAFT_TYPE,
    BUFFER_PATH,
    LANDING_ALTITUDE_FT,
    LANDING_TIMEOUT_SECONDS,
    TAKEOFF_ALTITUDE_FT,
)

# Active flights buffer: { hex: flight_state }
# flight_state keys:
#   callsign, first_seen, last_seen, last_lat, last_lon, last_alt,
#   airborne (bool), origin_icao, origin_lat, origin_lon, departure_time
_active = {}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _now_ts():
    return datetime.now(timezone.utc).timestamp()


def load_buffer():
    if os.path.exists(BUFFER_PATH):
        with open(BUFFER_PATH) as f:
            _active.update(json.load(f))
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
        lat = ac.get("lat")
        lon = ac.get("lon")
        alt = _altitude(ac)

        if lat is None or lon is None:
            continue

        seen_hexes.add(hex_id)

        if hex_id not in _active:
            # New aircraft — only track if it's on the ground or very low (not mid-join)
            if alt > TAKEOFF_ALTITUDE_FT:
                continue  # mid-join: discard
            _active[hex_id] = {
                "callsign": callsign,
                "first_seen": now_ts,
                "last_seen": now_ts,
                "last_lat": lat,
                "last_lon": lon,
                "last_alt": alt,
                "airborne": False,
                "origin_icao": None,
                "origin_lat": None,
                "origin_lon": None,
                "departure_time": None,
            }
            continue

        state = _active[hex_id]
        prev_alt = state["last_alt"]

        # Detect takeoff
        if not state["airborne"] and prev_alt <= TAKEOFF_ALTITUDE_FT and alt > TAKEOFF_ALTITUDE_FT:
            origin_icao, _ = snap_to_airport(state["last_lat"], state["last_lon"])
            if origin_icao:
                state["airborne"] = True
                state["origin_icao"] = origin_icao
                state["origin_lat"] = state["last_lat"]
                state["origin_lon"] = state["last_lon"]
                state["departure_time"] = _now_iso()
                print(f"  Takeoff: {callsign or hex_id} from {origin_icao}")
            else:
                # Can't snap origin — discard by removing
                del _active[hex_id]
                seen_hexes.discard(hex_id)
                continue

        # Update state
        state["callsign"] = callsign or state["callsign"]
        state["last_seen"] = now_ts
        state["last_lat"] = lat
        state["last_lon"] = lon
        state["last_alt"] = alt

    # Check for aircraft that have disappeared
    vanished = [h for h in list(_active) if h not in seen_hexes]
    for hex_id in vanished:
        state = _active[hex_id]
        time_since_seen = now_ts - state["last_seen"]

        if time_since_seen < LANDING_TIMEOUT_SECONDS:
            continue  # Too soon — might be a radar gap

        # Timed out — attempt to close the flight
        if state["airborne"] and state["last_alt"] <= LANDING_ALTITUDE_FT:
            dest_icao, _ = snap_to_airport(state["last_lat"], state["last_lon"])
            if dest_icao and state["origin_icao"] and dest_icao != state["origin_icao"]:
                arrival_time = _now_iso()
                departure_dt = datetime.fromisoformat(state["departure_time"])
                arrival_dt = datetime.fromisoformat(arrival_time)
                duration_min = (arrival_dt - departure_dt).total_seconds() / 60

                flight = {
                    "callsign": state["callsign"],
                    "aircraft_type": AIRCRAFT_TYPE,
                    "icao_hex": hex_id,
                    "origin_icao": state["origin_icao"],
                    "dest_icao": dest_icao,
                    "origin_lat": state["origin_lat"],
                    "origin_lon": state["origin_lon"],
                    "dest_lat": state["last_lat"],
                    "dest_lon": state["last_lon"],
                    "departure_time": state["departure_time"],
                    "arrival_time": arrival_time,
                    "duration_min": round(duration_min, 1),
                    "recorded_at": _now_iso(),
                }
                completed_flights.append(flight)
                print(
                    f"  Landed:  {state['callsign'] or hex_id} "
                    f"{state['origin_icao']} -> {dest_icao} "
                    f"({round(duration_min)}min)"
                )

        del _active[hex_id]

    return completed_flights
