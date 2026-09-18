"""Database layer + demo seed data for the Smart Laptop Tracker.

Uses SQLite from the Python standard library, so there are no external
services to install.  The database file is created automatically on first
run.  Seed data is dated *relative to today* so that a fresh demo always
looks alive (active sessions, upcoming bookings, an overdue return, and
historical usage logs).
"""

import os
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "laptops.db")

# Rooms a laptop can live in / be booked for, and the staff roster offered
# to teachers in the booking form (free-text names are also accepted).
ROOMS = [
    "ICT Office",
    "Room 101",
    "Room 102",
    "Room 103",
    "Science Lab",
    "ICT Suite A",
    "ICT Suite B",
    "Library",
    "Staff Room",
    "Main Hall",
]

TEACHERS = [
    "Ms. A. Khan",
    "Mr. D. Patel",
    "Mrs. S. Thompson",
    "Mr. J. Okafor",
    "Ms. L. Nguyen",
    "Mr. R. Ahmed",
    "Mrs. E. Davies",
    "Mr. T. Walker",
    "Ms. H. Ali",
    "Mr. P. Novak",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS laptops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_tag    TEXT UNIQUE NOT NULL,
    model        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'available',  -- available | in-use | maintenance
    current_room TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bookings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher    TEXT NOT NULL,
    room       TEXT NOT NULL,
    date       TEXT NOT NULL,   -- YYYY-MM-DD
    start_time TEXT NOT NULL,   -- HH:MM
    end_time   TEXT NOT NULL,   -- HH:MM
    quantity   INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'booked',  -- booked | active | completed | cancelled | expired
    created_at TEXT NOT NULL
);

-- Which physical laptops are reserved by which booking.
CREATE TABLE IF NOT EXISTS booking_laptops (
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    laptop_id  INTEGER NOT NULL REFERENCES laptops(id),
    PRIMARY KEY (booking_id, laptop_id)
);

-- The audit trail that replaces the paper log: who had which laptop,
-- where, from when to when, and for how long.
CREATE TABLE IF NOT EXISTS usage_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id       INTEGER REFERENCES bookings(id),
    laptop_id        INTEGER NOT NULL REFERENCES laptops(id),
    teacher          TEXT NOT NULL,
    room             TEXT NOT NULL,
    checkout_at      TEXT NOT NULL,
    checkin_at       TEXT,
    duration_minutes INTEGER
);
"""


def get_db():
    """Open a connection with dict-like rows and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if needed; seed demo data on a brand-new database."""
    fresh = not os.path.exists(DB_PATH)
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        if fresh:
            seed(conn)
        conn.commit()
    finally:
        conn.close()


def reset_db():
    """Drop the database file and re-seed (used by the demo reset button)."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seed(conn):
    """Insert 20 laptops and a realistic set of bookings/logs around 'now'."""
    now = datetime.now()

    # --- 20 laptops across three models ---------------------------------
    for i in range(1, 21):
        if i <= 8:
            model = "Dell Latitude 3420"
        elif i <= 15:
            model = "HP ProBook 440 G9"
        else:
            model = "Lenovo ThinkPad E14"
        tag = f"LT-{i:02d}"
        status = "maintenance" if tag == "LT-14" else "available"
        notes = "Cracked screen — sent to repair vendor" if tag == "LT-14" else ""
        conn.execute(
            "INSERT INTO laptops (asset_tag, model, status, current_room, notes)"
            " VALUES (?,?,?,?,?)",
            (tag, model, status, "ICT Office", notes),
        )

    def lid(tag):
        return conn.execute(
            "SELECT id FROM laptops WHERE asset_tag = ?", (tag,)
        ).fetchone()["id"]

    def add_session(teacher, room, start_dt, end_dt, tags, status,
                    checkout_dt=None, checkin_dt=None):
        """Insert a booking plus (optionally) its checkout/check-in logs."""
        cur = conn.execute(
            "INSERT INTO bookings (teacher, room, date, start_time, end_time,"
            " quantity, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                teacher, room,
                start_dt.strftime("%Y-%m-%d"),
                start_dt.strftime("%H:%M"),
                end_dt.strftime("%H:%M"),
                len(tags), status,
                _ts(start_dt - timedelta(days=1)),
            ),
        )
        bid = cur.lastrowid
        for tag in tags:
            conn.execute(
                "INSERT INTO booking_laptops (booking_id, laptop_id) VALUES (?,?)",
                (bid, lid(tag)),
            )
            if status == "active":
                conn.execute(
                    "UPDATE laptops SET status='in-use', current_room=? WHERE id=?",
                    (room, lid(tag)),
                )
            if checkout_dt is not None:
                cin = _ts(checkin_dt) if checkin_dt else None
                dur = (
                    int((checkin_dt - checkout_dt).total_seconds() // 60)
                    if checkin_dt else None
                )
                conn.execute(
                    "INSERT INTO usage_logs (booking_id, laptop_id, teacher, room,"
                    " checkout_at, checkin_at, duration_minutes)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (bid, lid(tag), teacher, room, _ts(checkout_dt), cin, dur),
                )

    def at(days_ago=0, hours=0, minutes=0):
        """Helper: today +/- offsets at a wall-clock time."""
        base = now - timedelta(days=days_ago)
        return base.replace(hour=hours, minute=minutes, second=0, microsecond=0)

    def span(days_ago, h1, m1, h2, m2):
        return at(days_ago, h1, m1), at(days_ago, h2, m2)

    # --- Historical (completed) usage -----------------------------------
    s, e = span(3, 10, 0, 11, 30)
    add_session("Mrs. E. Davies", "Room 103", s, e,
                ["LT-18", "LT-19", "LT-20"], "completed",
                s + timedelta(minutes=3), e - timedelta(minutes=3))

    s, e = span(2, 11, 15, 12, 0)
    add_session("Ms. H. Ali", "Library", s, e,
                ["LT-06", "LT-07"], "completed",
                s + timedelta(minutes=2), e - timedelta(minutes=2))

    s, e = span(1, 9, 0, 10, 30)
    add_session("Mrs. S. Thompson", "Room 101", s, e,
                ["LT-01", "LT-02", "LT-03", "LT-04", "LT-05"], "completed",
                s + timedelta(minutes=2), e - timedelta(minutes=2))

    s, e = span(1, 13, 0, 14, 0)
    add_session("Mr. D. Patel", "ICT Suite A", s, e,
                ["LT-09", "LT-10", "LT-11", "LT-12"], "completed",
                s + timedelta(minutes=4), e - timedelta(minutes=5))

    # --- Today: an overdue session (checked out, never returned) ---------
    s, e = now - timedelta(hours=3), now - timedelta(hours=1)
    add_session("Mr. J. Okafor", "Library", s, e,
                ["LT-16", "LT-17"], "active", checkout_dt=s + timedelta(minutes=5))

    # --- Today: a session currently in progress --------------------------
    s, e = now - timedelta(minutes=50), now + timedelta(minutes=40)
    add_session("Ms. L. Nguyen", "Science Lab", s, e,
                ["LT-06", "LT-07", "LT-08"], "active", checkout_dt=s + timedelta(minutes=3))

    # --- Today: an upcoming booking (reserved, not yet checked out) ------
    s, e = now + timedelta(hours=2), now + timedelta(hours=3)
    add_session("Mr. R. Ahmed", "Room 102", s, e,
                ["LT-09", "LT-10", "LT-11", "LT-12"], "booked")
