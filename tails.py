"""
Persistent set of known tail numbers discovered via adsb.lol polling.
Seeded from KNOWN_TAILS in config; new tails added automatically at runtime.
"""

import json
import os
from config import KNOWN_TAILS, TAILS_PATH

_tails = set()


def load_tails():
    _tails.update(KNOWN_TAILS)
    if os.path.exists(TAILS_PATH):
        with open(TAILS_PATH) as f:
            _tails.update(json.load(f))
    print(f"Loaded {len(_tails)} known tail numbers.")


def save_tails():
    os.makedirs(os.path.dirname(TAILS_PATH), exist_ok=True)
    with open(TAILS_PATH, "w") as f:
        json.dump(sorted(_tails), f)


def add_tail(tail):
    """Add a tail number. Returns True if it was new."""
    if tail and tail not in _tails:
        _tails.add(tail)
        return True
    return False


def get_tails():
    return set(_tails)
