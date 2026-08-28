"""
app/routers/availability.py
-----------------------------
Read-only availability checks for the three bookable element types (rooms,
tables, leisure venues). Per the isolation model described in the README,
these checks always consider "seed bookings + bookings created by the
requesting IP" as the set of bookings that can block a slot.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import schemas
from ..data_store import BookingStore, Catalog
from ..deps import client_ip, get_booking_store, get_catalog
from ..schemas import HOUR_RE

router = APIRouter(prefix="/availability", tags=["Availability"])


@router.get(
    "/rooms", response_model=list[schemas.RoomAvailability],
    summary="Check room availability for a date range",
    description=(
        "Returns availability for the rooms matching the given filters over "
        "[init_day, end_day). At least one of hotel_id, room_type_id or "
        "room_id should be given to keep the result set reasonable."
    ),
)
def rooms_availability(
    init_day: date = Query(..., description="Check-in day (inclusive)"),
    end_day: date = Query(..., description="Check-out day (exclusive)"),
    hotel_id: Optional[int] = None,
    room_type_id: Optional[int] = None,
    room_id: Optional[int] = None,
    only_available: bool = Query(False, description="If true, only return rooms that ARE available"),
    catalog: Catalog = Depends(get_catalog),
    store: BookingStore = Depends(get_booking_store),
    ip: str = Depends(client_ip),
):
    if end_day <= init_day:
        raise HTTPException(status_code=400, detail="'end_day' must be after 'init_day'")

    if room_id is not None:
        candidates = [catalog.rooms_by_id[room_id]] if room_id in catalog.rooms_by_id else []
        if not candidates:
            raise HTTPException(status_code=404, detail=f"Room {room_id} not found")
    else:
        candidates = catalog.rooms
        if hotel_id is not None:
            candidates = [r for r in candidates if r["hotel_id"] == hotel_id]
        if room_type_id is not None:
            candidates = [r for r in candidates if r["room_type_id"] == room_type_id]

    results = []
    for room in candidates:
        conflicts = store.room_conflicts(room["room_id"], init_day, end_day, ip)
        available = not conflicts
        if only_available and not available:
            continue
        results.append({
            "room_id": room["room_id"],
            "hotel_id": room["hotel_id"],
            "room_type_id": room["room_type_id"],
            "room_number": room["room_number"],
            "init_day": init_day,
            "end_day": end_day,
            "available": available,
            "conflicting_booking_ids": [c["booking_id"] for c in conflicts],
        })
    return results


@router.get(
    "/tables", response_model=list[schemas.TableAvailability],
    summary="Check table availability for a day and time slot",
    description=(
        "Returns availability for the tables matching the given filters on "
        "a specific day and hour. At least one of restaurant_id or table_id "
        "should be given to keep the result set reasonable."
    ),
)
def tables_availability(
    day: date = Query(..., description="Reservation day"),
    hour: str = Query(..., description="24h time, format HH:MM, e.g. '20:30'"),
    restaurant_id: Optional[int] = None,
    table_id: Optional[int] = None,
    min_capacity: Optional[int] = Query(None, description="Only return tables that seat at least this many people"),
    only_available: bool = Query(False, description="If true, only return tables that ARE available"),
    catalog: Catalog = Depends(get_catalog),
    store: BookingStore = Depends(get_booking_store),
    ip: str = Depends(client_ip),
):
    if not HOUR_RE.match(hour):
        raise HTTPException(status_code=400, detail="'hour' must match 24h format HH:MM, e.g. '20:30'")

    if table_id is not None:
        candidates = [catalog.tables_by_id[table_id]] if table_id in catalog.tables_by_id else []
        if not candidates:
            raise HTTPException(status_code=404, detail=f"Table {table_id} not found")
    else:
        candidates = catalog.tables
        if restaurant_id is not None:
            candidates = [t for t in candidates if t["restaurant_id"] == restaurant_id]
        if min_capacity is not None:
            candidates = [t for t in candidates if t["capacity"] >= min_capacity]

    results = []
    for table in candidates:
        conflicts = store.table_conflicts(table["table_id"], day, hour, ip)
        available = not conflicts
        if only_available and not available:
            continue
        results.append({
            "table_id": table["table_id"],
            "restaurant_id": table["restaurant_id"],
            "table_number": table["table_number"],
            "capacity": table["capacity"],
            "day": day,
            "hour": hour,
            "available": available,
            "conflicting_booking_ids": [c["booking_id"] for c in conflicts],
        })
    return results


@router.get(
    "/activities", response_model=list[schemas.ActivityAvailability],
    summary="Check leisure venue capacity for a day",
)
def activities_availability(
    day: date = Query(..., description="Visit day"),
    activity_id: Optional[int] = None,
    num_people: Optional[int] = Query(None, ge=1, description="Check whether a group of this size still fits"),
    only_available: bool = Query(False, description="If true and num_people is set, only return venues that fit the group"),
    catalog: Catalog = Depends(get_catalog),
    store: BookingStore = Depends(get_booking_store),
    ip: str = Depends(client_ip),
):
    if activity_id is not None:
        candidates = [catalog.activities_by_id[activity_id]] if activity_id in catalog.activities_by_id else []
        if not candidates:
            raise HTTPException(status_code=404, detail=f"Activity {activity_id} not found")
    else:
        candidates = catalog.activities

    results = []
    for activity in candidates:
        booked = store.activity_booked_count(activity["activity_id"], day, ip)
        remaining = activity["max_capacity"] - booked
        if num_people is not None:
            available = remaining >= num_people
        else:
            available = remaining > 0
        if only_available and not available:
            continue
        results.append({
            "activity_id": activity["activity_id"],
            "day": day,
            "max_capacity": activity["max_capacity"],
            "booked_count": booked,
            "remaining_capacity": remaining,
            "requested_people": num_people,
            "available": available,
        })
    return results
