import json
import re
from flask import current_app
import anthropic

PLAN_READY_MARKER = "%%PLAN_READY%%"

INTERVIEW_SYSTEM = """You are a friendly, efficient travel agent. Collect trip details one or two questions at a time. Gather:
- Origin city and all destinations/stops
- Who is traveling (any return-route splits — different people flying home to different cities?)
- Travel dates (outbound and return for each traveler)
- Preferred departure time window for outbound flights (e.g., early morning / mid-morning / afternoon / evening — no red-eyes?)
- Preferred return time window (e.g., want to land before 8 PM?)
- Budget/class preference (economy / business)
- Priorities (cheapest / fewest stops / best schedule / specific airline)

Be conversational. Ask one or two questions at a time. If the user mentions comfort or convenience, probe for preferred time windows. A question like "Do you have a preferred time of day to fly out, or any times you'd like to avoid?" is always worth asking.

STOPOVER OPPORTUNITIES — proactively suggest these when the route naturally passes through a hub:
When you learn the origin and destination, check if the route commonly connects through a city that has an attractive stopover program. If so, BEFORE finalising the plan, ask the traveler if they'd like to turn that layover into a 1–2 day stopover to explore the hub city. Only suggest one stopover per conversation; pick the most compelling one. Frame it as a bonus opportunity, not an obligation.

Known stopover hub programs to watch for (airline → hub city → when to suggest):
- Etihad / Emirates / flydubai → Dubai or Abu Dhabi: any flight from the US/Europe to India, Southeast Asia, East Africa, or Australia
- Qatar Airways → Doha: same long-haul routes through the Gulf
- Turkish Airlines → Istanbul: flights from the Americas or Asia to Europe, Middle East, or Africa
- Singapore Airlines / Scoot → Singapore: US/Europe to Southeast Asia, Australia, or New Zealand
- Cathay Pacific → Hong Kong: US/Europe to Southeast Asia, Japan, Korea, China, Australia
- Icelandair → Reykjavik: transatlantic flights between North America and Europe
- Finnair → Helsinki: flights to/from Asia (especially Japan, Korea, China) or North America to northern Europe
- TAP Air Portugal → Lisbon: North America to southern Europe, Africa, or Brazil
- Aer Lingus → Dublin: US/Canada eastbound to Europe
- Royal Air Maroc → Casablanca: Europe or US to West Africa or sub-Saharan Africa
- LATAM / Avianca → Bogotá or Lima: North America to South America or onward to other South American cities
- Air Canada → Toronto or Vancouver: US cities to Europe, Asia, or Australia

Example phrasing: "Since you're flying from [origin] to [destination], you'd likely route through [hub city] anyway — [Airline] has a great stopover program there. Would you like to spend a day or two in [hub city] on the way? I can build that into your itinerary."

If the traveler says yes: ask how many nights (suggest 1–2), then incorporate the hub city as a proper stop — add it to destinations[], insert the relevant legs into the legs[] array with appropriate dates, and plan it as a mini-destination in the itinerary.
If they say no or skip: continue normally without it.

When you have all details, end naturally ("Let me search for flights and build your itinerary!") and on the very last line output exactly:
%%PLAN_READY%%{"origin":"OKC","destinations":["Boston","Madrid"],"legs":[{"from":"OKC","to":"Boston","type":"flight","date":"2026-09-10","depart_pref":"morning","arrive_pref":"afternoon"},{"from":"Boston","to":"Madrid","type":"flight","date":"2026-09-12","depart_pref":"any","arrive_pref":"any"},{"from":"Madrid","to":"OKC","type":"flight","date":"2026-09-20","depart_pref":"morning","arrive_pref":"before_8pm"},{"from":"Madrid","to":"Boston","type":"flight","date":"2026-09-20","depart_pref":"morning","arrive_pref":"any"}],"travelers":2,"dates":"Sep 10–20 2026","num_days":10,"budget":"economy","priorities":["cheapest","direct"]}

depart_pref / arrive_pref values: "early_morning" (before 8am), "morning" (8am-noon), "afternoon" (noon-6pm), "evening" (after 6pm), "no_redeye" (avoid overnight), "before_8pm", "any".

CRITICAL: Never show %%PLAN_READY%% or the JSON to the user — that line is machine-readable only. Your conversational message must appear BEFORE that line."""


