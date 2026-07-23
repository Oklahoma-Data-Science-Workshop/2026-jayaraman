import logging
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.models import get_db

log = logging.getLogger(__name__)
_scheduler = None


def poll(app, client):
    with app.app_context():
        log.info('Polling iLab reservations')
        today = datetime.now()
        from_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        to_date = (today + timedelta(days=14)).strftime('%Y-%m-%d')
        now_str = today.isoformat()

        try:
            reservations = client.fetch_all(from_date, to_date)

            with get_db() as db:
                db.execute(
                    'DELETE FROM reservations WHERE date(start_date) >= ? AND date(start_date) <= ?',
                    (from_date, to_date)
                )
                for res in reservations:
                    owner = res.get('owner') or {}
                    group = res.get('group_profile') or {}
                    db.execute('''
                        INSERT OR REPLACE INTO reservations
                            (id, schedule_id, equipment_name, core_name, owner_name, owner_email,
                             lab_group, start_date, end_date, no_show, confirmed, polled_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ''', (
                        res['id'],
                        res['_schedule_id'],
                        res.get('equipment_name') or res.get('_eq_name', ''),
                        res.get('_core_name', ''),
                        owner.get('name', ''),
                        owner.get('email', ''),
                        group.get('name', ''),
                        res.get('start_date', ''),
                        res.get('end_date', ''),
                        1 if res.get('no_show') else 0,
                        1 if res.get('confirmed') else 0,
                        now_str,
                    ))
                db.execute(
                    'INSERT INTO poll_log (polled_at, success, reservation_count) VALUES (?,1,?)',
                    (now_str, len(reservations))
                )
            log.info('Cached %d reservations', len(reservations))

        except Exception as e:
            log.error('Poll failed: %s', e)
            try:
                with get_db() as db:
                    db.execute(
                        'INSERT INTO poll_log (polled_at, success, error) VALUES (?,0,?)',
                        (now_str, str(e))
                    )
            except Exception:
                pass


def start_poller(app, client):
    global _scheduler
    interval = app.config.get('POLL_INTERVAL_MINUTES', 15)
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        poll, 'interval', minutes=interval,
        args=[app, client], id='ilab_poll',
        max_instances=1, coalesce=True
    )
    _scheduler.start()
    threading.Thread(target=poll, args=[app, client], daemon=True).start()
    log.info('Poller started (interval=%dm)', interval)
