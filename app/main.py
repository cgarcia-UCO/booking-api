"""
app/main.py
------------
FastAPI application entry point. Loads the seed catalog + bookings once at
startup (kept on `app.state`) and wires up all the routers.

Run locally with:
    uvicorn app.main:app --reload

See README.md for the Railway deployment steps.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .data_store import BookingStore, Catalog
from .embeddings import build_indexes
from .middleware import MaxBodySizeMiddleware
from .routers import activities, availability, bookings, cities, customers, hotels, llm, restaurants, semantic_search
from .security import ConcurrencyLimiter, RateLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading catalog from %s ...", config.DATA_DIR)
    catalog = Catalog(config.DATA_DIR)
    booking_store = BookingStore(catalog, config.DATA_DIR / "bookings.csv")
    logger.info(
        "Loaded %d hotels, %d restaurants, %d activities, %d customers, "
        "%d seed bookings (+ %d dynamic bookings restored from storage).",
        len(catalog.hotels), len(catalog.restaurants), len(catalog.activities),
        len(catalog.customers), len(booking_store.seed_bookings), len(booking_store.dynamic_bookings),
    )

    if config.OPENAI_API_KEY:
        logger.info(
            "LLM endpoint enabled: model=%s, %s req/%.0fs per caller (session key or IP), "
            "max %d concurrent, no access token required.",
            config.LLM_MODEL, config.LLM_RATE_LIMIT_MAX_REQUESTS,
            config.LLM_RATE_LIMIT_WINDOW_SECONDS, config.LLM_MAX_CONCURRENT_REQUESTS,
        )
    else:
        logger.info("LLM endpoint disabled (no OPENAI_API_KEY set).")

    if config.COMPUTE_EMBEDDINGS_ON_STARTUP:
        try:
            embedding_indexes = build_indexes(catalog)
        except Exception as exc:  # noqa: BLE001 - semantic search is optional; never take the whole API down for it
            logger.error("Failed to build semantic search embeddings (semantic search will be "
                         "disabled, everything else still works): %s", exc)
            embedding_indexes = {}
    else:
        logger.info("Semantic search embedding computation skipped (COMPUTE_EMBEDDINGS_ON_STARTUP=false).")
        embedding_indexes = {}

    app.state.catalog = catalog
    app.state.booking_store = booking_store
    app.state.llm_rate_limiter = RateLimiter()
    app.state.llm_concurrency_limiter = ConcurrencyLimiter(config.LLM_MAX_CONCURRENT_REQUESTS)
    app.state.embedding_indexes = embedding_indexes

    yield  # application runs here

    logger.info("Shutting down.")


app = FastAPI(
    title="Travel Booking Mock API",
    description=(
        "Read-only catalog of hotels, restaurants and leisure venues, plus "
        "availability checks and a booking endpoint, built for a workshop "
        "setting. See the README in the repository for the full design "
        "notes (in particular the per-session-key booking isolation model)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Hard cap on the /llm/chat request body, enforced before the body is even
# parsed (see app/middleware.py). Scoped narrowly so it never affects any
# other endpoint.
app.add_middleware(MaxBodySizeMiddleware, max_bytes=config.LLM_MAX_HTTP_BODY_BYTES, paths={"/llm/chat"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cities.router)
app.include_router(customers.router)
app.include_router(hotels.router)
app.include_router(restaurants.router)
app.include_router(activities.router)
app.include_router(availability.router)
app.include_router(bookings.router)
app.include_router(llm.router)
app.include_router(semantic_search.router)


@app.get("/", tags=["Health"], summary="API info / health check")
def root():
    return {
        "name": "Travel Booking Mock API",
        "status": "ok",
        "docs": "/docs",
        "max_booking_date": config.MAX_BOOKING_DATE.isoformat(),
    }


@app.get("/health", tags=["Health"], summary="Health check")
def health():
    return {"status": "ok"}
