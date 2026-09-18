"""Smart Laptop Tracker — Flask REST API + static frontend.

Replaces a paper-based laptop log for a school IT department:

  * Teachers book laptops for a room/time slot; the system AUTOMATICALLY
    allocates specific laptops (least-used first, to even out wear) and
    prevents double-booking.
  * Check-out / check-in AUTOMATICALLY logs who used which laptop, where,
    and for exactly how long — no more paper timesheets.
  * A sweep runs before every API call to AUTOMATICALLY expire bookings
    that were never collected, and overdue returns are flagged live.
  * Marking a laptop for maintenance AUTOMATICALLY reallocates its future
    bookings to other free laptops.

Run locally:  python app.py        (serves UI + API on port 5000)
"""

import csv
import io
import os
from datetime import datetime, timedelta

from flask import Flask, Response, g, jsonify, request, send_from_directory

import database as db

app = Flask(__name__, static_folder="static", static_url_path="")

CHECKOUT_EARLY_MINUTES = 15   # how early a booking may be collected
FMT_DT = "%Y-%m-%d %H:%M"
FMT_TS = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_conn():
    if "conn" not in g:
        g.conn = db.get_db()
    return g.conn


@app.teardown_appcontext
def close_conn(_exc):
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


def parse_dt(day, hhmm):
    return datetime.strptime(f"{day} {hhmm}", FMT_DT)


def err(message, code=400):
    return jsonify({"error": message}), code


def rows(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# Automation 1 — expiry sweep (runs before every API request)
# ---------------------------------------------------------------------------

@app.before_request
def automation_sweep():
    if not request.path.startswith("/api/"):
        return
    conn = get_conn()
    now = datetime.now()
    stale = rows(conn, "SELECT id, date, end_time FROM bookings WHERE status='booked'")
    for b in stale:
        if now > parse_dt(b["date"], b["end_time"]):
            # Slot has ended and the laptops were never collected.
            conn.execute("UPDATE bookings SET status='expired' WHERE id=?", (b["id"],))
    conn.commit()


# ---------------------------------------------------------------------------
# Automation 2 — availability engine + smart (least-used-first) allocation
# ---------------------------------------------------------------------------

def available_laptops(conn, day, start, end, exclude_ids=()):
    """Laptops free for a slot, ranked least-used first to balance wear."""
    sql = """
        SELECT l.id, l.asset_tag, l.model,
               COALESCE(SUM(u.duration_minutes), 0) AS used_minutes
        FROM laptops l
        LEFT JOIN usage_logs u ON u.laptop_id = l.id
        WHERE l.status NOT IN ('maintenance', 'in-use')
          AND l.id NOT IN (
              SELECT bl.laptop_id FROM booking_laptops bl
              JOIN bookings b ON b.id = bl.booking_id
              WHERE b.date = ? AND b.status IN ('booked', 'active')
                AND NOT (b.end_time <= ? OR b.start_time >= ?)
          )
    """
    params = [day, start, end]
    if exclude_ids:
        sql += f" AND l.id NOT IN ({','.join('?' * len(exclude_ids))})"
        params.extend(exclude_ids)
    sql += " GROUP BY l.id ORDER BY used_minutes ASC, l.id ASC"
    return rows(conn, sql, params)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def booking_dict(conn, b):
    now = datetime.now()
    tags = [
        r["asset_tag"] for r in rows(
            conn,
            """SELECT l.asset_tag FROM booking_laptops bl
               JOIN laptops l ON l.id = bl.laptop_id
               WHERE bl.booking_id = ? ORDER BY l.asset_tag""",
            (b["id"],),
        )
    ]
    start_dt = parse_dt(b["date"], b["start_time"])
    end_dt = parse_dt(b["date"], b["end_time"])
    d = dict(b)
    d["laptops"] = tags
    d["overdue"] = b["status"] == "active" and now > end_dt
    d["can_checkout"] = (
        b["status"] == "booked"
        and start_dt - timedelta(minutes=CHECKOUT_EARLY_MINUTES) <= now <= end_dt
    )
    d["can_checkin"] = b["status"] == "active"
    d["can_cancel"] = b["status"] == "booked"
    d["finished"] = b["status"] in ("completed", "cancelled", "expired")
    return d


def laptop_dict(conn, l, today, now_hhmm):
    d = dict(l)
    nxt = conn.execute(
        """SELECT b.start_time, b.end_time, b.teacher, b.room, b.status AS bstatus
           FROM booking_laptops bl JOIN bookings b ON b.id = bl.booking_id
           WHERE bl.laptop_id = ? AND b.date = ?
             AND b.status IN ('booked', 'active') AND b.end_time >= ?
           ORDER BY b.start_time LIMIT 1""",
        (l["id"], today, now_hhmm),
    ).fetchone()
    d["next_booking"] = dict(nxt) if nxt else None
    if l["status"] == "in-use":
        sess = conn.execute(
            """SELECT teacher, checkout_at, room FROM usage_logs
               WHERE laptop_id = ? AND checkin_at IS NULL
               ORDER BY id DESC LIMIT 1""",
            (l["id"],),
        ).fetchone()
        d["current_session"] = dict(sess) if sess else None
    return d


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---------------------------------------------------------------------------
# API — config / overview / availability
# ---------------------------------------------------------------------------

@app.get("/api/config")
def config():
    return jsonify({
        "rooms": db.ROOMS,
        "teachers": db.TEACHERS,
        "server_time": datetime.now().strftime(FMT_TS),
        "checkout_early_minutes": CHECKOUT_EARLY_MINUTES,
    })


@app.get("/api/overview")
def overview():
    conn = get_conn()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H:%M")

    laptops = [
        laptop_dict(conn, l, today, hhmm)
        for l in rows(conn, "SELECT * FROM laptops ORDER BY asset_tag")
    ]
    stats = {
        "total": len(laptops),
        "available": sum(1 for l in laptops if l["status"] == "available"),
        "in_use": sum(1 for l in laptops if l["status"] == "in-use"),
        "maintenance": sum(1 for l in laptops if l["status"] == "maintenance"),
        "reserved_today": conn.execute(
            """SELECT COUNT(DISTINCT bl.laptop_id) FROM booking_laptops bl
               JOIN bookings b ON b.id = bl.booking_id
               WHERE b.date = ? AND b.status = 'booked'""",
            (today,),
        ).fetchone()[0],
        "active_overdue": conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE status='active' AND (date < ? OR (date = ? AND end_time < ?))",
            (today, today, hhmm),
        ).fetchone()[0],
    }
    rooms = rows(conn, """
        SELECT current_room AS room, COUNT(*) AS count
        FROM laptops GROUP BY current_room ORDER BY count DESC, room
    """)
    return jsonify({"stats": stats, "laptops": laptops,
                    "rooms": [dict(r) for r in rooms],
                    "server_time": now.strftime(FMT_TS)})


