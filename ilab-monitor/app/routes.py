from datetime import datetime, timedelta
from flask import Blueprint, jsonify
from app.models import get_db

bp = Blueprint('main', __name__)


def _rows(cursor):
    return [dict(r) for r in cursor]


@bp.route('/')
def index():
    return (
        '<!DOCTYPE html><html><head><title>iLab Monitor</title></head>'
        '<body style="font-family:sans-serif;max-width:600px;margin:2em auto">'
        '<h1>iLab Equipment Monitor</h1><ul>'
        '<li><a href="/api/now">In Use Right Now</a></li>'
        '<li><a href="/api/today">Today\'s Schedule</a></li>'
        '<li><a href="/api/tomorrow">Tomorrow</a></li>'
        '<li><a href="/api/week">This Week</a></li>'
        '<li><a href="/api/status">Poller Status</a></li>'
        '</ul></body></html>'
    )


@bp.route('/api/now')
def api_now():
    now = datetime.now().strftime('%Y-%m-%dT%H:%M')
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM reservations'
            ' WHERE start_date <= ? AND end_date >= ? AND no_show = 0'
            ' ORDER BY core_name, equipment_name',
            (now, now)
        ).fetchall()
    return jsonify(_rows(rows))


@bp.route('/api/today')
def api_today():
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM reservations'
            ' WHERE date(start_date) = ? OR date(end_date) = ?'
            ' ORDER BY start_date',
            (today, today)
        ).fetchall()
    return jsonify(_rows(rows))


@bp.route('/api/tomorrow')
def api_tomorrow():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM reservations WHERE date(start_date) = ? ORDER BY start_date',
            (tomorrow,)
        ).fetchall()
    return jsonify(_rows(rows))


@bp.route('/api/week')
def api_week():
    today = datetime.now().strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM reservations'
            ' WHERE date(start_date) >= ? AND date(start_date) <= ?'
            ' ORDER BY start_date',
            (today, end)
        ).fetchall()
    return jsonify(_rows(rows))


@bp.route('/api/status')
def api_status():
    with get_db() as db:
        last = db.execute('SELECT * FROM poll_log ORDER BY id DESC LIMIT 1').fetchone()
        total = db.execute('SELECT COUNT(*) as n FROM reservations').fetchone()
    return jsonify({
        'last_poll': dict(last) if last else None,
        'cached_reservations': total['n'] if total else 0,
        'status': 'ok',
    })
