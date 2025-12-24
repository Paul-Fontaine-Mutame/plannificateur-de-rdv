import json
import threading
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

_SESSION = requests.Session()
_ADAPTER = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=2)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)

API_KEY = "pk.eyJ1IjoicGF1bG11dGFtZSIsImEiOiJjbWluYTJhOHcwNGRrM2VzYThkMXo1aTdhIn0.A1NwGkKqnI8GuuEos_bkVg"

# Cache file path
_CACHE_PATH = Path(".mapbox_cache.json")
_CACHE_LOCK = threading.Lock()

# TTLs (seconds)
SUGGESTIONS_TTL = 10 * 24 * 3600
GEOCODE_TTL = 30 * 24 * 3600
DRIVING_TTL = 3 * 24 * 3600


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        with _CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    tmp = _CACHE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cache, f)
    try:
        tmp.replace(_CACHE_PATH)
    except Exception:
        tmp.rename(_CACHE_PATH)


def _get_cache(key: str):
    with _CACHE_LOCK:
        cache = _load_cache()
        entry = cache.get(key)
        if not entry:
            return None
        return entry.get("value")


def clean_expired_entries(cache):
    now = time.time()

    # TTL rules by key prefix
    TTL_BY_PREFIX = {
        "suggestions": SUGGESTIONS_TTL,
        "geocode": GEOCODE_TTL,
        "driving": DRIVING_TTL,
    }

    for key, entry in list(cache.items()):
        prefix = key.split(":", 1)[0]
        ttl = TTL_BY_PREFIX.get(prefix)

        ts = entry.get("ts", 0)
        if now - ts > ttl:
            cache.pop(key, None)


def _set_cache(key: str, value) -> None:
    with _CACHE_LOCK:
        cache = _load_cache()
        clean_expired_entries(cache)
        cache[key] = {"ts": int(time.time()), "value": value}
        _save_cache(cache)


def suggestions(adress, limit=3):
    key = f"suggestions:{adress.strip().lower()}:{limit}"
    cached = _get_cache(key)
    if cached is not None:
        return cached

    url = "https://api.mapbox.com/search/searchbox/v1/suggest"
    params = {
        "q": f"{adress}",
        "language": "fr",
        "limit": limit,
        "proximity": "-1.0842812946932405, 49.11306395733223",
        "country": "FR",
        "access_token": API_KEY,
        "session_token": "[GENERATED-UUID]",
    }
    response = _SESSION.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    results = [
        {
            "name": s.get("name"),
            "full_address": s.get("full_address") or s.get("place_formatted"),
            "mapbox_id": s.get("mapbox_id"),
        }
        for s in data.get("suggestions", [])
    ]

    _set_cache(key, results)
    return results


def geocode(mapbox_id):
    """Return (lon, lat) for a given mapbox_id."""

    key = f"geocode:{mapbox_id}"
    cached = _get_cache(key)
    if cached is not None:
        return tuple(cached)

    url = f"https://api.mapbox.com/search/searchbox/v1/retrieve/{mapbox_id}"
    params = {
        "session_token": "[GENERATED-UUID]",
        "access_token": API_KEY,
    }
    response = _SESSION.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    coords = data["features"][0]["geometry"]["coordinates"]
    _set_cache(key, coords)
    return coords[0], coords[1]


def driving_time_between(lieu1, lieu2, heure_depart=None, heure_arrivee=None):
    # Normalize times to minute granularity for caching (if provided)
    depart_str = (
        heure_depart.strftime("%Y-%m-%dT%H:%M") if heure_depart is not None else ""
    )
    arrive_str = (
        heure_arrivee.strftime("%Y-%m-%dT%H:%M") if heure_arrivee is not None else ""
    )

    key = (
        f"driving:{round(lieu1.lon, 6)},{round(lieu1.lat, 6)}:"
        f"{round(lieu2.lon, 6)},{round(lieu2.lat, 6)}:depart={depart_str}:arrive={arrive_str}"
    )
    cached = _get_cache(key)
    if cached is not None:
        return cached[0], cached[1]

    url = f"https://api.mapbox.com/directions/v5/mapbox/driving/{lieu1.lon},{lieu1.lat};{lieu2.lon},{lieu2.lat}"
    if heure_depart is not None:
        params = {
            "depart_at": heure_depart.strftime("%Y-%m-%dT%H:%M"),
            "overview": "false",
            "access_token": API_KEY,
        }
    elif heure_arrivee is not None:
        params = {
            "arrive_by": heure_arrivee.strftime("%Y-%m-%dT%H:%M"),
            "overview": "false",
            "access_token": API_KEY,
        }
    else:
        params = {
            "access_token": API_KEY,
        }

    try:
        response = _SESSION.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        summary = data["routes"][0]
        duration = summary["duration"]  # in seconds
        distance = summary["distance"]  # in meters

        _set_cache(key, [duration, distance])
        return duration, distance
    except Exception as e:
        print(f"Error while fetching driving time between {lieu1} and {lieu2} :\n {e}")
        return 0, 0


def map_with_places(lieu_list):
    lonlats = ";".join(
        f"{round(lieu.lon, 6)},{round(lieu.lat, 6)}" for lieu in lieu_list
    )
    url = f"https://api.mapbox.com/styles/v1/mapbox/streets-v11/static/pin-s+ff0000({lonlats})/{lonlats}/auto/500x300@2x?access_token={API_KEY}"
    return url


if __name__ == "__main__":
    # count the number of entries for each type
    counts = {
        "suggestions": 0,
        "geocode": 0,
        "driving": 0,
    }
    cache = _load_cache()
    for key, entry in list(cache.items()):
        prefix = key.split(":", 1)[0]
        counts[prefix] += 1

    print(counts)