@app.get("/api/availability")
def availability():
    day = request.args.get("date", "")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    try:
        parse_dt(day, start)
        parse_dt(day, end)
    except ValueError:
        return err("Provide date, start and end in HH:MM format.")
    if start >= end:
        return err("End time must be after start time.")
    free = available_laptops(get_conn(), day, start, end)
    return jsonify({"count": len(free),
                    "laptops": [{"asset_tag": f["asset_tag"], "model": f["model"]} for f in free]})


# ---------------------------------------------------------------------------
# API — bookings
# ---------------------------------------------------------------------------

@app.get("/api/bookings")
def list_bookings():
    conn = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")
    # Everything live, plus anything finished *today* (keeps the list short).
    bs = rows(conn, """
        SELECT * FROM bookings
        WHERE status IN ('booked', 'active') OR date = ?
        ORDER BY date, start_time
    """, (today,))
    return jsonify({"bookings": [booking_dict(conn, b) for b in bs]})


@app.post("/api/bookings")
def create_booking():
    conn = get_conn()
    data = request.get_json(silent=True) or {}
    teacher = str(data.get("teacher") or "").strip()
    room = str(data.get("room") or "").strip()
    day = str(data.get("date") or "").strip()
    start = str(data.get("start_time") or "").strip()
    end = str(data.get("end_time") or "").strip()

    # --- validation -------------------------------------------------------
    if len(teacher) < 2:
        return err("Please enter the teacher's name.")
    if room not in db.ROOMS:
        return err("Please choose a valid room.")
    try:
        qty = int(data.get("quantity"))
        if not 1 <= qty <= 20:
            raise ValueError
    except (TypeError, ValueError):
        return err("Quantity must be between 1 and 20.")
    try:
        start_dt, end_dt = parse_dt(day, start), parse_dt(day, end)
    except ValueError:
        return err("Invalid date or time format.")
    if end_dt <= start_dt:
        return err("End time must be after start time.")
    if day < datetime.now().strftime("%Y-%m-%d"):
        return err("Bookings cannot be made in the past.")

    # --- automation: conflict check + smart allocation --------------------
    free = available_laptops(conn, day, start, end)
    if len(free) < qty:
        return err(
            f"Only {len(free)} laptop(s) are free for that slot — "
            "try a different time or fewer laptops.", 409)

    picked = free[:qty]
    cur = conn.execute(
        "INSERT INTO bookings (teacher, room, date, start_time, end_time,"
        " quantity, status, created_at) VALUES (?,?,?,?,?,?, 'booked', ?)",
        (teacher, room, day, start, end, qty, datetime.now().strftime(FMT_TS)),
    )
    bid = cur.lastrowid
    for lap in picked:
        conn.execute(
            "INSERT INTO booking_laptops (booking_id, laptop_id) VALUES (?,?)",
            (bid, lap["id"]),
        )
    conn.commit()
    b = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
    return jsonify({"booking": booking_dict(conn, b)}), 201


