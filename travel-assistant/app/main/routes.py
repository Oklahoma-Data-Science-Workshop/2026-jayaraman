import json
from concurrent.futures import ThreadPoolExecutor, Future
from flask import (
    render_template,
    redirect,
    url_for,
    request,
    jsonify,
    Response,
    stream_with_context,
    current_app,
)
from app import db
from app.models import TripSession
from app.main import bp
from app.services import planner, flights as flight_svc, maps


@bp.route("/")
def index():
    return render_template("main/index.html")


@bp.route("/new", methods=["POST"])
def new_trip():
    session = TripSession()
    db.session.add(session)
    db.session.commit()
    return redirect(url_for("main.chat", session_id=session.id))


@bp.route("/chat/<session_id>")
def chat(session_id):
    session = TripSession.query.get_or_404(session_id)
    messages = json.loads(session.messages_json or "[]")
    return render_template("main/chat.html", session=session, messages=messages)


@bp.route("/chat/<session_id>/message", methods=["POST"])
def send_message(session_id):
    session = TripSession.query.get_or_404(session_id)

    if session.status not in ("chatting",):
        return jsonify({"error": "Session not in chatting state"}), 400

    user_text = request.json.get("message", "").strip()
    if not user_text:
        return jsonify({"error": "Empty message"}), 400

    messages = json.loads(session.messages_json or "[]")
    messages.append({"role": "user", "content": user_text})

    try:
        reply_text, trip_data = planner.interview_response(messages)
    except Exception as exc:
        current_app.logger.error("Claude interview error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    messages.append({"role": "assistant", "content": reply_text})
    session.messages_json = json.dumps(messages)

    plan_ready = trip_data is not None
    if plan_ready:
        session.trip_data_json = json.dumps(trip_data)
        # Build title from origin/destinations
        origin = trip_data.get("origin", "")
        dests = trip_data.get("destinations", [])
        if dests:
            session.title = f"{origin} → {' → '.join(dests)}"
        session.status = "searching"

    db.session.commit()

    return jsonify({
        "reply": reply_text,
        "plan_ready": plan_ready,
        "status": session.status,
    })


@bp.route("/chat/<session_id>/generate")
def generate_plan(session_id):
    """SSE endpoint: Maps + Flights + Claude plan → stream sections."""
    session = TripSession.query.get_or_404(session_id)

    if not session.trip_data_json:
        return jsonify({"error": "No trip data available"}), 400

    trip_data = json.loads(session.trip_data_json)

    def event_stream():
        # 1. Status update
        yield _sse({"type": "status", "message": "Searching for flights..."})

        # 2. Google Maps distance matrix (drive legs, optional)
        all_cities = [trip_data.get("origin", "")] + trip_data.get("destinations", [])
        drive_cities = [
            leg.get("from") for leg in trip_data.get("legs", []) if leg.get("type") == "drive"
        ]
        matrix = {}
        if drive_cities and current_app.config.get("GOOGLE_MAPS_API_KEY"):
            try:
                matrix = maps.get_distance_matrix(all_cities)
            except Exception as exc:
                current_app.logger.warning("Maps API error: %s", exc)

        # 3. SerpAPI flight search
        flights_data = {}
        try:
            flights_data = flight_svc.search_all_legs(trip_data)
        except Exception as exc:
            current_app.logger.error("Flight search error: %s", exc)
            yield _sse({"type": "status", "message": "Flight search unavailable — using estimates"})

        # Save raw flight results
        with current_app.app_context():
            s = db.session.get(TripSession, session_id)
            if s:
                s.flights_json = json.dumps(flights_data)
                s.status = "generating"
                db.session.commit()

        yield _sse({"type": "status", "message": "Building your itinerary..."})

        # 4. Stream Claude plan; kick off parallel agents as soon as itinerary arrives
        result_sections = []
        dest_intel_future: "Future | None" = None
        connections_future: "Future | None" = None
        hotels_future: "Future | None" = None
        transport_future: "Future | None" = None
        executor = ThreadPoolExecutor(max_workers=4)
        app_obj = current_app._get_current_object()

        try:
            for section in planner.stream_plan(trip_data, flights_data, matrix):
                result_sections.append(section)
                yield _sse({"type": "section", "data": section})

                # Kick off destination intel + connections + hotels in parallel when itinerary arrives
                if section.get("section") == "itinerary" and dest_intel_future is None:
                    itinerary_days = section.get("days", [])

                    def _run_intel(app=app_obj, td=trip_data, days=itinerary_days):
                        with app.app_context():
                            return planner.run_destination_intel(td, days)
                    dest_intel_future = executor.submit(_run_intel)

                    def _run_connections(app=app_obj, td=trip_data, days=itinerary_days):
                        with app.app_context():
                            return planner.run_connections_intel(td, days)
                    connections_future = executor.submit(_run_connections)

                    def _run_hotels(app=app_obj, td=trip_data, days=itinerary_days):
                        with app.app_context():
                            return planner.run_hotels_intel(td, days)
                    hotels_future = executor.submit(_run_hotels)

                    def _run_transport(app=app_obj, td=trip_data, days=itinerary_days):
                        with app.app_context():
                            return planner.run_local_transport_intel(td, days)
                    transport_future = executor.submit(_run_transport)

        except Exception as exc:
            current_app.logger.error("Plan generation error: %s", exc)
            yield _sse({"type": "error", "message": str(exc)})
            executor.shutdown(wait=False)
            return

        # 5. Yield destination intel (ran in parallel with budget + connections)
        if dest_intel_future is not None:
            try:
                dest_section = dest_intel_future.result(timeout=40)
                result_sections.append(dest_section)
                yield _sse({"type": "section", "data": dest_section})
            except Exception as exc:
                current_app.logger.warning("Destination intel error: %s", exc)

        # 6. Yield ground connections
        if connections_future is not None:
            try:
                conn_section = connections_future.result(timeout=40)
                result_sections.append(conn_section)
                yield _sse({"type": "section", "data": conn_section})
            except Exception as exc:
                current_app.logger.warning("Connections intel error: %s", exc)

        # 7. Yield hotels
        if hotels_future is not None:
            try:
                hotels_section = hotels_future.result(timeout=40)
                result_sections.append(hotels_section)
                yield _sse({"type": "section", "data": hotels_section})
            except Exception as exc:
                current_app.logger.warning("Hotels intel error: %s", exc)

        # 8. Yield local transport guide
        if transport_future is not None:
            try:
                transport_section = transport_future.result(timeout=40)
                result_sections.append(transport_section)
                yield _sse({"type": "section", "data": transport_section})
            except Exception as exc:
                current_app.logger.warning("Transport intel error: %s", exc)

        executor.shutdown(wait=False)

        # 6. Finalize
        with current_app.app_context():
            s = db.session.get(TripSession, session_id)
            if s:
                s.result_json = json.dumps(result_sections)
                s.status = "done"
                db.session.commit()

        yield _sse({"type": "done"})

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.route("/trips")
def trips():
    sessions = TripSession.query.order_by(TripSession.created_at.desc()).limit(50).all()
    return render_template("main/trips.html", sessions=sessions)


@bp.route("/trip/<session_id>/view")
def trip_view(session_id):
    session = TripSession.query.get_or_404(session_id)
    if session.mode != "plan" or not session.result_json:
        return render_template("main/trip_view_unavailable.html", session=session), 404
    sections = json.loads(session.result_json)
    by_section = {s["section"]: s for s in sections if "section" in s}
    return render_template("main/trip_view.html", session=session, by_section=by_section)


# ── Discovery routes ──────────────────────────────────────────────────────────

@bp.route("/discover/new", methods=["POST"])
def new_discover():
    session = TripSession(mode="discover", title="Discovering destinations...")
    db.session.add(session)
    db.session.commit()
    return redirect(url_for("main.discover_chat", session_id=session.id))


@bp.route("/discover/<session_id>")
def discover_chat(session_id):
    session = TripSession.query.get_or_404(session_id)
    messages = json.loads(session.messages_json or "[]")
    return render_template("main/discover.html", session=session, messages=messages)


@bp.route("/discover/<session_id>/message", methods=["POST"])
def discover_message(session_id):
    session = TripSession.query.get_or_404(session_id)

    if session.status not in ("chatting",):
        return jsonify({"error": "Session not in chatting state"}), 400

    user_text = request.json.get("message", "").strip()
    if not user_text:
        return jsonify({"error": "Empty message"}), 400

    messages = json.loads(session.messages_json or "[]")
    messages.append({"role": "user", "content": user_text})

    try:
        reply_text, interests_data = planner.discovery_response(messages)
    except Exception as exc:
        current_app.logger.error("Claude discovery error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    messages.append({"role": "assistant", "content": reply_text})
    session.messages_json = json.dumps(messages)

    interests_ready = interests_data is not None
    if interests_ready:
        session.trip_data_json = json.dumps(interests_data)
        origin = interests_data.get("origin", "")
        session.title = f"Discovering: {origin}" if origin else "Discovering destinations"
        session.status = "suggesting"

    db.session.commit()

    return jsonify({
        "reply": reply_text,
        "interests_ready": interests_ready,
        "status": session.status,
    })


@bp.route("/discover/<session_id>/suggest")
def discover_suggest(session_id):
    """SSE endpoint: streams destination suggestion cards."""
    session = TripSession.query.get_or_404(session_id)

    if not session.trip_data_json:
        return jsonify({"error": "No interests data available"}), 400

    interests_data = json.loads(session.trip_data_json)

    def event_stream():
        yield _sse({"type": "status", "message": "Searching the world for your perfect match..."})

        suggestions = []
        try:
            for suggestion in planner.stream_suggestions(interests_data):
                suggestions.append(suggestion)
                yield _sse({"type": "suggestion", "data": suggestion})
        except Exception as exc:
            current_app.logger.error("Suggestion generation error: %s", exc)
            yield _sse({"type": "error", "message": str(exc)})
            return

        with current_app.app_context():
            s = db.session.get(TripSession, session_id)
            if s:
                s.result_json = json.dumps(suggestions)
                s.status = "done"
                db.session.commit()

        yield _sse({"type": "done"})

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/discover/<session_id>/choose", methods=["POST"])
def discover_choose(session_id):
    """User picks a destination — create a pre-seeded planning session and redirect."""
    disc_session = TripSession.query.get_or_404(session_id)
    destination = request.json.get("destination", "").strip()
    if not destination:
        return jsonify({"error": "No destination provided"}), 400

    interests_data = {}
    if disc_session.trip_data_json:
        interests_data = json.loads(disc_session.trip_data_json)

    origin = interests_data.get("origin", "your city")
    group = interests_data.get("travel_group", "")
    duration = interests_data.get("duration_days", "")
    month = interests_data.get("travel_month", "")
    budget = interests_data.get("budget_tier", "mid-range")
    budget_class = "business" if budget == "splurge" else "economy"

    details = [f"Flying from: {origin}"]
    if group:
        details.append(f"Traveling: {group}")
    if duration:
        details.append(f"Duration: ~{duration} days")
    if month:
        details.append(f"Target month: {month}")
    details.append(f"Budget: {budget} ({budget_class} class)")

    details_str = "\n".join(f"• {d}" for d in details)

    greeting = (
        f"Great choice — {destination} is going to be amazing! "
        f"Based on our conversation, here's what I already know:\n\n"
        f"{details_str}\n\n"
        f"I just need a few more details to find real flights and build your full itinerary. "
        f"What specific dates are you thinking for departure and return?"
    )

    plan_session = TripSession(
        mode="plan",
        title=f"{origin} → {destination}",
        messages_json=json.dumps([{"role": "assistant", "content": greeting}]),
        status="chatting",
    )
    db.session.add(plan_session)
    db.session.commit()

    return jsonify({"redirect": url_for("main.chat", session_id=plan_session.id)})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
