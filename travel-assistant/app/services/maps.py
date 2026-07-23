import requests
from flask import current_app


def get_distance_matrix(cities: list) -> dict:
    """
    Call Google Maps Distance Matrix API for driving distances between cities.
    Returns {(city_a, city_b): {"distance_km": N, "duration_h": N}}
    Gracefully returns empty dict if no API key is configured.
    """
    api_key = current_app.config.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key or len(cities) < 2:
        return {}

    # Build origins / destinations strings
    origins = "|".join(cities[:-1])
    destinations = "|".join(cities[1:])

    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origins,
        "destinations": destinations,
        "mode": "driving",
        "units": "metric",
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        current_app.logger.warning("Distance Matrix API error: %s", exc)
        return {}

    result = {}
    rows = data.get("rows", [])
    origin_addrs = data.get("origin_addresses", [])
    dest_addrs = data.get("destination_addresses", [])

    for i, row in enumerate(rows):
        for j, element in enumerate(row.get("elements", [])):
            if element.get("status") == "OK":
                origin = origin_addrs[i] if i < len(origin_addrs) else cities[i]
                dest = dest_addrs[j] if j < len(dest_addrs) else cities[j + 1]
                dist_m = element["distance"]["value"]
                dur_s = element["duration"]["value"]
                result[(cities[i], cities[j + 1])] = {
                    "distance_km": round(dist_m / 1000, 1),
                    "duration_h": round(dur_s / 3600, 1),
                    "origin_label": origin,
                    "dest_label": dest,
                }

    return result
