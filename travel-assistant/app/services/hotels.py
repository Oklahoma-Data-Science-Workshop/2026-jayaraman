import re
from datetime import datetime
import requests
from flask import current_app


def _parse_date(day_str: str, year: str) -> str | None:
    """Convert 'Sep 10' + '2026' to '2026-09-10'. Returns None on failure."""
    if not day_str or not year:
        return None
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", day_str.strip())
    for fmt in ("%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(f"{cleaned} {year}", fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _extract_year(dates_str: str) -> str:
    """Pull a 4-digit year from a string like 'Sep 10–20 2026'."""
    m = re.search(r"\b(20\d{2})\b", dates_str or "")
    return m.group(1) if m else str(datetime.now().year)


def search_hotels(city: str, check_in: str = None, check_out: str = None) -> list:
    """
    Search Google Hotels via SerpAPI for 4-star-and-above properties.
    Returns up to 6 hotels sorted by guest rating descending.
    """
    api_key = current_app.config.get("SERPAPI_KEY", "")
    if not api_key:
        return []

    params = {
        "engine": "google_hotels",
        "q": city,
        "api_key": api_key,
        "hl": "en",
        "gl": "us",
        "currency": "USD",
        "sort_by": "3",  # sort by rating
    }
    if check_in:
        params["check_in_date"] = check_in
    if check_out:
        params["check_out_date"] = check_out

    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        current_app.logger.warning("Hotels API error for %s: %s", city, exc)
        return []

    hotels = []
    for prop in data.get("properties", []):
        star_class = prop.get("extracted_hotel_class", 0)
        if star_class < 4:
            continue

        rate = prop.get("rate_per_night") or {}
        images = prop.get("images") or []
        amenities = prop.get("amenities") or []

        hotels.append({
            "name": prop.get("name", ""),
            "star_class": star_class,
            "overall_rating": prop.get("overall_rating"),
            "reviews": prop.get("reviews", 0),
            "price_per_night": rate.get("lowest", ""),
            "price_usd": rate.get("extracted_lowest"),
            "amenities": amenities[:5],
            "description": (prop.get("description") or "")[:200],
            "image": images[0].get("original_image", "") if images else "",
            "link": prop.get("link", ""),
        })

    hotels.sort(key=lambda h: (-(h.get("overall_rating") or 0), -h.get("star_class", 0)))
    return hotels[:6]


def search_all_cities(trip_data: dict, itinerary_days: list) -> dict:
    """
    Search 4+ star hotels for every destination city in the itinerary.
    Returns {"section": "hotels", "cities": [...]}
    """
    from concurrent.futures import ThreadPoolExecutor

    year = _extract_year(trip_data.get("dates", ""))

    # Group itinerary days by city; record first and last date
    city_dates: dict[str, dict] = {}
    for day in itinerary_days:
        city = day.get("city", "").strip()
        if not city:
            continue
        d = day.get("date", "")
        if city not in city_dates:
            city_dates[city] = {"first": d, "last": d, "order": len(city_dates)}
        else:
            city_dates[city]["last"] = d

    def fetch(city: str, info: dict) -> dict:
        check_in = _parse_date(info["first"], year)
        check_out = _parse_date(info["last"], year)
        hotels = search_hotels(city, check_in, check_out)
        return {
            "city": city,
            "check_in": check_in or info["first"],
            "check_out": check_out or info["last"],
            "hotels": hotels,
        }

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch, city, info): city for city, info in city_dates.items()}
        for fut, city in futures.items():
            try:
                results.append(fut.result(timeout=25))
            except Exception as exc:
                current_app.logger.warning("Hotel fetch failed for %s: %s", city, exc)

    # Preserve itinerary order
    order = list(city_dates.keys())
    results.sort(key=lambda r: order.index(r["city"]) if r["city"] in order else 999)

    return {"section": "hotels", "cities": results}
