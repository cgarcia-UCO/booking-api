"""
app/security.py
-----------------
Small helpers related to the "one attendee = one IP" isolation model and to
protecting the LLM endpoint from abuse:

  - `get_client_ip`: resolves the real client IP behind Railway's proxy.
  - `RateLimiter`: a tiny in-memory sliding-window limiter (good enough for
    a ~50-person workshop on a single server instance).
  - `ConcurrencyLimiter`: a global (not per-IP) async concurrency gate that
    rejects requests outright once a cap is reached, instead of queueing
    them.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """
    Returns the best-effort real client IP.

    Railway (like most PaaS providers) terminates TLS at a reverse proxy and
    forwards requests to the app, so `request.client.host` would otherwise
    always be the proxy's internal address. We look at the standard
    forwarding headers first and fall back to the raw socket address.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # This header can contain a comma-separated chain of proxies; the
        # left-most entry is the original client.
        ip = forwarded_for.split(",")[0].strip()
    else:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            ip = real_ip.strip()
        elif request.client:
            ip = request.client.host
        else:
            ip = "unknown"

    # Defend against a client spoofing the reserved "seed" marker via a
    # forged header, which would otherwise let them inject bookings that
    # block every other attendee.
    from . import config
    if ip.lower() == config.SEED_IP:
        ip = f"spoofed-{ip}"
    return ip


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
    Global (not per-IP) async concurrency gate: at most `max_concurrent`
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
