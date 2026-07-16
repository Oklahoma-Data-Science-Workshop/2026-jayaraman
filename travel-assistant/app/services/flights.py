import requests
from flask import current_app

# Common IATA code lookup for frequently used cities
IATA_MAP = {
    "oklahoma city": "OKC",
    "okc": "OKC",
    "boston": "BOS",
    "madrid": "MAD",
    "new york": "JFK",
    "nyc": "JFK",
    "los angeles": "LAX",
    "la": "LAX",
    "chicago": "ORD",
    "dallas": "DFW",
    "houston": "IAH",
    "miami": "MIA",
    "atlanta": "ATL",
    "san francisco": "SFO",
    "seattle": "SEA",
    "denver": "DEN",
    "phoenix": "PHX",
    "london": "LHR",
    "paris": "CDG",
    "frankfurt": "FRA",
    "amsterdam": "AMS",
    "rome": "FCO",
    "barcelona": "BCN",
    "lisbon": "LIS",
    "tokyo": "NRT",
    "dubai": "DXB",
    "toronto": "YYZ",
    "montreal": "YUL",
    "mexico city": "MEX",
    "cancun": "CUN",
    "washington": "DCA",
    "dc": "DCA",
    "orlando": "MCO",
    "las vegas": "LAS",
    "minneapolis": "MSP",
    "detroit": "DTW",
    "philadelphia": "PHL",
    "charlotte": "CLT",
    "salt lake city": "SLC",
    "portland": "PDX",
    "nashville": "BNA",
    "austin": "AUS",
    "san antonio": "SAT",
    "new orleans": "MSY",
    "baltimore": "BWI",
    "raleigh": "RDU",
    "indianapolis": "IND",
    "kansas city": "MCI",
    "st. louis": "STL",
    "pittsburgh": "PIT",
    "columbus": "CMH",
    "cleveland": "CLE",
    "cincinnati": "CVG",
    "memphis": "MEM",
    "richmond": "RIC",
    "norfolk": "ORF",
    "jacksonville": "JAX",
    "tampa": "TPA",
    "fort lauderdale": "FLL",
    "san jose": "SJC",
    "san diego": "SAN",
    "honolulu": "HNL",
    "anchorage": "ANC",
}

# Preferred departure/arrival time windows
TIME_WINDOWS = {
    "early_morning": (0, 480),    # before 8:00
    "morning": (480, 720),        # 8:00–12:00
    "afternoon": (720, 1080),     # 12:00–18:00
    "evening": (1080, 1440),      # after 18:00
    "no_redeye": (360, 1440),     # avoid overnight (before 6am counts as redeye)
    "before_8pm": (0, 1200),      # before 20:00
    "any": None,
}


def _parse_time_minutes(time_str: str) -> int | None:
    """Parse 'HH:MM' or 'H:MM AM/PM' into minutes since midnight."""
    if not time_str:
        return None
    time_str = time_str.strip()
    try:
        # Handle AM/PM
        if "AM" in time_str.upper() or "PM" in time_str.upper():
            import datetime
            for fmt in ("%I:%M %p", "%I:%M%p", "%I %p"):
                try:
                    t = datetime.datetime.strptime(time_str.upper(), fmt)
                    return t.hour * 60 + t.minute
                except ValueError:
                    continue
        # Handle 24-hour
        parts = time_str.replace(".", ":").split(":")
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        return hours * 60 + minutes
    except (ValueError, IndexError):
        return None


def _time_in_window(time_str: str, pref: str) -> bool:
    """Return True if time_str falls within the named preference window."""
    window = TIME_WINDOWS.get(pref or "any")
    if window is None:
        return True  # "any" always matches
    mins = _parse_time_minutes(time_str)
    if mins is None:
        return True  # can't parse → don't penalize
    return window[0] <= mins <= window[1]


def filter_by_time_pref(flights: list, depart_pref: str = "any", arrive_pref: str = "any") -> list:
    """
    Mark each flight with comfort_match based on time preferences.
    Reorders so matching flights come first; never discards options.
    """
    for f in flights:
        depart_ok = _time_in_window(f.get("departure", ""), depart_pref)
        arrive_ok = _time_in_window(f.get("arrival", ""), arrive_pref)
        f["comfort_match"] = depart_ok and arrive_ok
    # Matching flights first, then by price
    return sorted(flights, key=lambda x: (not x["comfort_match"], x.get("price_usd", 9999)))


def get_iata_code(city_name: str) -> str:
    """
    Map city name → IATA code.
    Falls back to SerpAPI airport search for unknown cities.
    Returns empty string if lookup fails.
    """
    normalized = city_name.lower().strip()
    # Direct lookup
    if normalized in IATA_MAP:
        return IATA_MAP[normalized]
    # Try prefix match
    for key, code in IATA_MAP.items():
        if normalized.startswith(key) or key.startswith(normalized):
            return code

    # SerpAPI fallback
    api_key = current_app.config.get("SERPAPI_KEY", "")
    if not api_key:
        return ""
    try:
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google_flights", "type": "1", "departure_id": city_name, "api_key": api_key},
            timeout=10,
        )
        data = resp.json()
        airports = data.get("airports", [])
        if airports:
            return airports[0].get("iata_code", "")
    except Exception as exc:
        current_app.logger.warning("IATA lookup failed for %s: %s", city_name, exc)
    return ""


