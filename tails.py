"""
Persistent registry of known tail numbers discovered via adsb.lol polling.
Seeded from KNOWN_TAILS in config; new tails added automatically at runtime.

Stored as a dict: { tail: last_fa_fetch_iso or null }
"""

import json
import os
from datetime import datetime, timezone, timedelta
from config import KNOWN_TAILS, TAILS_PATH

FA_SUPPRESS_DAYS = 7  # Don't re-fetch a tail within this many days of last success

_registry = {}  # { tail: last_fa_fetch_iso or None }


def load_tails():
    for tail in KNOWN_TAILS:
        _registry.setdefault(tail, None)
    if os.path.exists(TAILS_PATH):
        with open(TAILS_PATH) as f:
            data = json.load(f)
        # Support old format (plain list) and new format (dict)
        if isinstance(data, list):
            for tail in data:
                _registry.setdefault(tail, None)
        else:
            for tail, last_fetch in data.items():
                _registry.setdefault(tail, last_fetch)
    print(f"Loaded {len(_registry)} known tail numbers.")


def save_tails():
    os.makedirs(os.path.dirname(TAILS_PATH), exist_ok=True)
    with open(TAILS_PATH, "w") as f:
        json.dump(_registry, f, indent=2)


def add_tail(tail):
    """Add a tail number. Returns True if it was new."""
    if tail and tail not in _registry:
        _registry[tail] = None
        return True
    return False


def record_fa_fetch(tail):
    """Mark a tail as successfully fetched from FlightAware right now."""
    if tail in _registry:
        _registry[tail] = datetime.now(timezone.utc).isoformat()
        save_tails()


def get_tails():
    return set(_registry.keys())


def get_tails_due_for_fetch():
    """Return tails that have never been fetched or were last fetched > FA_SUPPRESS_DAYS ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=FA_SUPPRESS_DAYS)
    due = []
    for tail, last_fetch in _registry.items():
        if last_fetch is None:
            due.append(tail)
        else:
            last_dt = datetime.fromisoformat(last_fetch)
            if last_dt < cutoff:
                due.append(tail)
    return sorted(due)