PLAN_SYSTEM = """You are an expert travel planner. You have been given real flight search results and a complete trip profile. Your job is to produce a structured travel plan.

Output exactly 4 JSON objects, one per line (NDJSON). Do not add any commentary outside the JSON lines.

Line 1 — Route overview:
{"section":"route","optimal_order":["City1","City2"],"reasoning":"..."}

Line 2 — Flights per leg. For each leg, pick the best option based on priorities and time preferences. Explain why in the "why" field — always mention time preference when it is the deciding factor:
{"section":"flights","legs":[{"from":"OKC","to":"Boston","date":"Sep 10","time_pref":"morning departure, arrive by afternoon","recommended":{"airline":"American Airlines","flight":"AA 2301","departs":"08:45","arrives":"15:20","stops":1,"price_usd":312,"why":"Morning departure fits your schedule; lands mid-afternoon well before 8 PM"},"alternatives":[{"airline":"Delta","price_usd":389,"stops":0,"departs":"11:00","arrives":"17:30","comfort_match":true},{"airline":"United","price_usd":276,"stops":2,"departs":"06:00","arrives":"14:45","comfort_match":false,"note":"Very early departure"}]}]}

Line 3 — Day-by-day itinerary:
{"section":"itinerary","days":[{"day":1,"city":"Boston","date":"Sep 10","activities":["Arrive Logan Airport","Check in Back Bay hotel","Evening walk on Freedom Trail"]}]}

Line 4 — Budget breakdown:
{"section":"budget","breakdown":[{"category":"Flights (traveler 1)","amount":"$623"},{"category":"Hotel estimate (N nights × $X)","amount":"$960"},{"category":"Daily expenses (N days × $X)","amount":"$640"}],"total_range":"$2,800–$3,400","tips":["Book 6–8 weeks out for best prices","Madrid hotel cheaper booked directly"]}

Base hotel estimates on typical rates for the destination city. Include both travelers' flights if there are splits. Be specific and helpful."""


def interview_response(messages: list) -> tuple:
    """
    Send conversation to Claude for interview phase.
    Returns (display_text: str, trip_data: dict | None).
    trip_data is non-None when %%PLAN_READY%% is detected.
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=1024,
        system=INTERVIEW_SYSTEM,
        messages=messages,
    )

    full_text = response.content[0].text

    # Detect PLAN_READY marker
    trip_data = None
    display_text = full_text

    if PLAN_READY_MARKER in full_text:
        # Split on marker line — extract JSON and clean display text
        lines = full_text.splitlines()
        clean_lines = []
        for line in lines:
            if line.strip().startswith(PLAN_READY_MARKER):
                json_str = line.strip()[len(PLAN_READY_MARKER):]
                try:
                    trip_data = json.loads(json_str)
                except json.JSONDecodeError:
                    # Try extracting JSON with regex
                    m = re.search(r"\{.*\}", json_str, re.DOTALL)
                    if m:
                        try:
                            trip_data = json.loads(m.group())
                        except json.JSONDecodeError:
                            pass
                # Don't include this line in display text
            else:
                clean_lines.append(line)

        display_text = "\n".join(clean_lines).strip()

    return display_text, trip_data


DEST_INTEL_SYSTEM = """You are a destination intelligence specialist. Given a list of cities a traveler will visit, produce a JSON array (one object per city) with rich, opinionated, practical destination content.

Output a single JSON array. No commentary outside the JSON.