def search_flights(
    origin_code: str,
    dest_code: str,
    date: str,
    adults: int = 1,
    currency: str = "USD",
) -> list:
    """
    Call SerpAPI Google Flights.
    Returns top 5 options, each as a dict with airline, times, stops, price, etc.
    Returns [] on any error or missing key.
    """
    api_key = current_app.config.get("SERPAPI_KEY", "")
    if not api_key:
        current_app.logger.warning("SERPAPI_KEY not configured — skipping flight search")
        return []

    params = {
        "engine": "google_flights",
        "departure_id": origin_code,
        "arrival_id": dest_code,
        "outbound_date": date,
        "adults": adults,
        "currency": currency,
        "api_key": api_key,
        "type": "2",  # one-way
    }

    try:
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        current_app.logger.error("SerpAPI flight search error: %s", exc)
        return []

    raw_flights = data.get("best_flights", []) + data.get("other_flights", [])
    results = []

    for item in raw_flights[:10]:
        flights_list = item.get("flights", [])
        if not flights_list:
            continue

        first_leg = flights_list[0]
        last_leg = flights_list[-1]

        # Layover info
        layovers = item.get("layovers", [])
        layover_str = ""
        if layovers:
            layover_str = ", ".join(
                f"{lay.get('name', '?')} {lay.get('duration', 0)} min"
                for lay in layovers
            )

        # Airline name: may be list or string
        airline = first_leg.get("airline", "")
        if isinstance(airline, list):
            airline = airline[0] if airline else ""

        entry = {
            "airline": airline,
            "flight_number": first_leg.get("flight_number", ""),
            "departure": first_leg.get("departure_airport", {}).get("time", ""),
            "arrival": last_leg.get("arrival_airport", {}).get("time", ""),
            "duration_min": item.get("total_duration", 0),
            "stops": len(flights_list) - 1,
            "layover": layover_str,
            "price_usd": item.get("price", 0),
            "booking_token": item.get("booking_token", ""),
            "comfort_match": True,
        }
        results.append(entry)

    return results[:5]


def _resolve_travelers(travelers_raw) -> int:
    """
    Normalize the travelers field from trip_data.
    Claude may emit an int (2) or a per-leg dict ({"OKC_to_BOS": 1, "BOS_to_MAD": 2}).
    Return the max traveler count as a safe default for all legs.
    """
    if isinstance(travelers_raw, int):
        return max(1, travelers_raw)
    if isinstance(travelers_raw, dict):
        vals = [v for v in travelers_raw.values() if isinstance(v, int) and v > 0]
        return max(vals) if vals else 1
    try:
        return max(1, int(travelers_raw))
    except (TypeError, ValueError):
        return 1


def search_all_legs(trip_data: dict) -> dict:
    """
    Search flights for every flight leg in trip_data["legs"].
    Applies time preference filtering per leg.
    Returns {leg_key: [flight_options]}.
    """
    legs = trip_data.get("legs", [])
    travelers = _resolve_travelers(trip_data.get("travelers", 1))
    results = {}

    for leg in legs:
        if leg.get("type", "flight") != "flight":
            continue

        from_city = leg.get("from", "")
        to_city = leg.get("to", "")

        # Resolve IATA codes — prefer explicit codes in trip_data, fall back to lookup
        iata_map = trip_data.get("iata_codes", {})
        origin_code = iata_map.get(from_city) or leg.get("origin_code") or get_iata_code(from_city)
        dest_code = iata_map.get(to_city) or leg.get("dest_code") or get_iata_code(to_city)

        if not origin_code or not dest_code:
            current_app.logger.warning("Could not resolve IATA for %s→%s", from_city, to_city)
            continue

        date = leg.get("date", "")
        depart_pref = leg.get("depart_pref", "any")
        arrive_pref = leg.get("arrive_pref", "any")

        # Use per-leg traveler count if Claude provided it (dict keyed by leg description)
        leg_travelers = travelers
        if isinstance(trip_data.get("travelers"), dict):
            leg_key_lookup = f"{from_city}_to_{to_city}"
            for k, v in trip_data["travelers"].items():
                if from_city.lower() in k.lower() and to_city.lower() in k.lower():
                    if isinstance(v, int) and v > 0:
                        leg_travelers = v
                    break

        leg_key = f"{from_city}→{to_city}_{date}"
        options = search_flights(origin_code, dest_code, date, adults=leg_travelers)
        options = filter_by_time_pref(options, depart_pref, arrive_pref)
        results[leg_key] = options

    return results