def _get_booking(conn, bid):
    b = conn.execute("SELECT * FROM bookings WHERE id = ?", (bid,)).fetchone()
    return b


@app.post("/api/bookings/<int:bid>/checkout")
def checkout(bid):
    conn = get_conn()
    b = _get_booking(conn, bid)
    if not b:
        return err("Booking not found.", 404)
    if b["status"] != "booked":
        return err(f"This booking is already {b['status']}.")
    now = datetime.now()
    start_dt, end_dt = parse_dt(b["date"], b["start_time"]), parse_dt(b["date"], b["end_time"])
    if now < start_dt - timedelta(minutes=CHECKOUT_EARLY_MINUTES):
        return err(f"Too early — laptops can be collected from "
                   f"{(start_dt - timedelta(minutes=CHECKOUT_EARLY_MINUTES)).strftime('%H:%M')}.")
    if now > end_dt:
        return err("This booking's time slot has already ended.")

    laps = rows(conn, """
        SELECT l.* FROM booking_laptops bl JOIN laptops l ON l.id = bl.laptop_id
        WHERE bl.booking_id = ?
    """, (bid,))
    blocked = [l["asset_tag"] for l in laps if l["status"] != "available"]
    if blocked:
        return err("Cannot check out: " + ", ".join(blocked) +
                   " not available (maintenance or in use elsewhere).", 409)

    # Automation: one click logs every laptop out with a timestamp.
    for l in laps:
        conn.execute("UPDATE laptops SET status='in-use', current_room=? WHERE id=?",
                     (b["room"], l["id"]))
        conn.execute(
            "INSERT INTO usage_logs (booking_id, laptop_id, teacher, room, checkout_at)"
            " VALUES (?,?,?,?,?)",
            (bid, l["id"], b["teacher"], b["room"], now.strftime(FMT_TS)),
        )
    conn.execute("UPDATE bookings SET status='active' WHERE id=?", (bid,))
    conn.commit()
    return jsonify({"booking": booking_dict(conn, _get_booking(conn, bid))})


@app.post("/api/bookings/<int:bid>/checkin")
def checkin(bid):
    conn = get_conn()
    b = _get_booking(conn, bid)
    if not b:
        return err("Booking not found.", 404)
    if b["status"] != "active":
        return err("Only an active session can be checked in.")
    now = datetime.now()
    # Automation: one click returns every laptop and computes exact durations.
    logs = rows(conn,
                "SELECT * FROM usage_logs WHERE booking_id = ? AND checkin_at IS NULL",
                (bid,))
    for log in logs:
        out = datetime.strptime(log["checkout_at"], FMT_TS)
        dur = max(1, int((now - out).total_seconds() // 60))
        conn.execute("UPDATE usage_logs SET checkin_at=?, duration_minutes=? WHERE id=?",
                     (now.strftime(FMT_TS), dur, log["id"]))
        conn.execute("UPDATE laptops SET status='available' WHERE id=?",
                     (log["laptop_id"],))
    conn.execute("UPDATE bookings SET status='completed' WHERE id=?", (bid,))
    conn.commit()
    return jsonify({"booking": booking_dict(conn, _get_booking(conn, bid))})


@app.post("/api/bookings/<int:bid>/cancel")
def cancel(bid):
    conn = get_conn()
    b = _get_booking(conn, bid)
    if not b:
        return err("Booking not found.", 404)
    if b["status"] != "booked":
        return err("Only upcoming bookings can be cancelled.")
    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
    conn.commit()
    return jsonify({"booking": booking_dict(conn, _get_booking(conn, bid))})


# ---------------------------------------------------------------------------
# API — history, reports, CSV export
# ---------------------------------------------------------------------------

LOG_QUERY = """
    SELECT u.*, l.asset_tag FROM usage_logs u
    JOIN laptops l ON l.id = u.laptop_id
    ORDER BY u.checkout_at DESC
"""


@app.get("/api/history")
def history():
    conn = get_conn()
    logs = [dict(r) for r in rows(conn, LOG_QUERY + " LIMIT 500")]
    s = conn.execute(
        "SELECT COUNT(*) AS sessions, COALESCE(SUM(duration_minutes),0) AS minutes"
        " FROM usage_logs WHERE duration_minutes IS NOT NULL"
    ).fetchone()
    top = [dict(r) for r in rows(conn, """
        SELECT l.asset_tag, COUNT(*) AS sessions,
               COALESCE(SUM(u.duration_minutes),0) AS minutes
        FROM usage_logs u JOIN laptops l ON l.id = u.laptop_id
        GROUP BY l.id ORDER BY minutes DESC, l.asset_tag LIMIT 6
    """)]
    sessions, minutes = s["sessions"], s["minutes"]
    return jsonify({
        "logs": logs,
        "summary": {
            "sessions": sessions,
            "minutes": minutes,
            "avg_minutes": round(minutes / sessions) if sessions else 0,
            "top": top,
        },
    })


@app.get("/api/history.csv")
def history_csv():
    """One-click export of the full usage log (the old paper book, digitised)."""
    conn = get_conn()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Laptop", "Teacher", "Room", "Checked out", "Checked in",
                "Duration (minutes)"])
    for r in rows(conn, LOG_QUERY):
        w.writerow([r["asset_tag"], r["teacher"], r["room"], r["checkout_at"],
                    r["checkin_at"] or "", r["duration_minutes"] or ""])
    return Response(out.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=laptop_usage_log.csv"
    })


