#!/usr/bin/env python3
"""
FlightScrapper — polls adsb.lol for C208 feeder flights and stores
completed flights (with resolved origin/destination) in a SQLite database.
"""

import os
import signal
import sys
from datetime import datetime, timezone

import airports
import database
import flightaware
import tails as tails_store
import tracker
from config import (
    AIRCRAFT_TYPES, CALLSIGN_PREFIXES, FLIGHTAWARE_API_KEY,
    FLIGHTAWARE_BATCH_INTERVAL_HOURS, POLL_INTERVAL_SECONDS, POLL_JITTER_SECONDS,
)
from poller import fetch_aircraft, jittered_sleep


def handle_shutdown(sig, frame):
    print("\nShutting down — saving in-flight buffer...")
    tracker.save_buffer()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    print(f"FlightScrapper starting.")
    print(f"  Aircraft types: {', '.join(AIRCRAFT_TYPES)}")
    print(f"  Callsign filter: {CALLSIGN_PREFIXES or 'all'}")
    print(f"  Poll interval : {POLL_INTERVAL_SECONDS}s ± {POLL_JITTER_SECONDS}s")

    _fa_key = os.environ.get("FLIGHTAWARE_API_KEY") or FLIGHTAWARE_API_KEY
    fa_enabled = bool(_fa_key and _fa_key != "None")
    print(f"  FlightAware  : {'enabled (batch every ' + str(FLIGHTAWARE_BATCH_INTERVAL_HOURS) + 'h)' if fa_enabled else 'disabled (no API key)'}")

    airports.load_airports()
    database.init_db()
    tails_store.load_tails()
    tracker.load_buffer()

    last_fa_run = None
    poll_count = 0

    while True:
        try:
            aircraft_list = fetch_aircraft()
            poll_count += 1
            now = datetime.now(timezone.utc)
            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] poll #{poll_count} — {len(aircraft_list)} aircraft matching filters")

            completed = tracker.process_poll(aircraft_list)
            for flight in completed:
                database.save_flight(flight)
                print(f"  Saved: {flight['callsign']} {flight['origin_icao']}->{flight['dest_icao']}")

            tracker.save_buffer()

            # Run FlightAware batch if due
            if fa_enabled:
                hours_since = (
                    (now - last_fa_run).total_seconds() / 3600
                    if last_fa_run else FLIGHTAWARE_BATCH_INTERVAL_HOURS
                )
                if hours_since >= FLIGHTAWARE_BATCH_INTERVAL_HOURS:
                    known = tails_store.get_tails()
                    if known:
                        flightaware.run_batch(known)
                    last_fa_run = now

        except Exception as e:
            print(f"  Error: {e}")

        jittered_sleep(POLL_INTERVAL_SECONDS, POLL_JITTER_SECONDS)


if __name__ == "__main__":
    main()
