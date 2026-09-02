"""
app/routers/llm.py
--------------------
LLM chat endpoint for the workshop: a thin, stateless proxy to OpenAI
Chat Completions. Attendees never need an API key of their own — their
code calls POST /llm/chat with the full `messages` list they want to send
(system prompt + history included), and the server relays it to OpenAI.

Protections kept from the original design (see app/config.py for the
full rationale):
  - the OpenAI API key never leaves the server;
  - model and max output tokens are fixed server-side, not client-chosen;
  - the HTTP body is capped *before* it is parsed at all (see
    app/middleware.py), and the combined size of all messages is capped
    again at the Pydantic level;
  - a rate limit and a global concurrency cap protect the shared OpenAI
    budget from a runaway loop in someone's agent code.

Difference from the original public-demo design: the client now supplies
the entire `messages` array (not just a single free-text string), since
designing the system prompt and managing conversation history is the
point of the exercise. The rate-limit identity is the caller's
X-Session-Id if provided (recommended — this is what the workshop
notebook always sends), falling back to source IP otherwise, so that
attendees sharing a single hosted-notebook egress IP don't all compete
for one shared bucket.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, schemas
from ..deps import client_ip, optional_session_key
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
    summary="Chat with the LLM (relayed to OpenAI)",
    description=(
        "Send the full `messages` list (system prompt + history + latest user "
        "turn, OpenAI Chat Completions format) and get back the model's reply. "
        "Model and output length are fixed server-side. Send your X-Session-Id "
        "header on this endpoint too, so your rate limit is tracked separately "
        f"from other attendees. Rate-limited to {config.LLM_RATE_LIMIT_MAX_REQUESTS} "
        f"request(s) per {config.LLM_RATE_LIMIT_WINDOW_SECONDS:g}s per caller, with a "
        f"global cap of {config.LLM_MAX_CONCURRENT_REQUESTS} concurrent requests."
    ),
)
async def llm_chat(
    payload: schemas.LLMChatRequest,
    ip: str = Depends(client_ip),
    session: str = Depends(optional_session_key),
    rate_limiter: RateLimiter = Depends(get_llm_rate_limiter),
    concurrency: ConcurrencyLimiter = Depends(get_llm_concurrency_limiter),
):
    if not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="The LLM endpoint is not configured on this server (missing OPENAI_API_KEY).",
        )

    rate_limit_key = session or ip
    if not rate_limiter.check(rate_limit_key, config.LLM_RATE_LIMIT_MAX_REQUESTS,
                               config.LLM_RATE_LIMIT_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {config.LLM_RATE_LIMIT_MAX_REQUESTS} request(s) "
                f"per {config.LLM_RATE_LIMIT_WINDOW_SECONDS:g}s. Please slow down. "
                + ("" if session else "Tip: send an X-Session-Id header so your limit isn't "
                                       "shared with other callers on the same network.")
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
        messages = [{"role": m.role, "content": m.content} for m in payload.messages]
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

    # return schemas.LLMChatResponse(reply=choice.message.content or "", model=config.LLM_MODEL, usage=usage)
    return schemas.LLMChatResponse(reply=choice.message.content or "", usage=usage)