# ---------------------------------------------------------------------------
# API — fleet management (maintenance / moves / reset)
# ---------------------------------------------------------------------------

def reallocate_future_bookings(conn, laptop_id):
    """Automation 3: a laptop entering maintenance has its future bookings
    automatically moved onto other free laptops."""
    now = datetime.now()
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    affected = rows(conn, """
        SELECT b.* FROM bookings b
        JOIN booking_laptops bl ON bl.booking_id = b.id
        WHERE bl.laptop_id = ? AND b.status = 'booked'
          AND (b.date > ? OR (b.date = ? AND b.end_time > ?))
    """, (laptop_id, today, today, hhmm))

    messages = []
    tag = conn.execute("SELECT asset_tag FROM laptops WHERE id=?",
                       (laptop_id,)).fetchone()["asset_tag"]
    for b in affected:
        others = [r["laptop_id"] for r in rows(
            conn, "SELECT laptop_id FROM booking_laptops WHERE booking_id=? AND laptop_id != ?",
            (b["id"], laptop_id))]
        candidates = available_laptops(conn, b["date"], b["start_time"], b["end_time"],
                                       exclude_ids=others)
        label = f"{b['teacher']} ({b['date'] == today and 'today' or b['date']} {b['start_time']}–{b['end_time']})"
        if candidates:
            new = candidates[0]
            conn.execute(
                "UPDATE booking_laptops SET laptop_id=? WHERE booking_id=? AND laptop_id=?",
                (new["id"], b["id"], laptop_id))
            messages.append(f"{tag} → {new['asset_tag']} for {label}")
        else:
            messages.append(f"⚠ No replacement found for {label} — please review.")
    return messages


@app.post("/api/laptops/<int:lid>/maintenance")
def set_maintenance(lid):
    conn = get_conn()
    l = conn.execute("SELECT * FROM laptops WHERE id=?", (lid,)).fetchone()
    if not l:
        return err("Laptop not found.", 404)
    data = request.get_json(silent=True) or {}
    on = bool(data.get("on"))
    notes = str(data.get("notes") or "").strip()
    if on and l["status"] == "in-use":
        return err("This laptop is currently checked out — wait for it to be returned.")
    messages = []
    if on:
        conn.execute("UPDATE laptops SET status='maintenance', notes=? WHERE id=?",
                     (notes or "Under maintenance", lid))
        messages = reallocate_future_bookings(conn, lid)
    else:
        conn.execute("UPDATE laptops SET status='available', notes='' WHERE id=?", (lid,))
    conn.commit()
    return jsonify({"ok": True, "messages": messages})


@app.post("/api/laptops/<int:lid>/move")
def move_laptop(lid):
    conn = get_conn()
    l = conn.execute("SELECT * FROM laptops WHERE id=?", (lid,)).fetchone()
    if not l:
        return err("Laptop not found.", 404)
    room = str((request.get_json(silent=True) or {}).get("room") or "").strip()
    if room not in db.ROOMS:
        return err("Unknown room.")
    if l["status"] == "in-use":
        return err("This laptop is checked out — its location updates automatically on return.")
    conn.execute("UPDATE laptops SET current_room=? WHERE id=?", (room, lid))
    conn.commit()
    return jsonify({"ok": True})


@app.post("/api/reset")
def reset():
    """Wipe and re-seed demo data (dated relative to today)."""
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()
    db.reset_db()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
