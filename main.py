#!/usr/bin/env python3
"""
FlightScrapper — generic flight tracking utility.

Live tracking: polls adsb.lol every 60s, detects takeoff/landing events,
snaps positions to OurAirports for O/D resolution, stores completed flights.

Historical enrichment: configurable provider (FlightAware or AeroDataBox)
runs a daily batch per tail number, merging missing fields into existing
records (e.g. airport names from history, max altitude from live tracking).
"""

import os
import signal
import sys
from datetime import datetime, timezone

import airports
import database
import tails as tails_store
import tracker
from config import (
    AIRCRAFT_TYPES, CALLSIGN_PREFIXES, HISTORY_PROVIDER,
    FLIGHTAWARE_API_KEY, FLIGHTAWARE_BATCH_INTERVAL_HOURS,
    AERODATABOX_API_KEY, AERODATABOX_BATCH_INTERVAL_HOURS,
    POLL_INTERVAL_SECONDS, POLL_JITTER_SECONDS,
)
from poller import fetch_aircraft, jittered_sleep


def _load_provider():
    """Return (module, api_key, batch_interval_hours, label) for the configured history provider."""
    if HISTORY_PROVIDER == "flightaware":
        import flightaware as mod
        key = os.environ.get("FLIGHTAWARE_API_KEY") or FLIGHTAWARE_API_KEY
        key = key if key and key != "None" and key != "" else None
        return mod, key, FLIGHTAWARE_BATCH_INTERVAL_HOURS, "FlightAware"
    else:
        import aerodatabox as mod
        key = os.environ.get("AERODATABOX_API_KEY") or AERODATABOX_API_KEY
        key = key if key and key != "" else None
        return mod, key, AERODATABOX_BATCH_INTERVAL_HOURS, "AeroDataBox"


def handle_shutdown(sig, frame):
    print("\nShutting down — saving in-flight buffer...")
    tracker.save_buffer()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    provider_mod, provider_key, batch_interval, provider_label = _load_provider()
    enrichment_enabled = bool(provider_key)

    print(f"FlightScrapper starting.")
    print(f"  Aircraft types : {', '.join(AIRCRAFT_TYPES)}")
    print(f"  Callsign filter: {CALLSIGN_PREFIXES or 'all'}")
    print(f"  Poll interval  : {POLL_INTERVAL_SECONDS}s ± {POLL_JITTER_SECONDS}s")
    print(f"  History source : {provider_label} — "
          f"{'enabled (batch every ' + str(batch_interval) + 'h)' if enrichment_enabled else 'disabled (no API key)'}")

    airports.load_airports()
    database.init_db()
    tails_store.load_tails()
    tracker.load_buffer()

    last_batch_run = None
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

            # Run history batch if due
            if enrichment_enabled:
                hours_since = (
                    (now - last_batch_run).total_seconds() / 3600
                    if last_batch_run else batch_interval
                )
                if hours_since >= batch_interval:
                    if tails_store.get_tails():
                        provider_mod.run_batch()
                    last_batch_run = now

        except Exception as e:
            print(f"  Error: {e}")

        jittered_sleep(POLL_INTERVAL_SECONDS, POLL_JITTER_SECONDS)


if __name__ == "__main__":
    main()
