from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import schemas
from ..data_store import Catalog
from ..deps import Pagination, get_catalog, paginate
from ..filtering import contains_ci, eq_ci, has_all

router = APIRouter(tags=["Hotels"])


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------
@router.get("/hotels", response_model=schemas.Page[schemas.Hotel], summary="List hotels")
def list_hotels(
    city: Optional[str] = Query(None, description="Case-insensitive substring match"),
    type: Optional[str] = Query(None, description="hotel, resort, aparthotel, hostel, boutique, rural"),
    category: Optional[int] = Query(None, ge=1, le=5, description="Exact star category"),
    min_category: Optional[int] = Query(None, ge=1, le=5),
    price_range: Optional[str] = Query(None, description="budget, mid-range, upscale, luxury"),
    min_rating: Optional[float] = Query(None, ge=1, le=5),
    pet_friendly: Optional[bool] = None,
    accessible: Optional[bool] = None,
    reception_24h: Optional[bool] = None,
    services: Optional[str] = Query(None, description="Comma-separated; hotel must offer ALL of these"),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.hotels
    items = [h for h in items if contains_ci(h["city"], city)]
    items = [h for h in items if eq_ci(h["type"], type)]
    items = [h for h in items if category is None or h["category"] == category]
    items = [h for h in items if min_category is None or h["category"] >= min_category]
    items = [h for h in items if eq_ci(h["price_range"], price_range)]
    items = [h for h in items if min_rating is None or h["rating"] >= min_rating]
    items = [h for h in items if pet_friendly is None or h["pet_friendly"] == pet_friendly]
    items = [h for h in items if accessible is None or h["accessible"] == accessible]
    items = [h for h in items if reception_24h is None or h["reception_24h"] == reception_24h]
    items = [h for h in items if has_all(h["services"], services)]
    return paginate(items, pagination)


@router.get("/hotels/{hotel_id}", response_model=schemas.Hotel, summary="Get a hotel by id")
def get_hotel(hotel_id: int, catalog: Catalog = Depends(get_catalog)):
    hotel = catalog.hotels_by_id.get(hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail=f"Hotel {hotel_id} not found")
    return hotel


# ---------------------------------------------------------------------------
# Room types
# ---------------------------------------------------------------------------
@router.get("/room_types", response_model=schemas.Page[schemas.RoomType], summary="List room types")
def list_room_types(
    hotel_id: Optional[int] = None,
    name: Optional[str] = Query(None, description="single, double, twin, triple, family, suite, junior suite"),
    min_adults: Optional[int] = Query(None, description="Room must accommodate at least this many adults"),
    min_children: Optional[int] = None,
    breakfast_included: Optional[bool] = None,
    accessible: Optional[bool] = None,
    bathroom_type: Optional[str] = Query(None, description="private or shared"),
    max_price: Optional[float] = Query(None, description="Maximum base_price_per_night"),
    services: Optional[str] = Query(None, description="Comma-separated; room must offer ALL of these"),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.room_types
    items = [r for r in items if hotel_id is None or r["hotel_id"] == hotel_id]
    items = [r for r in items if eq_ci(r["name"], name)]
    items = [r for r in items if min_adults is None or r["max_adults"] >= min_adults]
    items = [r for r in items if min_children is None or r["max_children"] >= min_children]
    items = [r for r in items if breakfast_included is None or r["breakfast_included"] == breakfast_included]
    items = [r for r in items if accessible is None or r["accessible"] == accessible]
    items = [r for r in items if eq_ci(r["bathroom_type"], bathroom_type)]
    items = [r for r in items if max_price is None or r["base_price_per_night"] <= max_price]
    items = [r for r in items if has_all(r["services"], services)]
    return paginate(items, pagination)


@router.get("/room_types/{room_type_id}", response_model=schemas.RoomType, summary="Get a room type by id")
def get_room_type(room_type_id: int, catalog: Catalog = Depends(get_catalog)):
    room_type = catalog.room_types_by_id.get(room_type_id)
    if room_type is None:
        raise HTTPException(status_code=404, detail=f"Room type {room_type_id} not found")
    return room_type


@router.get(
    "/hotels/{hotel_id}/room_types", response_model=schemas.Page[schemas.RoomType],
    summary="List room types for a hotel",
)
def list_room_types_for_hotel(
    hotel_id: int, pagination: Pagination = Depends(), catalog: Catalog = Depends(get_catalog),
):
    if hotel_id not in catalog.hotels_by_id:
        raise HTTPException(status_code=404, detail=f"Hotel {hotel_id} not found")
    items = catalog.room_types_by_hotel.get(hotel_id, [])
    return paginate(items, pagination)


# ---------------------------------------------------------------------------
# Physical rooms
# ---------------------------------------------------------------------------
@router.get("/rooms", response_model=schemas.Page[schemas.Room], summary="List physical rooms")
def list_rooms(
    hotel_id: Optional[int] = None,
    room_type_id: Optional[int] = None,
    status: Optional[str] = Query(None, description="available, occupied, maintenance, cleaning, blocked"),
    floor: Optional[int] = None,
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.rooms
    items = [r for r in items if hotel_id is None or r["hotel_id"] == hotel_id]
    items = [r for r in items if room_type_id is None or r["room_type_id"] == room_type_id]
    items = [r for r in items if eq_ci(r["status"], status)]
    items = [r for r in items if floor is None or r["floor"] == floor]
    return paginate(items, pagination)


@router.get("/rooms/{room_id}", response_model=schemas.Room, summary="Get a physical room by id")
def get_room(room_id: int, catalog: Catalog = Depends(get_catalog)):
    room = catalog.rooms_by_id.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found")
    return room


@router.get(
    "/hotels/{hotel_id}/rooms", response_model=schemas.Page[schemas.Room],
    summary="List physical rooms for a hotel",
)
def list_rooms_for_hotel(
    hotel_id: int, pagination: Pagination = Depends(), catalog: Catalog = Depends(get_catalog),
):
    if hotel_id not in catalog.hotels_by_id:
        raise HTTPException(status_code=404, detail=f"Hotel {hotel_id} not found")
    items = catalog.rooms_by_hotel.get(hotel_id, [])
    return paginate(items, pagination)
