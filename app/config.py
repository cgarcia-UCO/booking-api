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

# ---------------------------------------------------------------------------
# Per-attendee session isolation
# ---------------------------------------------------------------------------
# Each caller (e.g. each workshop attendee's Colab runtime) is expected to
# generate a random session key once and send it on every call to the
# availability/booking endpoints, in this header. It replaces the earlier
# "one attendee = one IP" model, which breaks down when several attendees
# share an egress IP (as commonly happens with hosted notebook runtimes).
#
# Availability and booking reads/writes always consider "the shared seed
# dataset" + "bookings created under this exact session key" — never
# another session's bookings. The header is REQUIRED on those endpoints.
SESSION_HEADER_NAME = "X-Session-Id"
SESSION_KEY_MIN_LENGTH = 4
SESSION_KEY_MAX_LENGTH = 128

# Marker used as `created_by_session` for the bookings that ship in the
# seed dataset (as opposed to bookings created live through the API). A
# client sending this exact value as their own session key gets it
# rewritten (see app/security.py) so they can never impersonate the seed
# dataset or collide with it.
SEED_SESSION = "seed"

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
# This endpoint exists so that workshop attendees never need an OpenAI key
# of their own: their code calls POST /llm/chat, the server calls OpenAI.
#
# Unlike the original "2-hour public demo" version of this endpoint, the
# workshop scenario has known, identified callers (each with their own
# session key) rather than anonymous internet traffic, so the design here
# is deliberately more permissive on *what* can be sent, while keeping the
# same cost/abuse safety nets:
#   - the OpenAI key itself never leaves the server;
#   - the client supplies the full `messages` list (system prompt +
#     history included) — needed so attendees can experiment with their
#     own system prompts and conversation/state-management strategies,
#     which is the whole point of the exercise;
#   - model and max output tokens are still fixed server-side;
#   - a per-caller rate limit and a global concurrency cap still apply;
#   - the HTTP body is still capped (before parsing) and so is the
#     combined size of all messages — generous enough for real
#     agent/tool-loop prompts, but still bounded;
#   - no access token is required to call the endpoint at all (same as
#     before) — the barrier to entry is intentionally zero.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5-nano")

# Fixed on the server; the client cannot influence this. Passed to OpenAI
# as `max_completion_tokens` (the parameter OpenAI recommends capping,
# since it affects both cost and rate limits).
LLM_MAX_COMPLETION_TOKENS = _env_int("LLM_MAX_COMPLETION_TOKENS", 2000)
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "60"))

# Per-message and whole-conversation size limits. A single message (e.g. a
# system prompt describing several tools) can legitimately be a couple of
# KB; the combined total across all messages in one call is capped more
# tightly to bound per-request cost.
LLM_MAX_MESSAGE_CHARS = _env_int("LLM_MAX_MESSAGE_CHARS", 20000)
LLM_MAX_TOTAL_CHARS = _env_int("LLM_MAX_TOTAL_CHARS", 20000)
LLM_MAX_MESSAGES = _env_int("LLM_MAX_MESSAGES", 40)

# Hard HTTP body-size cap for POST /llm/chat, enforced *before* the body is
# parsed at all (see app/middleware.py). Sized generously above
# LLM_MAX_TOTAL_CHARS to leave room for JSON syntax overhead (roles,
# braces, escaping) across up to LLM_MAX_MESSAGES messages.
LLM_MAX_HTTP_BODY_BYTES = _env_int("LLM_MAX_HTTP_BODY_BYTES", 40000)

# Rate limit: N requests per caller within a sliding window of M seconds.
# The "caller" is the X-Session-Id header if the client sends one (it's
# optional for this endpoint, but the workshop notebook always sends it),
# falling back to the source IP otherwise. Using the session key avoids
# every attendee sharing a single IP-based bucket on a hosted notebook
# runtime. The default (5 req/s) is higher than the original public-demo
# value (1 req/s) since callers are now identified workshop attendees
# rather than anonymous traffic, and agent loops may need to iterate
# quickly.
LLM_RATE_LIMIT_MAX_REQUESTS = _env_int("LLM_RATE_LIMIT_MAX_REQUESTS", 5)
LLM_RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("LLM_RATE_LIMIT_WINDOW_SECONDS", "1"))

# Global concurrency cap across all callers (not per caller). Requests
# beyond this are rejected immediately (503) rather than queued.
LLM_MAX_CONCURRENT_REQUESTS = _env_int("LLM_MAX_CONCURRENT_REQUESTS", 200)

# ---------------------------------------------------------------------------
# Semantic search (see app/embeddings.py)
# ---------------------------------------------------------------------------
# Computing embeddings for the whole catalog takes a little while and costs
# a (small) number of OpenAI API calls. It runs once at startup, gated on
# OPENAI_API_KEY being set. Set this to false to skip it entirely (e.g. for
# fast local iteration when you don't need semantic search).
COMPUTE_EMBEDDINGS_ON_STARTUP = _env_bool("COMPUTE_EMBEDDINGS_ON_STARTUP", True)
