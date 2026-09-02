"""
app/routers/semantic_search.py
--------------------------------
Semantic search over catalog entities that have a free-text `description`
(hotels, room types, restaurants, activities, dishes), using precomputed
OpenAI embeddings compared by cosine similarity against the caller's query
(embedded on the fly). Requires OPENAI_API_KEY — same gating pattern as
/llm/chat.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, schemas
from ..data_store import Catalog
from ..deps import get_catalog
from ..embeddings import embed_text_async

router = APIRouter(prefix="/semantic-search", tags=["Semantic search"])

_ENTITY_LOOKUP = {
    "hotel": lambda catalog: catalog.hotels_by_id,
    "room_type": lambda catalog: catalog.room_types_by_id,
    "restaurant": lambda catalog: catalog.restaurants_by_id,
    "activity": lambda catalog: catalog.activities_by_id,
    "dish": lambda catalog: catalog.dishes_by_id,
}


@router.post(
    "", response_model=schemas.SemanticSearchResponse,
    summary="Semantic search over catalog descriptions",
    description=(
        "Finds the entities of the given type whose `description` is most semantically similar "
        "to `query` (cosine similarity over OpenAI embeddings), rather than requiring an exact "
        "keyword match. Useful for open-ended requests like 'a quiet romantic hotel with a pool' "
        "that don't map cleanly onto the exact-match filters of the regular catalog endpoints."
    ),
)
async def semantic_search(
    payload: schemas.SemanticSearchRequest,
    request: Request,
    catalog: Catalog = Depends(get_catalog),
):
    if not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Semantic search is not configured on this server (missing OPENAI_API_KEY).",
        )

    indexes = request.app.state.embedding_indexes
    index = indexes.get(payload.entity_type)
    if index is None:
        raise HTTPException(
            status_code=503,
            detail=f"No embedding index is available for entity_type='{payload.entity_type}' "
                   f"(it may still be building, or the catalog has no items of this type).",
        )

    query_vector = await embed_text_async(payload.query)
    matches = index.search(query_vector, limit=payload.limit)

    lookup = _ENTITY_LOOKUP[payload.entity_type](catalog)
    results = [
        schemas.SemanticSearchResult(entity_type=payload.entity_type, id=entity_id, similarity=score,
                                      entity=lookup[entity_id])
        for entity_id, score in matches if entity_id in lookup
    ]
    return schemas.SemanticSearchResponse(query=payload.query, results=results)
