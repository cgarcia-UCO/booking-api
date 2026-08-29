"""
app/security.py
-----------------
Small helpers related to:

  - the "one attendee = one session key" isolation model
    (`session_key` / `optional_session_key` / `get_client_ip`);
  - protecting the LLM endpoint from abuse
    (`RateLimiter`, `ConcurrencyLimiter`).
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Header, HTTPException, Request

from . import config


def get_client_ip(request: Request) -> str:
    """
    Best-effort real client IP, used only as a fallback identity for the
    LLM rate limiter when no X-Session-Id header is sent (see
    `optional_session_key` below). Not used for booking isolation anymore
    — see `session_key`.

    Railway (like most PaaS providers) terminates TLS at a reverse proxy
    and forwards requests to the app, so `request.client.host` would
    otherwise always be the proxy's internal address. We look at the
    standard forwarding headers first and fall back to the raw socket
    address.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # This header can contain a comma-separated chain of proxies; the
        # left-most entry is the original client.
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


def _clean_session_key(value: str) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(
            status_code=422, detail=f"'{config.SESSION_HEADER_NAME}' header must not be empty."
        )
    if len(value) < config.SESSION_KEY_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"'{config.SESSION_HEADER_NAME}' must be at least "
                   f"{config.SESSION_KEY_MIN_LENGTH} characters long.",
        )
    if len(value) > config.SESSION_KEY_MAX_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"'{config.SESSION_HEADER_NAME}' must be at most "
                   f"{config.SESSION_KEY_MAX_LENGTH} characters long.",
        )
    # Defend against a client spoofing the reserved "seed" marker, which
    # would otherwise let them inject bookings that block every other
    # attendee (or read the seed dataset under a different guise).
    if value.lower() == config.SEED_SESSION:
        value = f"spoofed-{value}"
    return value


def session_key(
    x_session_id: str = Header(
        ...,
        alias=config.SESSION_HEADER_NAME,
        description=(
            "Required per-attendee identifier. Generate a random string once per "
            "notebook/client run (e.g. `secrets.token_hex(8)` in Python) and send the "
            "same value on every call — this is what keeps your bookings isolated from "
            "everyone else's."
        ),
    )
) -> str:
    """Required session-key dependency for availability/booking endpoints."""
    return _clean_session_key(x_session_id)


def optional_session_key(
    x_session_id: Optional[str] = Header(default=None, alias=config.SESSION_HEADER_NAME)
) -> Optional[str]:
    """Optional session-key dependency (used by /llm/chat's rate limiter)."""
    if x_session_id is None:
        return None
    return _clean_session_key(x_session_id)


class RateLimiter:
    """
    Minimal in-memory per-key rate limiter using a sliding window.

    Not distributed (state lives in the process' memory), which is fine for
    a single-instance deployment like the one described in the README.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, max_hits: int, window_seconds: float) -> bool:
        """Records a hit for `key` and returns True if it is still within
        the allowed rate, False if the limit has been exceeded."""
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= max_hits:
                return False
            q.append(now)
            return True

    def count(self, key: str, window_seconds: float) -> int:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            return len(q)


class ConcurrencyLimiter:
    """
    Global (not per-caller) async concurrency gate: at most `max_concurrent`
    callers may hold it at once. `try_acquire()` never waits — if the cap
    is already reached it returns False immediately, so the caller can
    reject the request (e.g. HTTP 503) instead of silently queueing it.
    """

    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max_concurrent
        self._count = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._count >= self.max_concurrent:
                return False
            self._count += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def current(self) -> int:
        return self._count
