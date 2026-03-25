#!/usr/bin/env python3
"""
FlightScrapper — polls adsb.lol for C208 feeder flights and stores
completed flights (with resolved origin/destination) in a SQLite database.
"""

import signal
import sys

import airports
import database
import tracker
from config import AIRCRAFT_TYPE, CALLSIGN_PREFIXES, POLL_INTERVAL_SECONDS, POLL_JITTER_SECONDS
from poller import fetch_aircraft, jittered_sleep


def handle_shutdown(sig, frame):
    print("\nShutting down — saving in-flight buffer...")
    tracker.save_buffer()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    print(f"FlightScrapper starting.")
    print(f"  Aircraft type : {AIRCRAFT_TYPE}")
    print(f"  Callsign filter: {CALLSIGN_PREFIXES or 'all'}")
    print(f"  Poll interval : {POLL_INTERVAL_SECONDS}s ± {POLL_JITTER_SECONDS}s")

    airports.load_airports()
    database.init_db()
    tracker.load_buffer()

    poll_count = 0
    while True:
        try:
            aircraft_list = fetch_aircraft()
            poll_count += 1
            print(f"[poll #{poll_count}] {len(aircraft_list)} aircraft matching filters")

            completed = tracker.process_poll(aircraft_list)
            for flight in completed:
                database.save_flight(flight)
                print(f"  Saved: {flight['callsign']} {flight['origin_icao']}->{flight['dest_icao']}")

            tracker.save_buffer()

        except Exception as e:
            print(f"  Error: {e}")

        jittered_sleep(POLL_INTERVAL_SECONDS, POLL_JITTER_SECONDS)


if __name__ == "__main__":
    main()
