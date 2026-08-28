"""
app/deps.py
------------
Shared FastAPI dependencies: access to the in-memory catalog / booking
store (created once at startup and kept on `app.state`), the requester's
IP address, and a small pagination helper reused by every list endpoint.
"""
from __future__ import annotations

from typing import TypeVar

from fastapi import Query, Request

from . import config
from .data_store import BookingStore, Catalog
from .security import get_client_ip

T = TypeVar("T")


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


def get_booking_store(request: Request) -> BookingStore:
    return request.app.state.booking_store


def client_ip(request: Request) -> str:
    return get_client_ip(request)


class Pagination:
    def __init__(
        self,
        limit: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE,
                            description="Max number of items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ):
        self.limit = limit
        self.offset = offset


def paginate(items: list, pagination: Pagination) -> dict:
    total = len(items)
    page_items = items[pagination.offset: pagination.offset + pagination.limit]
    return {
        "total": total,
        "count": len(page_items),
        "limit": pagination.limit,
        "offset": pagination.offset,
        "items": page_items,
    }
