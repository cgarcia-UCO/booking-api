"""
app/routers/bookings.py
-------------------------
- GET /bookings, GET /bookings/{id}: query endpoints. Per the isolation
  model, they only ever expose the seed dataset plus bookings created
  under the requester's own session key (X-Session-Id) — never another
  attendee's bookings.
- POST /bookings: the only creation endpoint in the whole API. Returns a
  clear affirmative/negative response depending on whether the requested
  slot is actually available.
- DELETE /bookings/mine: the only deletion endpoint, scoped to bookings
  created under the requester's own session key (resets that attendee's
  sandbox).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from .. import config, schemas
from ..data_store import BookingConflict, BookingStore, NotFound
from ..deps import Pagination, get_booking_store, paginate, session_key

router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.get("", response_model=schemas.Page[schemas.Booking], summary="List bookings")
def list_bookings(
    booking_type: Optional[schemas.BookingType] = None,
    status: Optional[schemas.BookingStatus] = None,
    customer_id: Optional[int] = None,
    hotel_id: Optional[int] = None,
    room_id: Optional[int] = None,
    restaurant_id: Optional[int] = None,
    table_id: Optional[int] = None,
    activity_id: Optional[int] = None,
    date_from: Optional[date] = Query(None, description="Only bookings with init_day >= this date"),
    date_to: Optional[date] = Query(None, description="Only bookings with init_day <= this date"),
    only_mine: bool = Query(
        False, description="If true, exclude the shared seed dataset and only show bookings you created"
    ),
    pagination: Pagination = Depends(),
    store: BookingStore = Depends(get_booking_store),
    session: str = Depends(session_key),
):
    items = [b for b in store.visible_bookings(session) if not only_mine or b["created_by_session"] == session]
    items = [b for b in items if booking_type is None or b["booking_type"] == booking_type]
    items = [b for b in items if status is None or b["status"] == status]
    items = [b for b in items if customer_id is None or b["customer_id"] == customer_id]
    items = [b for b in items if hotel_id is None or b["hotel_id"] == hotel_id]
    items = [b for b in items if room_id is None or b["room_id"] == room_id]
    items = [b for b in items if restaurant_id is None or b["restaurant_id"] == restaurant_id]
    items = [b for b in items if table_id is None or b["table_id"] == table_id]
    items = [b for b in items if activity_id is None or b["activity_id"] == activity_id]
    items = [b for b in items if date_from is None or b["init_day"] >= date_from]
    items = [b for b in items if date_to is None or b["init_day"] <= date_to]
    items = sorted(items, key=lambda b: b["booking_id"])
    return paginate(items, pagination)


@router.get("/{booking_id}", response_model=schemas.Booking, summary="Get a booking by id")
def get_booking(
    booking_id: int, store: BookingStore = Depends(get_booking_store), session: str = Depends(session_key)
):
    booking = store.get_booking(booking_id, session)
    if booking is None:
        raise HTTPException(status_code=404, detail=f"Booking {booking_id} not found")
    return booking


@router.post(
    "", response_model=schemas.BookingCreateResponse, status_code=201,
    summary="Create a booking (room, table or activity)",
    description=(
        "Creates a booking if, and only if, the requested slot does not "
        "overlap with any booking visible to the requester (the shared seed "
        "dataset plus bookings previously created under the same X-Session-Id). "
        f"Bookings are never accepted for dates after {config.MAX_BOOKING_DATE.isoformat()}."
    ),
)
def create_booking(
    payload: schemas.BookingCreateRequest,
    store: BookingStore = Depends(get_booking_store),
    session: str = Depends(session_key),
):
    try:
        booking = store.create_booking(payload, session)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except BookingConflict as exc:
        return JSONResponse(
            status_code=409,
            content=schemas.BookingCreateResponse(
                success=False, message=str(exc), booking=None
            ).model_dump(mode="json"),
        )
    return schemas.BookingCreateResponse(success=True, message="Booking confirmed.", booking=booking)


@router.delete(
    "/mine", summary="Delete all bookings created under the requester's session key",
    description="Resets this attendee's sandbox: deletes every booking created under the "
                "requesting X-Session-Id. The shared seed dataset is never affected.",
)
def delete_my_bookings(store: BookingStore = Depends(get_booking_store), session: str = Depends(session_key)):
    deleted = store.delete_by_session(session)
    return {"deleted_count": deleted, "session_id": session}
