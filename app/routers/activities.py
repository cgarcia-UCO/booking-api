from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import schemas
from ..data_store import Catalog
from ..deps import Pagination, get_catalog, paginate
from ..filtering import contains_ci, eq_ci, has_all

router = APIRouter(prefix="/activities", tags=["Leisure venues"])


@router.get("", response_model=schemas.Page[schemas.Activity], summary="List leisure venues")
def list_activities(
    city: Optional[str] = Query(None, description="Case-insensitive substring match"),
    activity_type: Optional[str] = Query(
        None,
        description="theme_park, water_park, zoo, aquarium, museum, cinema, theatre, "
                    "escape_room, guided_tour, concert",
    ),
    category: Optional[str] = Query(None, description="Case-insensitive substring match on the theme/sub-category"),
    indoor_outdoor: Optional[str] = Query(None, description="indoor, outdoor, mixed"),
    accessible: Optional[bool] = None,
    min_rating: Optional[float] = Query(None, ge=1, le=5),
    max_price: Optional[float] = None,
    suitable_for_age: Optional[int] = Query(
        None, ge=0, description="Only return venues whose recommended minimum age is <= this value"
    ),
    services: Optional[str] = Query(None, description="Comma-separated; venue must offer ALL of these"),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.activities
    items = [a for a in items if contains_ci(a["city"], city)]
    items = [a for a in items if eq_ci(a["activity_type"], activity_type)]
    items = [a for a in items if contains_ci(a["category"], category)]
    items = [a for a in items if eq_ci(a["indoor_outdoor"], indoor_outdoor)]
    items = [a for a in items if accessible is None or a["accessible"] == accessible]
    items = [a for a in items if min_rating is None or a["rating"] >= min_rating]
    items = [a for a in items if max_price is None or a["price"] <= max_price]
    items = [a for a in items if suitable_for_age is None or a["min_age"] <= suitable_for_age]
    items = [a for a in items if has_all(a["services"], services)]
    return paginate(items, pagination)


@router.get("/{activity_id}", response_model=schemas.Activity, summary="Get a leisure venue by id")
def get_activity(activity_id: int, catalog: Catalog = Depends(get_catalog)):
    activity = catalog.activities_by_id.get(activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail=f"Activity {activity_id} not found")
    return activity
