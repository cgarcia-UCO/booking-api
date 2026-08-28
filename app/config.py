"""
app/config.py
--------------
Central configuration for the API, read from environment variables (with
sensible defaults for local development). On Railway these are set as
project variables (see the deployment guide in README.md).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

try:
    from dotenv import load_dotenv  # optional, only used for local development
    load_dotenv()
except ImportError:
    pass


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Data / catalog
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))

# Dynamic (API-created) bookings are persisted here so they survive process
# restarts. Point STORAGE_DIR at a Railway volume if you want them to
# survive redeploys too (see README.md).
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DYNAMIC_BOOKINGS_DB = STORAGE_DIR / "dynamic_bookings.sqlite3"

# ---------------------------------------------------------------------------
# Booking rules
# ---------------------------------------------------------------------------
# No bookings may be made for dates after this day (hard requirement).
MAX_BOOKING_DATE = date(2027, 12, 31)

# Marker used as `created_by_ip` for the bookings that ship in the seed
# dataset (as opposed to bookings created live through the API).
SEED_IP = "seed"

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_PAGE_SIZE = _env_int("DEFAULT_PAGE_SIZE", 50)
MAX_PAGE_SIZE = _env_int("MAX_PAGE_SIZE", 500)

# ---------------------------------------------------------------------------
# LLM endpoint
# ---------------------------------------------------------------------------
# Design here follows, point by point, the protections agreed for this
# specific endpoint (see README.md section 9 for the full rationale):
#   - fixed model, fixed max_completion_tokens — the client cannot choose
#     either;
#   - the client may only send a free-text string, capped at ~1 KB, both
#     as a field-level check and as a hard HTTP body-size check performed
#     before the body is ever parsed/tokenized;
#   - a per-IP rate limit of 1 request/second;
#   - a global concurrency cap of 100 in-flight requests (rejected, not
#     queued, once exceeded);
#   - no global daily/lifetime budget cap in this app — that is enforced
#     on the OpenAI project itself (dashboard budget limits), by design;
#   - no access token for this endpoint, by explicit choice for this
#     short-lived public workshop demo.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5-nano")
LLM_SYSTEM_PROMPT = os.environ.get(
    "LLM_SYSTEM_PROMPT",
    "You are a friendly assistant for a hotel/restaurant/leisure booking "
    "demo API used in a workshop. Help attendees understand the catalog "
    "(hotels, restaurants, leisure venues) and how to use the API. Keep "
    "answers concise and do not invent data that is not provided to you.",
)

# Fixed on the server; the client cannot influence this. Passed to OpenAI
# as `max_completion_tokens` (the parameter OpenAI recommends capping,
# since it affects both cost and rate limits).
LLM_MAX_COMPLETION_TOKENS = _env_int("LLM_MAX_COMPLETION_TOKENS", 500)
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "30"))

# ~1 KB budget for the free-text message, enforced twice: once as a hard
# HTTP body-size check (LLM_MAX_HTTP_BODY_BYTES, checked before the body
# is parsed at all) and once as a field-level length check
# (LLM_MAX_MESSAGE_CHARS, on the parsed `message` string). We treat 1 KB
# as ~1024 characters rather than doing exact BPE tokenization, to keep
# this endpoint dependency-light and fast; both are intentionally equal
# by default, per the "same limit at the HTTP layer" requirement.
LLM_MAX_MESSAGE_CHARS = _env_int("LLM_MAX_MESSAGE_CHARS", 1024)
LLM_MAX_HTTP_BODY_BYTES = _env_int("LLM_MAX_HTTP_BODY_BYTES", 1024)

# Rate limit: N requests per IP within a sliding window of M seconds.
# Default: 1 request/second/IP.
LLM_RATE_LIMIT_MAX_REQUESTS = _env_int("LLM_RATE_LIMIT_MAX_REQUESTS", 1)
LLM_RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("LLM_RATE_LIMIT_WINDOW_SECONDS", "1"))

# Global concurrency cap across all callers (not per IP). Requests beyond
# this are rejected immediately (503) rather than queued.
LLM_MAX_CONCURRENT_REQUESTS = _env_int("LLM_MAX_CONCURRENT_REQUESTS", 100)
