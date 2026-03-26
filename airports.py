import csv
import math
import os
import requests
from config import AIRPORTS_CSV_URL, AIRPORTS_CSV_PATH, SNAP_RADIUS_KM_PRIMARY, SNAP_RADIUS_KM_FALLBACK

AIRPORT_TYPES = {"small_airport", "medium_airport", "large_airport"}

_airports = []  # [{icao, lat, lon, name, city, region, country}]


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _download_airports():
    os.makedirs(os.path.dirname(AIRPORTS_CSV_PATH), exist_ok=True)
    print(f"Downloading airports database from {AIRPORTS_CSV_URL} ...")
    r = requests.get(AIRPORTS_CSV_URL, timeout=30)
    r.raise_for_status()
    with open(AIRPORTS_CSV_PATH, "w", encoding="utf-8") as f:
        f.write(r.text)
    print("Airports database downloaded.")


def load_airports():
    global _airports
    if not os.path.exists(AIRPORTS_CSV_PATH):
        _download_airports()
    with open(AIRPORTS_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["type"] not in AIRPORT_TYPES:
                continue
            icao = row.get("gps_code", "").strip()
            if not icao:
                continue
            try:
                lat = float(row["latitude_deg"])
                lon = float(row["longitude_deg"])
            except ValueError:
                continue
            # iso_region format is "US-TN" — extract the state/province part
            iso_region = row.get("iso_region", "")
            region = iso_region.split("-", 1)[1] if "-" in iso_region else iso_region
            _airports.append({
                "icao": icao,
                "lat": lat,
                "lon": lon,
                "name": row.get("name", ""),
                "city": row.get("municipality", ""),
                "region": region,
                "country": row.get("iso_country", ""),
                "type": row["type"],
            })
    print(f"Loaded {len(_airports)} airports.")


def snap_to_airport(lat, lon):
    """
    Return (airport_dict, distance_km) for best matching airport within fallback radius,
    or (None, None) if nothing found.

    Priority rules (within the search radius):
    1. A small airport within 0.5km always wins — aircraft is essentially on top of it.
    2. Otherwise prefer medium/large airports over small ones.
    3. Within the same tier, prefer the closest.
    """
    SMALL_OVERRIDE_KM = 0.5

    best_ap = None
    best_dist = float("inf")
    best_large_medium_ap = None
    best_large_medium_dist = float("inf")

    for ap in _airports:
        d = _haversine_km(lat, lon, ap["lat"], ap["lon"])
        if d > SNAP_RADIUS_KM_FALLBACK:
            continue
        if d < best_dist:
            best_dist = d
            best_ap = ap
        if ap["type"] in ("medium_airport", "large_airport") and d < best_large_medium_dist:
            best_large_medium_dist = d
            best_large_medium_ap = ap

    if not best_ap:
        return None, None

    # Rule 1: small airport within 0.5km — use it regardless
    if best_dist <= SMALL_OVERRIDE_KM:
        return best_ap, best_dist

    # Rule 2: prefer medium/large if one exists within the radius
    if best_large_medium_ap:
        return best_large_medium_ap, best_large_medium_dist

    # Rule 3: fall back to nearest small airport if within primary radius
    if best_dist <= SNAP_RADIUS_KM_PRIMARY:
        return best_ap, best_dist

    # Rule 4: fallback radius — only medium/large
    if best_large_medium_ap and best_large_medium_dist <= SNAP_RADIUS_KM_FALLBACK:
        return best_large_medium_ap, best_large_medium_dist

    return None, None
