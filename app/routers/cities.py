from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import schemas
from ..data_store import Catalog
from ..deps import Pagination, get_catalog, paginate
from ..filtering import contains_ci

router = APIRouter(prefix="/cities", tags=["Cities"])


@router.get("", response_model=schemas.Page[schemas.City], summary="List cities")
def list_cities(
    name: Optional[str] = Query(None, description="Case-insensitive substring match on the city name"),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = [c for c in catalog.cities if contains_ci(c["name"], name)]
    return paginate(items, pagination)


@router.get("/{city_id}", response_model=schemas.City, summary="Get a city by id")
def get_city(city_id: int, catalog: Catalog = Depends(get_catalog)):
    for c in catalog.cities:
        if c["city_id"] == city_id:
            return c
    raise HTTPException(status_code=404, detail=f"City {city_id} not found")
