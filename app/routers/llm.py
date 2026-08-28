"""
app/routers/llm.py
--------------------
LLM chat endpoint, implementing the protections agreed for this specific
use case (a short-lived, publicly reachable demo backed by a real OpenAI
budget):

  - The OpenAI API key lives only on the server; it is never sent to, or
    echoed back to, the client.
  - The client may only supply a free-text `message` (max ~1 KB); model,
    system prompt, and max output tokens are all fixed server-side
    (see app/config.py) and are not exposed as request parameters.
  - The HTTP body itself is capped at ~1 KB *before* it is parsed at all
    (see app/middleware.py — this runs ahead of Pydantic validation).
  - Rate limit: 1 request per second per IP.
  - Global concurrency cap (default 100 simultaneous requests, across all
    IPs combined); once reached, new requests are rejected immediately
    (503) rather than queued.
  - No global daily/lifetime budget limit is enforced by this app — that
    is intentionally left to OpenAI's own project-level budget controls
    (see README.md section 9 for the recommended setup).
  - No access token is required for this endpoint, by explicit choice for
    this short, supervised public demo.
  - Upstream errors are turned into a generic message rather than leaking
    internal details to the caller.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, schemas
from ..deps import client_ip
from ..security import ConcurrencyLimiter, RateLimiter

logger = logging.getLogger("llm")

router = APIRouter(prefix="/llm", tags=["LLM"])

_async_client = None


def _get_openai_client():
    global _async_client
    if _async_client is None:
        from openai import AsyncOpenAI  # lazy import: only required if this endpoint is used
        _async_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _async_client


def get_llm_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.llm_rate_limiter


def get_llm_concurrency_limiter(request: Request) -> ConcurrencyLimiter:
    return request.app.state.llm_concurrency_limiter


@router.post(
    "/chat", response_model=schemas.LLMChatResponse,
    summary="Chat with the workshop assistant",
    description=(
        "Stateless LLM chat endpoint: send a free-text `message` (max ~1 KB) "
        "and get back a reply. Model and output length are fixed server-side. "
        f"Rate-limited to {config.LLM_RATE_LIMIT_MAX_REQUESTS} request(s) per "
        f"{config.LLM_RATE_LIMIT_WINDOW_SECONDS:g}s per IP, with a global cap of "
        f"{config.LLM_MAX_CONCURRENT_REQUESTS} concurrent requests."
    ),
)
async def llm_chat(
    payload: schemas.LLMChatRequest,
    ip: str = Depends(client_ip),
    rate_limiter: RateLimiter = Depends(get_llm_rate_limiter),
    concurrency: ConcurrencyLimiter = Depends(get_llm_concurrency_limiter),
):
    if not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="The LLM endpoint is not configured on this server (missing OPENAI_API_KEY).",
        )

    if not rate_limiter.check(ip, config.LLM_RATE_LIMIT_MAX_REQUESTS, config.LLM_RATE_LIMIT_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {config.LLM_RATE_LIMIT_MAX_REQUESTS} request(s) "
                f"per {config.LLM_RATE_LIMIT_WINDOW_SECONDS:g}s per IP. Please slow down."
            ),
        )

    if not await concurrency.try_acquire():
        raise HTTPException(
            status_code=503,
            detail=(
                f"The assistant is handling the maximum of "
                f"{config.LLM_MAX_CONCURRENT_REQUESTS} concurrent requests right now. "
                f"Please try again in a moment."
            ),
        )

    try:
        messages = [
            {"role": "system", "content": config.LLM_SYSTEM_PROMPT},
            {"role": "user", "content": payload.message},
        ]
        try:
            client = _get_openai_client()
            response = await client.chat.completions.create(
                model=config.LLM_MODEL,  # fixed server-side; not client-selectable
                messages=messages,
                max_completion_tokens=config.LLM_MAX_COMPLETION_TOKENS,  # fixed server-side
                timeout=config.LLM_REQUEST_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 - never leak upstream error details to the client
            logger.warning("LLM call failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="The language model is temporarily unavailable. Please try again shortly.",
            )
    finally:
        await concurrency.release()

    choice = response.choices[0]
    usage = None
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    return schemas.LLMChatResponse(reply=choice.message.content or "", model=config.LLM_MODEL, usage=usage)
