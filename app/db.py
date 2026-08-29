"""
app/db.py
----------
Lightweight SQLite persistence for the bookings created live through the
API ("dynamic" bookings, as opposed to the ones that ship in the seed
CSV dataset). This means a process restart on Railway does not wipe out
bookings made during the workshop.

Only the standard library is used (`sqlite3`), so no extra dependency is
required.

NOTE: the `created_by_session` column used to be `created_by_ip` (from the
original per-IP isolation model). If you're upgrading an existing
deployment, delete the old storage/dynamic_bookings.sqlite3 file (or point
STORAGE_DIR at a fresh path) so the new schema is created cleanly — the
two models aren't meant to be merged.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    booking_id INTEGER PRIMARY KEY,
    booking_reference TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    booking_type TEXT NOT NULL,
    status TEXT NOT NULL,
    hotel_id INTEGER,
    room_id INTEGER,
    restaurant_id INTEGER,
    table_id INTEGER,
    activity_id INTEGER,
    init_day TEXT NOT NULL,
    end_day TEXT NOT NULL,
    hour TEXT,
    num_people INTEGER NOT NULL,
    total_price REAL NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by_session TEXT NOT NULL
);
"""

_connection: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        db_path: Path = config.DYNAMIC_BOOKINGS_DB
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI runs sync route/dependency code in
        # a thread pool, and all access is already serialized by the
        # BookingStore's own lock (see data_store.py).
        _connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute(_SCHEMA)
        _connection.commit()
    return _connection


def load_all_bookings() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM bookings ORDER BY booking_id ASC").fetchall()
    return [_row_to_booking(row) for row in rows]


def insert_booking(booking: dict) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO bookings (
            booking_id, booking_reference, customer_id, booking_type, status,
            hotel_id, room_id, restaurant_id, table_id, activity_id,
            init_day, end_day, hour, num_people, total_price, currency,
            created_at, created_by_session
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            booking["booking_id"], booking["booking_reference"], booking["customer_id"],
            booking["booking_type"], booking["status"],
            booking["hotel_id"], booking["room_id"], booking["restaurant_id"],
            booking["table_id"], booking["activity_id"],
            booking["init_day"].isoformat(), booking["end_day"].isoformat(), booking["hour"],
            booking["num_people"], booking["total_price"], booking["currency"],
            booking["created_at"].isoformat(sep=" "), booking["created_by_session"],
        ),
    )
    conn.commit()


def delete_bookings_by_session(session_key: str) -> int:
    conn = get_connection()
    cur = conn.execute("DELETE FROM bookings WHERE created_by_session = ?", (session_key,))
    conn.commit()
    return cur.rowcount


def max_booking_id() -> int:
    conn = get_connection()
    row = conn.execute("SELECT MAX(booking_id) AS m FROM bookings").fetchone()
    return row["m"] or 0


def _row_to_booking(row: sqlite3.Row) -> dict:
    return {
        "booking_id": row["booking_id"],
        "booking_reference": row["booking_reference"],
        "customer_id": row["customer_id"],
        "booking_type": row["booking_type"],
        "status": row["status"],
        "hotel_id": row["hotel_id"],
        "room_id": row["room_id"],
        "restaurant_id": row["restaurant_id"],
        "table_id": row["table_id"],
        "activity_id": row["activity_id"],
        "init_day": date.fromisoformat(row["init_day"]),
        "end_day": date.fromisoformat(row["end_day"]),
        "hour": row["hour"],
        "num_people": row["num_people"],
        "total_price": row["total_price"],
        "currency": row["currency"],
        "created_at": datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S"),
        "created_by_session": row["created_by_session"],
    }
