import sqlite3
import os

_db_path = None


def init_db(app):
    global _db_path
    _db_path = os.path.join(app.instance_path, 'ilab.db')
    with get_db() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS reservations (
                id          INTEGER,
                schedule_id TEXT,
                equipment_name TEXT,
                core_name   TEXT,
                owner_name  TEXT,
                owner_email TEXT,
                lab_group   TEXT,
                start_date  TEXT,
                end_date    TEXT,
                no_show     INTEGER DEFAULT 0,
                confirmed   INTEGER DEFAULT 0,
                polled_at   TEXT,
                PRIMARY KEY (id, schedule_id)
            );
            CREATE TABLE IF NOT EXISTS poll_log (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                polled_at         TEXT,
                success           INTEGER,
                reservation_count INTEGER,
                error             TEXT
            );
        ''')


def get_db():
    db = sqlite3.connect(_db_path)
    db.row_factory = sqlite3.Row
    return db
