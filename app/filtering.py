"""
app/filtering.py
------------------
Small, dependency-free helpers used by the catalog routers to implement
query-parameter filtering (case-insensitive string matching, "must have
all/any of these tags" checks for list fields, etc.).
"""
from __future__ import annotations

from typing import Optional


def parse_csv_param(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip().lower() for v in value.split(",") if v.strip()]


def has_all(items: list[str], required_csv: Optional[str]) -> bool:
    """True if `items` contains every value in the comma-separated `required_csv`."""
    required = parse_csv_param(required_csv)
    if not required:
        return True
    items_lower = {i.lower() for i in items}
    return all(r in items_lower for r in required)


def has_any(items: list[str], required_csv: Optional[str]) -> bool:
    """True if `items` contains at least one value from the comma-separated `required_csv`."""
    required = parse_csv_param(required_csv)
    if not required:
        return True
    items_lower = {i.lower() for i in items}
    return any(r in items_lower for r in required)


def eq_ci(value: Optional[str], expected: Optional[str]) -> bool:
    """Case-insensitive equality; True (no filtering) if `expected` is None."""
    if expected is None:
        return True
    return (value or "").lower() == expected.lower()


def contains_ci(haystack: Optional[str], needle: Optional[str]) -> bool:
    """Case-insensitive substring match; True (no filtering) if `needle` is None."""
    if needle is None:
        return True
    return needle.lower() in (haystack or "").lower()


def in_range(value, min_value=None, max_value=None) -> bool:
    if min_value is not None and value < min_value:
        return False
    if max_value is not None and value > max_value:
        return False
    return True
