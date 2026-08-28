from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import schemas
from ..data_store import Catalog
from ..deps import Pagination, get_catalog, paginate
from ..filtering import contains_ci

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=schemas.Page[schemas.Customer], summary="List customers")
def list_customers(
    first_name: Optional[str] = Query(None, description="Case-insensitive substring match"),
    last_name: Optional[str] = Query(None, description="Case-insensitive substring match"),
    pagination: Pagination = Depends(),
    catalog: Catalog = Depends(get_catalog),
):
    items = [
        c for c in catalog.customers
        if contains_ci(c["first_name"], first_name) and contains_ci(c["last_name"], last_name)
    ]
    return paginate(items, pagination)


@router.get("/{customer_id}", response_model=schemas.Customer, summary="Get a customer by id")
def get_customer(customer_id: int, catalog: Catalog = Depends(get_catalog)):
    customer = catalog.customers_by_id.get(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return customer