For each city:
{
  "city": "Madrid",
  "tagline": "One-line poetic hook",
  "neighborhoods": [{"name": "La Latina", "vibe": "Old-town tapas & flamenco"}],
  "must_do": ["Prado Museum (book timed entry)", "Retiro Park on a Sunday morning"],
  "hidden_gems": ["Mercado de San Fernando in Lavapiés", "Rooftop at Círculo de Bellas Artes"],
  "skip": ["Overhyped touristy spots with better alternatives"],
  "day_trips": [{"destination": "Toledo", "why": "Medieval walled city, 30 min by AVE"}],
  "food": {"signature_dishes": ["cocido madrileño", "bocadillo de calamares"], "best_neighborhood_to_eat": "La Latina"},
  "practical": {"currency": "EUR", "language_tip": "Basic Spanish appreciated", "transport": "Metro excellent, 10-ride card saves money", "best_time_of_day": "Morning for museums, evening for tapas circuit"},
  "seasonal_note": "September: warm, post-summer crowds — ideal"
}

Be specific and opinionated. Avoid generic travel-brochure language. If a city has a stopover (1-2 nights), scale down to 3 must-dos and skip day trips."""


def run_destination_intel(trip_data: dict, itinerary_days: list) -> dict:
    """
    Blocking call to Claude for destination intelligence.
    Returns {"section": "destinations", "cities": [...]}
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    # Build city list with context (stopover vs full stay)
    cities = []
    destinations = trip_data.get("destinations", [])
    num_days = trip_data.get("num_days", 7)
    for dest in destinations:
        days_here = sum(1 for d in itinerary_days if d.get("city", "").lower() == dest.lower())
        cities.append({"city": dest, "nights": days_here or (num_days // max(len(destinations), 1))})

    prompt = f"Trip dates: {trip_data.get('dates', 'unknown')}\nCities to cover:\n{json.dumps(cities, indent=2)}"

    response = client.messages.create(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=4096,
        system=DEST_INTEL_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    cities_data = json.loads(raw)
    return {"section": "destinations", "cities": cities_data}


def stream_plan(trip_data: dict, flights: dict, matrix: dict):
    """
    Generator: streams the travel plan from Claude as parsed section dicts.
    Yields dicts as each complete JSON line is parsed from the NDJSON stream.
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    # Build context message with all the data
    context_parts = [
        f"TRIP PROFILE:\n{json.dumps(trip_data, indent=2)}",
        f"\nREAL FLIGHT OPTIONS (from SerpAPI):\n{json.dumps(flights, indent=2)}",
    ]
    if matrix:
        context_parts.append(f"\nDRIVING DISTANCES:\n{json.dumps(matrix, indent=2)}")

    context = "\n".join(context_parts)

    with client.messages.stream(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=4096,
        system=PLAN_SYSTEM,
        messages=[{"role": "user", "content": context}],
    ) as stream:
        buffer = ""
        for text_chunk in stream.text_stream:
            buffer += text_chunk
            # Parse complete JSON lines from buffer
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    yield obj
                except json.JSONDecodeError:
                    # Partial or non-JSON line — skip
                    pass

        # Handle any remaining content in buffer
        if buffer.strip():
            try:
                obj = json.loads(buffer.strip())
                yield obj
            except json.JSONDecodeError:
                pass


# ── Ground Connections Agent ─────────────────────────────────────────────────

CONNECTIONS_SYSTEM = """You are a ground transportation specialist. Given a trip itinerary, identify the best train/transit connections between consecutive cities and recommend essential local apps for each country visited.

Output a single JSON object. No commentary outside the JSON.

{
  "section": "connections",
  "city_pairs": [
    {
      "from": "Paris",
      "to": "Barcelona",
      "recommended_transport": "train",
      "operator": "Renfe + SNCF",
      "service_name": "TGV/AVE high-speed",
      "duration": "6h 25m",
      "frequency": "3–4 direct trains daily",
      "price_range": "€25–€130 economy",
      "booking_platform": "Renfe.com or Omio",
      "book_ahead": "4–8 weeks for best prices",
      "tips": ["City-center to city-center — often faster than flying once you add airport time", "Book early morning trains for lowest fares"],
      "alternatives": [
        {"type": "bus", "operator": "FlixBus", "duration": "~14h", "price_range": "€15–€40", "note": "Budget option, overnight buses available"}
      ]
    }
  ],
  "country_apps": [
    {
      "country": "France",
      "flag": "🇫🇷",
      "apps": [
        {"name": "SNCF Connect", "category": "Trains", "why": "Official booking for all TGV and regional trains", "platforms": "iOS + Android"},
        {"name": "Citymapper", "category": "Metro/Bus", "why": "Best real-time Paris metro, RER and bus navigator", "platforms": "iOS + Android"},
        {"name": "Navigo Easy", "category": "Transit card", "why": "Digital Paris metro/bus card — load credit on your phone", "platforms": "iOS + Android"},
        {"name": "Bolt", "category": "Ride-share", "why": "Cheaper than Uber in Paris for short trips", "platforms": "iOS + Android"}
      ]
    }
  ]
}

Rules:
- city_pairs: only include consecutive city pairs from the itinerary that are within practical ground-transport range (roughly under 1200 km / 10 h by the best train). Omit pairs where flying is the only realistic option.
- If a pair already has a flight booked but a faster/cheaper train exists, still include it — note it as an alternative to the booked flight.
- Be specific about operators ("Deutsche Bahn ICE", not just "train"), service names, and booking URLs.
- country_apps: 4–6 apps per country actually visited. Prioritise in order: (1) national rail booking app, (2) city metro/bus app for each major city, (3) navigation (Google Maps is fine but add local alternatives where they dominate), (4) ride-share/taxi. Include the country's main intercity bus app if relevant.
- category must be one of: Trains, Metro/Bus, Navigation, Ride-share, Transit card, Intercity bus
- Only include countries that appear in the itinerary.
- If no ground connections exist (single city, island, all-flight legs), return an empty city_pairs array but still include country_apps."""


def run_connections_intel(trip_data: dict, itinerary_days: list) -> dict:
    """
    Blocking call to Claude for ground connections + local app recommendations.
    Returns {"section": "connections", "city_pairs": [...], "country_apps": [...]}
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    cities_in_order = []
    seen: set = set()
    for day in itinerary_days:
        city = day.get("city", "")
        if city and city not in seen:
            cities_in_order.append(city)
            seen.add(city)

    day_summary = "\n".join(
        f"Day {d.get('day')}: {d.get('city')} ({d.get('date', '')})"
        for d in itinerary_days
    )
    prompt = (
        f"Trip profile:\n{json.dumps(trip_data, indent=2)}\n\n"
        f"Cities visited in order: {' → '.join(cities_in_order)}\n\n"
        f"Itinerary:\n{day_summary}"
    )

    response = client.messages.create(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=4096,
        system=CONNECTIONS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"city_pairs": [], "country_apps": []}

    data["section"] = "connections"
    return data


# ── Hotels Agent ─────────────────────────────────────────────────────────────

def run_hotels_intel(trip_data: dict, itinerary_days: list) -> dict:
    """
    Blocking call: searches 4+ star hotels for every destination city.
    Returns {"section": "hotels", "cities": [...]}
    """
    from app.services import hotels as hotel_svc
    return hotel_svc.search_all_cities(trip_data, itinerary_days)


# ── Local Transport Agent ────────────────────────────────────────────────────

LOCAL_TRANSPORT_SYSTEM = """You are a local transportation expert. For each city a traveler will visit, produce a detailed, practical guide covering how to get from the airport to the city center, how to get around locally, which transit cards to obtain, and which apps to download before landing.

Output a single JSON array (one object per city). No commentary outside the JSON.

For each city:
{
  "city": "Tokyo",
  "airport_transfer": [
    {
      "name": "Narita Express (N'EX)",
      "type": "train",
      "duration": "60 min",
      "price": "¥3,070 (~$20)",
      "frequency": "Every 30 min, 6am–10pm",
      "tip": "Fastest and most reliable — goes directly to Shinjuku/Shibuya"
    }
  ],
  "local_transit": {
    "system": "Tokyo Metro + Toei Subway + JR Lines",
    "coverage": "Excellent — virtually every attraction reachable by rail",
    "day_pass": "Tokyo Metro 24h pass: ¥600 (~$4)",
    "operating_hours": "5am–midnight; last trains vary by line",
    "tip": "Suica IC card works everywhere — trains, buses, taxis, convenience stores"
  },
  "transit_cards": [
    {
      "name": "Suica",
      "where_to_get": "Any JR vending machine or Apple/Google Wallet before you land",
      "works_for": "All trains, buses, taxis, vending machines, convenience stores",
      "cost": "¥500 deposit + load credit",
      "must_have": true
    }
  ],
  "ride_share": {
    "available": true,
    "main_apps": ["GO タクシー", "Uber (limited coverage)"],
    "avg_fare_local": "$6–$18 for most city trips",
    "tip": "Taxis are metered and honest; hail on the street or use GO app"
  },
  "apps": [
    {
      "name": "Google Maps",
      "category": "Navigation",
      "why": "Transit routing in Tokyo is near-perfect — shows exact car to board, platform number",
      "download_before_landing": true
    },
    {
      "name": "Suica (JR East)",
      "category": "Transit card",
      "why": "Load your IC card balance before you land to skip airport queues",
      "download_before_landing": true
    },
    {
      "name": "GO タクシー",
      "category": "Taxi/Ride-share",
      "why": "The dominant taxi-booking app in Japan — more cabs than Uber",
      "download_before_landing": false
    }
  ],
  "cycling": "Docomo Bike Share across major wards — ¥165/30 min; great for flat areas like Asakusa and Ueno",
  "practical_tips": [
    "Last trains run around midnight — note your line's last departure or budget for a taxi home",
    "IC cards require tapping in AND out — failure means penalty fare",
    "Taxis open/close their doors automatically — don't touch the door"
  ]
}

Rules:
- airport_transfer: list 2–3 realistic options (train, bus, taxi/ride-share). Always include the cheapest and fastest.
- local_transit: be specific — name the actual metro/bus system, not just 'good public transit'.
- transit_cards: only include if genuinely useful. Mark must_have: true only for cards that work citywide.
- ride_share: name the actual dominant apps (Grab in SE Asia, Bolt in Europe, DiDi in China, etc.) — not just 'Uber'.
- apps: 3–5 apps. Mark download_before_landing: true only for apps worth installing before arrival (offline maps, transit cards that need setup, etc.).
- cycling: one sentence if bike share exists; omit the field if not.
- practical_tips: 2–4 sharp, specific tips — not generic safety advice.
- If the city is a short stopover (1–2 nights), focus airport_transfer and top 2 apps only."""


def run_local_transport_intel(trip_data: dict, itinerary_days: list) -> dict:
    """
    Blocking call to Claude for per-city local transport guide.
    Returns {"section": "transport", "cities": [...]}
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    cities = []
    destinations = trip_data.get("destinations", [])
    num_days = trip_data.get("num_days", 7)
    for dest in destinations:
        nights = sum(1 for d in itinerary_days if d.get("city", "").lower() == dest.lower())
        cities.append({"city": dest, "nights": nights or (num_days // max(len(destinations), 1))})

    prompt = (
        f"Trip dates: {trip_data.get('dates', 'unknown')}\n"
        f"Traveler origin: {trip_data.get('origin', 'unknown')}\n"
        f"Cities to cover:\n{json.dumps(cities, indent=2)}"
    )

    response = client.messages.create(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=4096,
        system=LOCAL_TRANSPORT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        cities_data = json.loads(raw)
    except json.JSONDecodeError:
        cities_data = []

    return {"section": "transport", "cities": cities_data}


# ── Discovery Agent ───────────────────────────────────────────────────────────

INTERESTS_READY_MARKER = "%%INTERESTS_READY%%"

DISCOVERY_SYSTEM = """You are a warm, curious travel concierge helping someone discover where to go next. Your goal is to understand what kind of traveler they are so you can recommend destinations that will genuinely delight them.

Ask 1-2 conversational questions at a time. Be enthusiastic but concise. Over 4-6 exchanges, naturally cover:
- What travel experiences excite them most (culture, food, history, adventure, beaches, nature, nightlife, art, architecture, wellness)
- Who they're traveling with (solo, couple, family with kids, friend group)
- Travel pace and style (slow & deep vs. packed schedule; spontaneous vs. planned; luxury vs. budget vs. mid-range)
- When they're thinking of going (month/season) and how many days they have
- Where they'll be flying from (for flight time context)
- Their budget tier (budget / mid-range / splurge — no need for exact numbers)
- Places they've been and loved or hated (key calibration signal — "I loved Kyoto but found Paris overrated" tells you everything)
- Any hard constraints (max comfortable flight duration, visa difficulties, regions to avoid, climate preferences, mobility needs)

When you have a clear enough picture (after 4-6 exchanges), wrap up enthusiastically ("I have everything I need — let me find your perfect match!") and on the very last line output exactly:
%%INTERESTS_READY%%{"origin":"Houston, TX","interests":["food","history","culture"],"travel_group":"couple","pace":"slow","duration_days":10,"travel_month":"October 2026","budget_tier":"mid-range","loved_places":["Japan"],"avoided_places":[],"max_flight_hours":null,"constraints":[]}

CRITICAL: Never show %%INTERESTS_READY%% or the JSON to the user — that line is machine-readable only. Your conversational message must appear BEFORE that line."""


SUGGEST_SYSTEM = """You are a destination recommendation specialist. Given a traveler's interest profile, suggest exactly 4 destinations that are a strong personal match — not just generic popular spots.

Output exactly 4 JSON objects, one per line (NDJSON). No commentary outside the JSON. Rank by best fit.

Each line:
{"section":"suggestion","rank":1,"destination":"Lisbon, Portugal","country":"Portugal","region":"Europe","tagline":"Sun-soaked history with zero pretension","why_you":"Concise 2-sentence explanation of why THIS specific profile matches THIS destination","highlights":["Alfama fado music at night","Pastéis de nata bakery crawl","Sintra palace day trip"],"cost_tier":"$$$","approx_flight_hours":9,"best_time_match":"October is ideal — warm, dry, post-summer crowds gone","visa_note":"US passport: no visa required","surprise_factor":"One honest insight that makes this pick surprising or underrated"}

Rules:
- Be specific about WHY this traveler in particular would love each destination
- Mix regions — don't suggest 4 European cities unless constraints force it
- Include at least one surprising pick the traveler likely hasn't considered
- approx_flight_hours: integer estimate from their origin city via best routing
- cost_tier: "$" budget, "$$" mid-range, "$$$" comfortable, "$$$$" splurge
- Respect loved/avoided places — don't re-suggest avoided destinations"""


def discovery_response(messages: list) -> tuple:
    """
    Send conversation to Claude for discovery phase.
    Returns (display_text: str, interests_data: dict | None).
    interests_data is non-None when %%INTERESTS_READY%% is detected.
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    response = client.messages.create(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=1024,
        system=DISCOVERY_SYSTEM,
        messages=messages,
    )

    full_text = response.content[0].text
    interests_data = None
    display_text = full_text

    if INTERESTS_READY_MARKER in full_text:
        lines = full_text.splitlines()
        clean_lines = []
        for line in lines:
            if line.strip().startswith(INTERESTS_READY_MARKER):
                json_str = line.strip()[len(INTERESTS_READY_MARKER):]
                try:
                    interests_data = json.loads(json_str)
                except json.JSONDecodeError:
                    m = re.search(r"\{.*\}", json_str, re.DOTALL)
                    if m:
                        try:
                            interests_data = json.loads(m.group())
                        except json.JSONDecodeError:
                            pass
            else:
                clean_lines.append(line)
        display_text = "\n".join(clean_lines).strip()

    return display_text, interests_data


def stream_suggestions(interests_data: dict):
    """
    Generator: streams destination suggestions from Claude as parsed dicts.
    Yields suggestion dicts as each complete JSON line arrives.
    """
    client = anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"])

    prompt = f"Traveler profile:\n{json.dumps(interests_data, indent=2)}"

    with client.messages.stream(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=2048,
        system=SUGGEST_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        buffer = ""
        for text_chunk in stream.text_stream:
            buffer += text_chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    yield obj
                except json.JSONDecodeError:
                    pass

        if buffer.strip():
            try:
                obj = json.loads(buffer.strip())
                yield obj
            except json.JSONDecodeError:
                pass
