# 💻 Smart Laptop Tracker

A web-based **IT asset booking & usage-tracking system** that automates a
school's paper-based laptop log. Built with **Python (Flask) + SQLite** and a
zero-build vanilla JS frontend.

> **The problem:** 20 shared laptops are distributed to classrooms and tracked
> on paper — where each laptop is, when it's being used and for how long.
> Paper gets lost, double-bookings happen, and nobody knows which laptops are
> free *right now*.
>
> **The solution:** a live web app where teachers see real-time availability,
> book laptops for a room/time slot, and every checkout/return is logged
> automatically — with conflict prevention, overdue detection and one-click
> CSV reporting.

---

## ✨ Features

### 📊 Live Dashboard
- Real-time status of all 20 laptops: **available / out on loan / reserved / maintenance**
- Live location of every laptop ("where is everything, right now")
- KPI cards: available now, out on loan, reserved today, overdue returns, in maintenance
- Auto-refreshes every 30 seconds

### 🤖 Automation (the point of the project)
- **Smart allocation** — bookings state a quantity; the system assigns specific
  laptops automatically, choosing the *least-used* first to balance fleet wear
- **Conflict prevention** — double-booking a laptop is impossible; availability
  is validated live in the UI and again in the API
- **Automatic usage logging** — one-click checkout/check-in records *who* had
  *which* laptop, *where*, and computes exact session durations
- **Expiry sweep** — bookings never collected expire automatically before
  every request; overdue returns are flagged with live alerts
- **Self-healing allocations** — flagging a laptop for maintenance
  automatically reallocates its future bookings to other free laptops

### 🗓️ Booking
- Teachers pick a room, date, time slot and quantity
- Live availability preview as they type
- Instant confirmation showing which asset tags were allocated

### 🕑 Usage History (the paper log, digitised)
- Full audit trail: laptop, teacher, room, checkout → return, duration
- Fleet analytics: total sessions, total/average usage time, most-used laptops
- **One-click CSV export** for record-keeping

### 🛠️ Fleet Management
- Flag laptops for maintenance (with automatic booking reallocation)
- Move laptops between rooms
- Reset demo data

---

## 🧱 Tech Stack & Architecture

| Layer     | Tech                                             |
|-----------|--------------------------------------------------|
| Backend   | Python 3 · Flask (REST API)                      |
| Database  | SQLite (zero-config, file-based)                 |
| Frontend  | Vanilla HTML/CSS/JS single-page app (no build step) |
| Serving   | Flask serves both the API and the static UI      |

```
Automation-/
├── app.py            # Flask REST API + automation engine
├── database.py       # SQLite schema + demo seed data (dated relative to today)
├── requirements.txt
├── static/
│   ├── index.html    # SPA shell
│   ├── style.css     # dashboard styling
│   └── app.js        # frontend logic (fetch → render, live refresh)
└── laptops.db        # auto-created on first run (git-ignored)
```

## 🚀 Run it locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** — the database and demo data are created
automatically on first run.

## 🌐 Deploying online

Any platform that runs Python works. Example with Render/Railway:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app` (add `gunicorn` to requirements) or `python app.py`
- The `PORT` environment variable is respected automatically.

## 📡 API Reference

| Method | Endpoint                              | Purpose |
|--------|---------------------------------------|---------|
| GET    | `/api/overview`                       | Fleet status, stats, room breakdown |
| GET    | `/api/availability?date&start&end`    | Live slot availability |
| POST   | `/api/bookings`                       | Create booking (auto-allocates laptops) |
| GET    | `/api/bookings`                       | Active/upcoming bookings with action flags |
| POST   | `/api/bookings/<id>/checkout`         | Start session, begin logging |
| POST   | `/api/bookings/<id>/checkin`          | End session, compute durations |
| POST   | `/api/bookings/<id>/cancel`           | Release a reservation |
| GET    | `/api/history`                        | Usage log + fleet analytics |
| GET    | `/api/history.csv`                    | CSV export of the full log |
| POST   | `/api/laptops/<id>/maintenance`       | Maintenance flag (+ auto-reallocation) |
| POST   | `/api/laptops/<id>/move`              | Record a room move |
| POST   | `/api/reset`                          | Reset demo data |

## 🛣️ Future enhancements

- Staff authentication (SSO/PIN) and role-based admin views
- Email/Teams reminders for overdue returns
- QR-code labels on laptops for scan-based checkout
- Weekly usage reports auto-generated per department
- Room-blocking rules (e.g. exam lockdowns)
