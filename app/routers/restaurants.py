from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import schemas
from ..data_store import Catalog
from ..deps import Pagination, get_catalog, paginate
from ..filtering import contains_ci, eq_ci, has_all, has_any, parse_csv_param

router = APIRouter(tags=["Restaurants"])


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------
@router.get("/restaurants", response_model=schemas.Page[schemas.Restaurant], summary="List restaurants")
def list_restaurants(
    city: Optional[str] = Query(None, description="Case-insensitive substring match"),
    cuisine_type: Optional[str] = Query(
        None, description="Comma-separated; restaurant must offer AT LEAST ONE of these cuisines"
    ),
    price_range: Optional[str] = Query(None, description="budget, mid-range, upscale, luxury"),
    dress_code: Optional[str] = Query(None, description="casual, smart casual, formal"),
    min_rating: Optional[float] = Query(None, ge=1, le=5),
    accessible: Optional[bool] = None,
    pet_friendly: Optional[bool] = None,
    services: Optional[str] = Query(None, description="Comma-separated; restaurant must offer ALL of these"),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.restaurants
    items = [r for r in items if contains_ci(r["city"], city)]
    items = [r for r in items if has_any(r["cuisine_types"], cuisine_type)]
    items = [r for r in items if eq_ci(r["price_range"], price_range)]
    items = [r for r in items if eq_ci(r["dress_code"], dress_code)]
    items = [r for r in items if min_rating is None or r["rating"] >= min_rating]
    items = [r for r in items if accessible is None or r["accessible"] == accessible]
    items = [r for r in items if pet_friendly is None or r["pet_friendly"] == pet_friendly]
    items = [r for r in items if has_all(r["services"], services)]
    return paginate(items, pagination)


@router.get("/restaurants/{restaurant_id}", response_model=schemas.Restaurant, summary="Get a restaurant by id")
def get_restaurant(restaurant_id: int, catalog: Catalog = Depends(get_catalog)):
    restaurant = catalog.restaurants_by_id.get(restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")
    return restaurant


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
@router.get("/tables", response_model=schemas.Page[schemas.RestaurantTable], summary="List restaurant tables")
def list_tables(
    restaurant_id: Optional[int] = None,
    location: Optional[str] = Query(None, description="indoor, terrace, bar, private room"),
    min_capacity: Optional[int] = None,
    status: Optional[str] = Query(None, description="available, reserved, occupied, unavailable"),
    accessible: Optional[bool] = None,
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.tables
    items = [t for t in items if restaurant_id is None or t["restaurant_id"] == restaurant_id]
    items = [t for t in items if eq_ci(t["location"], location)]
    items = [t for t in items if min_capacity is None or t["capacity"] >= min_capacity]
    items = [t for t in items if eq_ci(t["status"], status)]
    items = [t for t in items if accessible is None or t["accessible"] == accessible]
    return paginate(items, pagination)


@router.get("/tables/{table_id}", response_model=schemas.RestaurantTable, summary="Get a table by id")
def get_table(table_id: int, catalog: Catalog = Depends(get_catalog)):
    table = catalog.tables_by_id.get(table_id)
    if table is None:
        raise HTTPException(status_code=404, detail=f"Table {table_id} not found")
    return table


@router.get(
    "/restaurants/{restaurant_id}/tables", response_model=schemas.Page[schemas.RestaurantTable],
    summary="List tables for a restaurant",
)
def list_tables_for_restaurant(
    restaurant_id: int, pagination: Pagination = Depends(), catalog: Catalog = Depends(get_catalog),
):
    if restaurant_id not in catalog.restaurants_by_id:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")
    items = catalog.tables_by_restaurant.get(restaurant_id, [])
    return paginate(items, pagination)


# ---------------------------------------------------------------------------
# Dishes
# ---------------------------------------------------------------------------
@router.get("/dishes", response_model=schemas.Page[schemas.Dish], summary="List dishes")
def list_dishes(
    restaurant_id: Optional[int] = None,
    category: Optional[str] = Query(None, description="starter, main, dessert, drink, small plate"),
    max_price: Optional[float] = None,
    available: Optional[bool] = None,
    dietary_tags: Optional[str] = Query(None, description="Comma-separated; dish must have ALL of these tags"),
    exclude_allergens: Optional[str] = Query(
        None, description="Comma-separated; dish must contain NONE of these allergens"
    ),
    max_spicy_level: Optional[int] = Query(None, ge=0, le=5),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = catalog.dishes
    items = [d for d in items if restaurant_id is None or d["restaurant_id"] == restaurant_id]
    items = [d for d in items if eq_ci(d["category"], category)]
    items = [d for d in items if max_price is None or d["price"] <= max_price]
    items = [d for d in items if available is None or d["available"] == available]
    items = [d for d in items if has_all(d["dietary_tags"], dietary_tags)]
    items = [d for d in items if max_spicy_level is None or d["spicy_level"] <= max_spicy_level]
    excluded = set(parse_csv_param(exclude_allergens))
    if excluded:
        items = [d for d in items if not (excluded & {a.lower() for a in d["allergens"]})]
    return paginate(items, pagination)


@router.get("/dishes/{dish_id}", response_model=schemas.Dish, summary="Get a dish by id")
def get_dish(dish_id: int, catalog: Catalog = Depends(get_catalog)):
    dish = catalog.dishes_by_id.get(dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail=f"Dish {dish_id} not found")
    return dish


@router.get(
    "/restaurants/{restaurant_id}/dishes", response_model=schemas.Page[schemas.Dish],
    summary="List dishes for a restaurant",
)
def list_dishes_for_restaurant(
    restaurant_id: int, pagination: Pagination = Depends(), catalog: Catalog = Depends(get_catalog),
):
    if restaurant_id not in catalog.restaurants_by_id:
        raise HTTPException(status_code=404, detail=f"Restaurant {restaurant_id} not found")
    items = catalog.dishes_by_restaurant.get(restaurant_id, [])
    return paginate(items, pagination)
