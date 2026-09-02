"""
app/embeddings.py
-------------------
Precomputed semantic embeddings for the catalog entities that have a
free-text `description` field (hotels, room types, restaurants, activities,
dishes), plus cosine-similarity search against them.

Uses OpenAI's embeddings API (the same OPENAI_API_KEY as the /llm/chat
endpoint). If no key is configured, no embeddings are computed and the
semantic search endpoint responds with 503 — the same pattern already used
by /llm/chat.

Embeddings are computed once, at server startup, and kept in memory as
plain numpy arrays (this is a small demo catalog — a few thousand vectors
at most — so an in-memory index is more than enough; a real production
system would use a vector database instead).
"""
from __future__ import annotations

import logging

import numpy as np

from . import config

logger = logging.getLogger("embeddings")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 100

# Entity types that have a `description` field and are exposed to semantic search.
_ENTITY_SOURCES = {
    "hotel": "hotel_id",
    "room_type": "room_type_id",
    "restaurant": "restaurant_id",
    "activity": "activity_id",
    "dish": "dish_id",
}


class EmbeddingIndex:
    """A single entity type's embeddings: parallel ids + an (n, dim) matrix of
    L2-normalized vectors, so a plain dot product IS the cosine similarity."""

    def __init__(self, ids: list[int], vectors: np.ndarray):
        self.ids = ids
        self.vectors = vectors

    def search(self, query_vector: np.ndarray, limit: int = 5) -> list[tuple[int, float]]:
        query_vector = query_vector / (np.linalg.norm(query_vector) + 1e-10)
        scores = self.vectors @ query_vector
        top_indices = np.argsort(-scores)[:limit]
        return [(self.ids[i], float(scores[i])) for i in top_indices]


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-10, None)


def _embed_texts_sync(texts: list[str]) -> np.ndarray:
    """Blocking embeddings call, used once at startup (batches to keep each
    request reasonably sized)."""
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start:start + EMBEDDING_BATCH_SIZE]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in response.data)
    return _l2_normalize(np.array(vectors, dtype=np.float32))


async def embed_text_async(text: str) -> np.ndarray:
    """Non-blocking embeddings call for a single query, used per-request."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    response = await client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
    vector = np.array(response.data[0].embedding, dtype=np.float32)
    return vector / (np.linalg.norm(vector) + 1e-10)


def build_indexes(catalog) -> dict[str, EmbeddingIndex]:
    """
    Builds one EmbeddingIndex per entity type listed in _ENTITY_SOURCES.
    Returns an empty dict (and logs why) if OPENAI_API_KEY isn't set.
    """
    if not config.OPENAI_API_KEY:
        logger.info("Semantic search disabled (no OPENAI_API_KEY set).")
        return {}

    entity_lists = {
        "hotel": catalog.hotels,
        "room_type": catalog.room_types,
        "restaurant": catalog.restaurants,
        "activity": catalog.activities,
        "dish": catalog.dishes,
    }

    indexes: dict[str, EmbeddingIndex] = {}
    for entity_type, id_field in _ENTITY_SOURCES.items():
        items = entity_lists[entity_type]
        if not items:
            continue
        try:
            ids = [item[id_field] for item in items]
            texts = [item["description"] for item in items]
            logger.info("Computing %d embeddings for '%s' entities...", len(texts), entity_type)
            vectors = _embed_texts_sync(texts)
            indexes[entity_type] = EmbeddingIndex(ids, vectors)
        except Exception as exc:  # noqa: BLE001 - one entity type failing shouldn't break the others
            logger.error("Failed to build the embedding index for '%s' (skipping it): %s", entity_type, exc)

    if indexes:
        logger.info("Semantic search index ready for: %s", ", ".join(indexes.keys()))
    return indexes
